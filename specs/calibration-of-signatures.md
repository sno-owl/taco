# Signature Calibration and Expansion (2026-03-06)

## Context
Original cohesion signature thresholds were manually chosen and too aggressive/inert in key places:
- `jargon_spray` could trigger unexpectedly on reasonable writing.
- `semantic_veneer` and `floating_claims` had threshold combinations that were effectively dead or misaligned.

Goal: ground thresholds in empirical distributions from known-good text and extend signatures using rare-but-interpretable metric patterns.

## Data and Method
Corpora:
- Known-good: `ELLIPSE_Sample/*.txt` (520 essays)
- Specs corpus target: `leaf/specs/*.md` (not present in this checkout during calibration runs)

CLI profile:
- `taco analyze --profile signature --format json`

Implemented script:
- `scripts/calibrate_signatures.sh`

Outputs:
- `dist/calibration.csv`
- `dist/calibration_percentiles.csv`
- `dist/calibration_threshold_positions.csv`
- `dist/calibration_report.txt`

Script behavior:
1. Runs `taco analyze` per input file.
2. Extracts 9 key metrics into one CSV.
3. Computes p10/p25/p50/p75/p90 by corpus.
4. Reports where current thresholds sit in each distribution and estimated flagged share.
5. Prints anchor recommendations:
   - novelty metrics (`noun_ttr`, `content_ttr`) anchored to high tail
   - continuity/link metrics anchored to low tail
   - semantic-sheen metric (`word2vec_1_all_sent`) anchored to upper quartile

## Threshold Changes Applied
File:
- `taco_tool/signature_data/cohesion_signatures.json`

Calibrated values:
- `noun_ttr >= 0.643` (was `0.8`)
- `content_ttr >= 0.605` (was `0.8`)
- `adjacent_overlap_binary_noun_sent <= 0.222` (was `0.05` / `0.1`)
- `repeated_content_lemmas <= 0.275` (was `0.2` / `0.25`)
- `syn_overlap_sent_noun <= 0.306` (was `0.1`)
- `all_connective <= 0.057` (was `0.015`)
- `word2vec_1_all_sent >= 0.861` in semantic-veneer branch (was `0.7`)
- `word2vec_1_all_sent <= 0.748` in floating-claims branch (was `0.35`)

## New Signatures Added
All in `taco_tool/signature_data/cohesion_signatures.json`.

1. `logic_gap_low_link_low_entity_carry_v1` (high)
- `all_connective <= 0.057`
- `adjacent_overlap_binary_argument_sent <= 0.526`
- `lsa_1_all_sent <= 0.339`

2. `novelty_burst_without_logic_links_v1` (high)
- `noun_ttr >= 0.643`
- `content_ttr >= 0.605`
- `all_connective <= 0.057`

3. `lexical_orphan_chain_v1` (medium)
- `adjacent_overlap_binary_noun_sent <= 0.222`
- `repeated_content_lemmas <= 0.275`
- `adjacent_overlap_binary_argument_sent <= 0.526`

## Semantic Veneer Recalibration
`semantic_veneer_no_lexical_thread_v1` was initially 0-hit on ELLIPSE after first calibration pass.

Adjusted lexical-thread cutoffs to keep the "high semantic smoothness + weak lexical continuity" intent while making the signature active:
- `word2vec_1_all_sent >= 0.861` (kept)
- `noun_ttr >= 0.49`
- `adjacent_overlap_binary_noun_sent <= 0.5`
- `repeated_content_lemmas <= 0.343`

## Observed ELLIPSE Base Rates (520 essays)
Post-change signature match rates on `dist/ellipse_signature_batch.csv`:
- `jargon_spray_sparse_local_cohesion_v1`: `10/520` (1.92%)
- `floating_claims_low_logic_links_v1`: `3/520` (0.58%)
- `semantic_veneer_no_lexical_thread_v1`: `4/520` (0.77%)
- `logic_gap_low_link_low_entity_carry_v1`: `2/520` (0.38%)
- `novelty_burst_without_logic_links_v1`: `2/520` (0.38%)
- `lexical_orphan_chain_v1`: `5/520` (0.96%)

## Quick Verification Run
Commands executed:
- `./.venv/bin/taco lint ELLIPSE_Sample/0000C359D63E.txt` -> pass (`exit 0`)
- `./.venv/bin/taco lint /tmp/taco_jargon.md` -> suspect (`exit 2`)

Jargon sample matched multiple high-signal signatures, while a known-good ELLIPSE sample passed.

## Known Gaps
- `leaf/specs/*.md` did not exist in this checkout, so calibration/verification could not include real spec docs yet.
- Once specs are present, rerun `scripts/calibrate_signatures.sh` and recheck threshold positions against both corpora before final lock.

## Re-run Instructions
From repo root:

```bash
./scripts/calibrate_signatures.sh
```

Optional controls:

```bash
MAX_FILES_PER_CORPUS=50 ./scripts/calibrate_signatures.sh
TACO_BIN=./.venv/bin/taco ./scripts/calibrate_signatures.sh
SPECS_GLOB='specs/*.md' ./scripts/calibrate_signatures.sh
```
