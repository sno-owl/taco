#!/usr/bin/env bash
set -euo pipefail

if ! command -v taco >/dev/null 2>&1; then
  echo "taco is not installed on PATH" >&2
  exit 1
fi

taco --version

tmp_md="$(mktemp /tmp/taco-verify-XXXXXX.md)"
cat > "${tmp_md}" <<'MD'
A coherent document repeats key entities and links claims explicitly.
Therefore a verifier should track overlap and connective usage.
MD

taco lint "${tmp_md}" >/dev/null
rm -f "${tmp_md}"

echo "verify_install_plane: ok"
