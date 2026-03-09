#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"

KNOWN_GOOD_GLOB="${KNOWN_GOOD_GLOB:-ELLIPSE_Sample/*.txt}"
SPECS_GLOB="${SPECS_GLOB:-leaf/specs/*.md}"
OUTPUT_CSV="${OUTPUT_CSV:-${DIST_DIR}/calibration.csv}"
PERCENTILES_CSV="${PERCENTILES_CSV:-${DIST_DIR}/calibration_percentiles.csv}"
THRESHOLDS_CSV="${THRESHOLDS_CSV:-${DIST_DIR}/calibration_threshold_positions.csv}"
REPORT_PATH="${REPORT_PATH:-${DIST_DIR}/calibration_report.txt}"
SIGNATURES_FILE="${SIGNATURES_FILE:-${ROOT_DIR}/taco_tool/signature_data/cohesion_signatures.json}"
TACO_BIN="${TACO_BIN:-taco}"
PROFILE="${PROFILE:-signature}"
MAX_FILES_PER_CORPUS="${MAX_FILES_PER_CORPUS:-0}"

METRICS=(
  "word2vec_1_all_sent"
  "lsa_1_all_sent"
  "all_connective"
  "adjacent_overlap_binary_argument_sent"
  "adjacent_overlap_binary_noun_sent"
  "noun_ttr"
  "content_ttr"
  "repeated_content_lemmas"
  "syn_overlap_sent_noun"
)

if ! command -v "${TACO_BIN}" >/dev/null 2>&1; then
  echo "Missing required command: ${TACO_BIN}" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Missing required command: python3" >&2
  exit 1
fi

mkdir -p "${DIST_DIR}" "$(dirname "${OUTPUT_CSV}")" "$(dirname "${REPORT_PATH}")"

header="corpus,file"
for metric in "${METRICS[@]}"; do
  header+=",${metric}"
done
printf '%s\n' "${header}" > "${OUTPUT_CSV}"

tmp_json="$(mktemp)"
trap 'rm -f "${tmp_json}"' EXIT

collect_corpus() {
  local corpus="$1"
  local glob_pattern="$2"
  local -a matches=()

  while IFS= read -r path; do
    matches+=("${path}")
  done < <(cd "${ROOT_DIR}" && compgen -G "${glob_pattern}" | sort || true)

  if [[ "${#matches[@]}" -eq 0 ]]; then
    echo "[warn] ${corpus}: no files matched ${glob_pattern}" >&2
    return 0
  fi

  if [[ "${MAX_FILES_PER_CORPUS}" =~ ^[1-9][0-9]*$ ]] && (( MAX_FILES_PER_CORPUS < ${#matches[@]} )); then
    matches=("${matches[@]:0:${MAX_FILES_PER_CORPUS}}")
  fi

  echo "[collect] ${corpus}: ${#matches[@]} files"
  local idx=0
  local rel_path=""
  for rel_path in "${matches[@]}"; do
    idx=$((idx + 1))
    echo "  - [${corpus}] ${idx}/${#matches[@]} ${rel_path}"
    if ! (cd "${ROOT_DIR}" && "${TACO_BIN}" analyze "${rel_path}" --profile "${PROFILE}" --format json > "${tmp_json}"); then
      echo "[warn] analyze failed for ${rel_path}" >&2
      continue
    fi

    python3 - "${tmp_json}" "${corpus}" "${rel_path}" "${METRICS[@]}" >> "${OUTPUT_CSV}" <<'PY'
import csv
import json
import sys

json_path = sys.argv[1]
corpus = sys.argv[2]
rel_path = sys.argv[3]
metrics = sys.argv[4:]

with open(json_path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)

values = payload.get("metrics", {})
row = [corpus, rel_path]
for metric in metrics:
    value = values.get(metric)
    row.append("" if value is None else value)

csv.writer(sys.stdout).writerow(row)
PY
  done
}

collect_corpus "known_good" "${KNOWN_GOOD_GLOB}"
collect_corpus "specs" "${SPECS_GLOB}"

row_count="$(($(wc -l < "${OUTPUT_CSV}") - 1))"
if (( row_count <= 0 )); then
  echo "No calibration rows were collected." >&2
  exit 1
fi

python3 - \
  "${OUTPUT_CSV}" \
  "${SIGNATURES_FILE}" \
  "${REPORT_PATH}" \
  "${PERCENTILES_CSV}" \
  "${THRESHOLDS_CSV}" <<'PY'
import bisect
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

csv_path = Path(sys.argv[1])
signatures_path = Path(sys.argv[2])
report_path = Path(sys.argv[3])
percentiles_path = Path(sys.argv[4])
thresholds_path = Path(sys.argv[5])

metrics = [
    "word2vec_1_all_sent",
    "lsa_1_all_sent",
    "all_connective",
    "adjacent_overlap_binary_argument_sent",
    "adjacent_overlap_binary_noun_sent",
    "noun_ttr",
    "content_ttr",
    "repeated_content_lemmas",
    "syn_overlap_sent_noun",
]

anchors = {
    "noun_ttr": ("known_good", 90, ">="),
    "content_ttr": ("known_good", 90, ">="),
    "adjacent_overlap_binary_noun_sent": ("known_good", 10, "<="),
    "repeated_content_lemmas": ("known_good", 10, "<="),
    "syn_overlap_sent_noun": ("known_good", 10, "<="),
    "word2vec_1_all_sent": ("known_good", 75, ">="),
    "all_connective": ("known_good", 10, "<="),
}


def to_float(raw):
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def percentile(values, pct):
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * (pct / 100.0)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    frac = pos - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


def rank_percent(values, threshold):
    if not values:
        return None
    xs = sorted(values)
    idx = bisect.bisect_right(xs, threshold)
    return 100.0 * idx / len(xs)


by_corpus = defaultdict(lambda: defaultdict(list))
counts = defaultdict(int)

with csv_path.open("r", encoding="utf-8", newline="") as handle:
    reader = csv.DictReader(handle)
    for row in reader:
        corpus = row.get("corpus", "unknown")
        counts[corpus] += 1
        counts["all"] += 1
        for metric in metrics:
            value = to_float(row.get(metric))
            if value is None:
                continue
            by_corpus[corpus][metric].append(value)
            by_corpus["all"][metric].append(value)

corpora = sorted([key for key in counts.keys() if key != "all"]) + ["all"]

percentiles_rows = []
for corpus in corpora:
    for metric in metrics:
        values = by_corpus[corpus][metric]
        percentiles_rows.append(
            {
                "corpus": corpus,
                "metric": metric,
                "count": len(values),
                "p10": percentile(values, 10),
                "p25": percentile(values, 25),
                "p50": percentile(values, 50),
                "p75": percentile(values, 75),
                "p90": percentile(values, 90),
            }
        )

with percentiles_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=["corpus", "metric", "count", "p10", "p25", "p50", "p75", "p90"],
    )
    writer.writeheader()
    writer.writerows(percentiles_rows)

with signatures_path.open("r", encoding="utf-8") as handle:
    signatures = json.load(handle).get("signatures", [])

threshold_rows = []
for sig in signatures:
    sig_id = str(sig.get("id", "unknown"))
    for rule in sig.get("rules", []):
        metric = str(rule.get("metric", ""))
        if metric not in metrics:
            continue
        op = str(rule.get("operator", ""))
        value = to_float(rule.get("value"))
        if value is None:
            continue
        row = {
            "signature_id": sig_id,
            "metric": metric,
            "operator": op,
            "threshold": value,
        }
        for corpus in corpora:
            values = by_corpus[corpus][metric]
            rp = rank_percent(values, value)
            row[f"threshold_percentile_{corpus}"] = rp
            if rp is None:
                flagged = None
            elif op == ">=":
                flagged = max(0.0, 100.0 - rp)
            elif op == "<=":
                flagged = rp
            else:
                flagged = None
            row[f"estimated_flagged_share_{corpus}"] = flagged
        threshold_rows.append(row)

threshold_fields = [
    "signature_id",
    "metric",
    "operator",
    "threshold",
]
for corpus in corpora:
    threshold_fields.append(f"threshold_percentile_{corpus}")
    threshold_fields.append(f"estimated_flagged_share_{corpus}")

with thresholds_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=threshold_fields)
    writer.writeheader()
    writer.writerows(threshold_rows)


def fmt(value):
    if value is None:
        return "n/a"
    return f"{value:.3f}"


lines = []
lines.append("TACO Signature Calibration Report")
lines.append(f"Source CSV: {csv_path}")
lines.append(f"Signatures: {signatures_path}")
lines.append("")
lines.append("Corpus row counts")
for corpus in corpora:
    lines.append(f"- {corpus}: {counts.get(corpus, 0)}")

lines.append("")
lines.append("Percentile distributions")
for corpus in corpora:
    lines.append("")
    lines.append(f"[{corpus}]")
    for metric in metrics:
        values = by_corpus[corpus][metric]
        lines.append(
            f"- {metric}: n={len(values)} "
            f"p10={fmt(percentile(values, 10))} "
            f"p25={fmt(percentile(values, 25))} "
            f"p50={fmt(percentile(values, 50))} "
            f"p75={fmt(percentile(values, 75))} "
            f"p90={fmt(percentile(values, 90))}"
        )

lines.append("")
lines.append("Current threshold positions")
for row in threshold_rows:
    parts = [
        f"- {row['signature_id']} :: {row['metric']} {row['operator']} {fmt(row['threshold'])}"
    ]
    for corpus in corpora:
        pct = row.get(f"threshold_percentile_{corpus}")
        flagged = row.get(f"estimated_flagged_share_{corpus}")
        parts.append(f"{corpus}:threshold@p{fmt(pct)},flags~{fmt(flagged)}%")
    lines.append(" | ".join(parts))

lines.append("")
lines.append("Anchor recommendations")
for metric, (corpus, pct, op) in anchors.items():
    values = by_corpus[corpus][metric]
    value = percentile(values, pct)
    lines.append(f"- {metric}: set {op} {fmt(value)} ({corpus} p{pct})")

report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
PY

echo
echo "Calibration artifacts:"
echo "  CSV rows: ${OUTPUT_CSV}"
echo "  Percentiles: ${PERCENTILES_CSV}"
echo "  Threshold positions: ${THRESHOLDS_CSV}"
echo "  Report: ${REPORT_PATH}"
