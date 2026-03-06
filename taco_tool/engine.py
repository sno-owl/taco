from __future__ import annotations

import csv
import importlib.util
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .markdown import markdown_to_text


SIGNATURE_PROFILE_OPTIONS: dict[str, bool] = {
    "sourceKeyOverlap": False,
    "sourceLSA": False,
    "sourceLDA": False,
    "sourceWord2vec": False,
    "wordsAll": True,
    "wordsContent": True,
    "wordsFunction": False,
    "wordsNoun": True,
    "wordsPronoun": True,
    "wordsArgument": True,
    "wordsVerb": True,
    "wordsAdjective": False,
    "wordsAdverb": False,
    "overlapSentence": True,
    "overlapParagraph": False,
    "overlapAdjacent": True,
    "overlapAdjacent2": True,
    "otherTTR": True,
    "otherConnectives": True,
    "otherGivenness": True,
    "overlapLSA": True,
    "overlapLDA": False,
    "overlapWord2vec": True,
    "overlapSynonym": True,
    "overlapNgrams": True,
    "outputTagged": False,
    "outputDiagnostic": False,
}


FOCUSED_PROFILE_OPTIONS: dict[str, bool] = {
    "sourceKeyOverlap": False,
    "sourceLSA": False,
    "sourceLDA": False,
    "sourceWord2vec": False,
    "wordsAll": False,
    "wordsContent": False,
    "wordsFunction": False,
    "wordsNoun": True,
    "wordsPronoun": False,
    "wordsArgument": True,
    "wordsVerb": True,
    "wordsAdjective": False,
    "wordsAdverb": False,
    "overlapSentence": True,
    "overlapParagraph": False,
    "overlapAdjacent": True,
    "overlapAdjacent2": False,
    "otherTTR": True,
    "otherConnectives": True,
    "otherGivenness": False,
    "overlapLSA": True,
    "overlapLDA": False,
    "overlapWord2vec": True,
    "overlapSynonym": False,
    "overlapNgrams": False,
    "outputTagged": False,
    "outputDiagnostic": False,
}


PROFILE_OPTIONS: dict[str, dict[str, bool]] = {
    "signature": SIGNATURE_PROFILE_OPTIONS,
    "focused": FOCUSED_PROFILE_OPTIONS,
}


@dataclass
class AnalysisResult:
    input_markdown: Path
    csv_path: Path
    profile: str
    metrics: dict[str, Any]
    data_dir: Path


def _candidate_data_dirs(explicit_data_dir: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_data_dir:
        candidates.append(Path(explicit_data_dir).expanduser().resolve())

    env_data = os.environ.get("TACO_DATA_DIR")
    if env_data:
        candidates.append(Path(env_data).expanduser().resolve())

    exe_share = Path(sys.executable).resolve().parent.parent / "share" / "taco"
    candidates.append(exe_share)

    package_repo = Path(__file__).resolve().parents[1]
    candidates.append(package_repo)

    candidates.append(Path.cwd())

    deduped: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        key = str(item)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def find_data_dir(explicit_data_dir: str | None = None) -> Path:
    for candidate in _candidate_data_dirs(explicit_data_dir):
        if (candidate / "TAACOnoGUI.py").exists() and (candidate / "wn_noun_2.txt").exists():
            return candidate
    searched = "\n".join(str(x) for x in _candidate_data_dirs(explicit_data_dir))
    raise FileNotFoundError(
        "Unable to locate TAACO data directory. Set --data-dir or TACO_DATA_DIR. "
        f"Searched:\n{searched}"
    )


def _load_run_taaco(data_dir: Path):
    module_path = data_dir / "TAACOnoGUI.py"
    spec = importlib.util.spec_from_file_location("_taaco_runtime", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load TAACO module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "runTAACO"):
        raise RuntimeError(f"runTAACO not found in {module_path}")
    return module.runTAACO


def _parse_metric(value: str) -> Any:
    if value is None:
        return None
    trimmed = value.strip()
    if trimmed == "":
        return None
    try:
        return float(trimmed)
    except ValueError:
        return trimmed


def _read_metrics(csv_path: Path) -> dict[str, Any]:
    with csv_path.open("r", encoding="utf-8", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)
    return {key: _parse_metric(value) for key, value in row.items()}


def run_analysis(
    input_markdown: str,
    *,
    profile: str = "signature",
    output_csv: str | None = None,
    data_dir: str | None = None,
) -> AnalysisResult:
    markdown_path = Path(input_markdown).expanduser().resolve()
    if not markdown_path.exists():
        raise FileNotFoundError(f"Input markdown does not exist: {markdown_path}")
    if markdown_path.suffix.lower() != ".md":
        raise ValueError(f"Input must be a .md file: {markdown_path}")

    if profile not in PROFILE_OPTIONS:
        known = ", ".join(sorted(PROFILE_OPTIONS.keys()))
        raise ValueError(f"Unknown profile '{profile}'. Expected one of: {known}")

    chosen_data_dir = find_data_dir(data_dir)
    run_taaco = _load_run_taaco(chosen_data_dir)

    raw_markdown = markdown_path.read_text(encoding="utf-8", errors="ignore")
    plain_text = markdown_to_text(raw_markdown)
    if not plain_text:
        raise ValueError("Markdown content is empty after normalization.")

    out_csv_path = Path(output_csv).expanduser().resolve() if output_csv else None
    if out_csv_path is not None:
        out_csv_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="taco_single_doc_") as tmpdir:
        tmp_input_dir = Path(tmpdir) / "input"
        tmp_input_dir.mkdir(parents=True, exist_ok=True)
        tmp_txt_path = tmp_input_dir / f"{markdown_path.stem}.txt"
        tmp_txt_path.write_text(plain_text, encoding="utf-8")

        if out_csv_path is None:
            out_csv_path = Path(tmpdir) / "analysis.csv"

        previous_cwd = Path.cwd()
        prior_data_dir_env = os.environ.get("TACO_DATA_DIR")
        try:
            os.chdir(chosen_data_dir)
            os.environ["TACO_DATA_DIR"] = str(chosen_data_dir)
            # Suppress noisy stdout from TAACOnoGUI (Loading Spacy,
            # Loading vector spaces, processing N of M files, etc.)
            _real_stdout = sys.stdout
            sys.stdout = open(os.devnull, "w")
            try:
                run_taaco(
                    str(tmp_input_dir),
                    str(out_csv_path),
                    dict(PROFILE_OPTIONS[profile]),
                    gui=False,
                    source_text="",
                )
            finally:
                sys.stdout.close()
                sys.stdout = _real_stdout
        except Exception as exc:
            message = str(exc)
            if "en_core_web_sm" in message or "Can't find model" in message:
                raise RuntimeError(
                    "spaCy model 'en_core_web_sm' is missing. Install it with: "
                    "python -m spacy download en_core_web_sm"
                ) from exc
            raise
        finally:
            if prior_data_dir_env is None:
                os.environ.pop("TACO_DATA_DIR", None)
            else:
                os.environ["TACO_DATA_DIR"] = prior_data_dir_env
            os.chdir(previous_cwd)

        metrics = _read_metrics(out_csv_path)

        if output_csv is None:
            # Persist temporary output for caller readability.
            persist_dir = Path(tempfile.mkdtemp(prefix="taco_output_"))
            persisted = persist_dir / out_csv_path.name
            persisted.write_text(out_csv_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
            out_csv_path = persisted

    return AnalysisResult(
        input_markdown=markdown_path,
        csv_path=out_csv_path,
        profile=profile,
        metrics=metrics,
        data_dir=chosen_data_dir,
    )
