#!/usr/bin/env bash
set -euo pipefail

if ! command -v taco >/dev/null 2>&1; then
  echo "taco binary not found. Install it first (e.g., scripts/build_install_homebrew.sh)." >&2
  exit 1
fi

status=0

for file in "$@"; do
  if [[ ! -f "$file" ]]; then
    continue
  fi
  if [[ "${file##*.}" != "md" ]]; then
    continue
  fi

  echo "[taco] linting ${file}"
  if ! taco lint "$file"; then
    status=1
  fi
done

exit "$status"
