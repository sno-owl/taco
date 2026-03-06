from __future__ import annotations

import argparse
import json
import sys
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Any

from taco_tool.buildinfo import cli_version_string
from taco_tool.engine import PROFILE_OPTIONS, find_data_dir, run_analysis
from taco_tool.signatures import evaluate_signatures, load_signatures, render_text_report

try:
    from requests.exceptions import RequestsDependencyWarning

    warnings.filterwarnings("ignore", category=RequestsDependencyWarning)
except Exception:
    pass


EXAMPLES = """Examples:
  taco analyze specs/RIF.md
  taco analyze specs/SIF.md --profile focused --csv-out /tmp/sif.csv --format json
  taco lint specs/RIF.md
  taco doctor
  taco signatures
"""

PRECOMMIT_SNIPPET = """repos:
  - repo: local
    hooks:
      - id: taco-cohesion
        name: taco cohesion lint
        entry: scripts/lint_markdown_taco.sh
        language: system
        files: ^specs/.*\\.md$
"""


class Formatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


def _signature_to_json(signature_result) -> dict[str, Any]:
    payload = asdict(signature_result)
    payload["rules"] = [asdict(rule) for rule in signature_result.rules]
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taco",
        description=(
            "TAACO-powered markdown cohesion CLI.\n"
            "Analyze one markdown document, detect suspect cohesion signatures,\n"
            "and emit actionable rewrite guidance."
        ),
        epilog=EXAMPLES,
        formatter_class=Formatter,
    )
    parser.add_argument("--version", action="version", version=cli_version_string("taco"))

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("input_markdown", help="Path to a single .md file")
    common.add_argument(
        "--profile",
        default="signature",
        choices=sorted(PROFILE_OPTIONS.keys()),
        help="TAACO option profile",
    )
    common.add_argument(
        "--data-dir",
        help="Directory containing TAACOnoGUI.py and TAACO data files",
    )
    common.add_argument("--signatures-file", help="Optional custom signatures JSON file")
    common.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )

    analyze = sub.add_parser(
        "analyze",
        parents=[common],
        formatter_class=Formatter,
        help="Run analysis and print report",
        description="Analyze one markdown file and print a full cohesion report.",
    )
    analyze.add_argument("--csv-out", help="Optional path for TAACO output CSV")

    lint = sub.add_parser(
        "lint",
        parents=[common],
        formatter_class=Formatter,
        help="Lint mode (exit 2 when suspect signatures match)",
        description=(
            "Analyze one markdown file in lint mode.\n"
            "Exit code: 0=pass, 2=suspect signatures matched, 1=runtime error."
        ),
    )
    lint.add_argument(
        "--fail-on",
        default="high,medium",
        help=(
            "Comma-separated severities that should fail the lint "
            "(e.g. high or high,medium)"
        ),
    )

    sub.add_parser(
        "signatures",
        formatter_class=Formatter,
        help="Print loaded signatures as JSON",
        description="Print the bundled (or custom) signature library.",
    ).add_argument("--signatures-file", help="Optional custom signatures JSON file")

    doctor = sub.add_parser(
        "doctor",
        formatter_class=Formatter,
        help="Check local runtime health",
        description="Validate data directory, TAACO runtime files, and spaCy model readiness.",
    )
    doctor.add_argument("--data-dir", help="Explicit TAACO data directory")
    doctor.add_argument("--format", choices=["text", "json"], default="text")

    init_hook = sub.add_parser(
        "init-precommit",
        formatter_class=Formatter,
        help="Print pre-commit config snippet",
        description="Print a ready-to-paste pre-commit hook snippet for markdown cohesion linting.",
    )
    init_hook.add_argument("--format", choices=["text", "json"], default="text")

    return parser


def cmd_signatures(args: argparse.Namespace) -> int:
    signatures = load_signatures(args.signatures_file)
    print(json.dumps(signatures, indent=2))
    return 0


def _render_payload(args: argparse.Namespace, payload: dict[str, Any], text_report: str) -> None:
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(text_report)


def cmd_analyze_or_lint(args: argparse.Namespace, lint_mode: bool) -> int:
    try:
        analysis = run_analysis(
            args.input_markdown,
            profile=args.profile,
            output_csv=getattr(args, "csv_out", None),
            data_dir=args.data_dir,
        )
        signatures = load_signatures(args.signatures_file)
        signature_results = evaluate_signatures(analysis.metrics, signatures)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    matched = [item for item in signature_results if item.matched]
    text_report = render_text_report(analysis.input_markdown, analysis.metrics, signature_results)

    payload = {
        "input_markdown": str(analysis.input_markdown),
        "csv_path": str(analysis.csv_path),
        "profile": analysis.profile,
        "data_dir": str(analysis.data_dir),
        "matched_count": len(matched),
        "metrics": analysis.metrics,
        "signatures": [_signature_to_json(item) for item in signature_results],
    }
    _render_payload(args, payload, text_report)

    if lint_mode:
        fail_on = {item.strip().lower() for item in args.fail_on.split(",") if item.strip()}
        if any(item.severity in fail_on for item in matched):
            return 2
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: dict[str, Any] = {
        "data_dir": None,
        "taaco_module": False,
        "spacy_import": False,
        "spacy_model": False,
    }
    errors: list[str] = []

    try:
        data_dir = find_data_dir(args.data_dir)
        checks["data_dir"] = str(data_dir)
        checks["taaco_module"] = (data_dir / "TAACOnoGUI.py").exists()
    except Exception as exc:
        errors.append(str(exc))

    try:
        import spacy  # noqa: F401

        checks["spacy_import"] = True
        try:
            spacy.load("en_core_web_sm")
            checks["spacy_model"] = True
        except Exception as exc:
            errors.append(f"spaCy model check failed: {exc}")
    except Exception as exc:
        errors.append(f"spaCy import failed: {exc}")

    ok = all([checks["data_dir"], checks["taaco_module"], checks["spacy_import"], checks["spacy_model"]])

    if args.format == "json":
        print(json.dumps({"ok": ok, "checks": checks, "errors": errors}, indent=2))
    else:
        print("taco doctor")
        print(f"  data_dir: {checks['data_dir']}")
        print(f"  taaco_module: {checks['taaco_module']}")
        print(f"  spacy_import: {checks['spacy_import']}")
        print(f"  spacy_model: {checks['spacy_model']}")
        if errors:
            print("  errors:")
            for item in errors:
                print(f"    - {item}")
        print(f"  status: {'ok' if ok else 'not-ready'}")

    return 0 if ok else 1


def cmd_init_precommit(args: argparse.Namespace) -> int:
    if args.format == "json":
        print(json.dumps({"pre_commit_config_snippet": PRECOMMIT_SNIPPET}, indent=2))
    else:
        print(PRECOMMIT_SNIPPET)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "signatures":
        return cmd_signatures(args)
    if args.command == "analyze":
        return cmd_analyze_or_lint(args, lint_mode=False)
    if args.command == "lint":
        return cmd_analyze_or_lint(args, lint_mode=True)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "init-precommit":
        return cmd_init_precommit(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
