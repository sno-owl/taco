#!/usr/bin/env python3
import json
import subprocess
import csv
from pathlib import Path
import statistics
import sys
import os

# Paths
ROOT = Path(__file__).parent.parent
ELLIPSE_DIR = ROOT / "ELLIPSE_Sample"
SPECS_DIR = Path("/Users/Taras.Shemchuk/repos/leaf/specs")
OUTPUT_CSV = ROOT / "dist" / "calibration.csv"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

# Metric keys to track
METRICS = [
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

def run_taco(file_path):
    try:
        # Use the venv python to ensure spacy and dependencies are found
        result = subprocess.run(
            [str(VENV_PYTHON), "-m", "taco_tool", "analyze", str(file_path), "--format", "json"],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        return data.get("metrics", {})
    except Exception as e:
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return None

def main():
    ROOT.joinpath("dist").mkdir(exist_ok=True)
    
    all_data = []
    
    # Process ELLIPSE samples (capped at 100 for speed if needed, but let's try all)
    ellipse_files = list(ELLIPSE_DIR.glob("*.txt"))
    print(f"Processing {len(ellipse_files)} ELLIPSE samples...")
    for i, f in enumerate(ellipse_files):
        if i % 50 == 0: print(f"  Progress: {i}/{len(ellipse_files)}")
        m = run_taco(f)
        if m:
            m["source"] = "ellipse"
            m["filename"] = f.name
            all_data.append(m)
            
    # Process specs
    spec_files = list(SPECS_DIR.glob("*.md"))
    print(f"Processing {len(spec_files)} spec files...")
    for f in spec_files:
        m = run_taco(f)
        if m:
            m["source"] = "spec"
            m["filename"] = f.name
            all_data.append(m)

    if not all_data:
        print("No data collected.")
        return

    # Write CSV
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "filename"] + METRICS)
        writer.writeheader()
        for row in all_data:
            # Filter keys to only what we want
            filtered = {k: v for k, v in row.items() if k in writer.fieldnames}
            writer.writerow(filtered)

    print(f"\nCalibration data saved to {OUTPUT_CSV}")

    # Compute Statistics for ELLIPSE (the "Good" baseline)
    ellipse_metrics = [d for d in all_data if d["source"] == "ellipse"]
    if not ellipse_metrics:
        return

    print("\n--- Percentile Distributions (ELLIPSE Corpus) ---")
    header = f"{'Metric':<40} | {'p10':>6} | {'p25':>6} | {'p50':>6} | {'p75':>6} | {'p90':>6}"
    print(header)
    print("-" * len(header))
    
    for m in METRICS:
        vals = sorted([d[m] for d in ellipse_metrics if m in d and d[m] is not None])
        if not vals: continue
        
        def pct(p):
            idx = int(len(vals) * p / 100)
            return vals[min(idx, len(vals)-1)]
            
        print(f"{m:<40} | {pct(10):>6.3f} | {pct(25):>6.3f} | {pct(50):>6.3f} | {pct(75):>6.3f} | {pct(90):>6.3f}")

if __name__ == "__main__":
    main()
