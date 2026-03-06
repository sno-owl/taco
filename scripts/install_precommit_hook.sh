#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRECOMMIT_CONFIG="${ROOT_DIR}/.pre-commit-config.yaml"

if ! command -v pre-commit >/dev/null 2>&1; then
  echo "pre-commit is required. Install with: pipx install pre-commit" >&2
  exit 1
fi

if [[ ! -f "${PRECOMMIT_CONFIG}" ]]; then
  cat > "${PRECOMMIT_CONFIG}" <<'YAML'
repos:
  - repo: local
    hooks:
      - id: taco-cohesion
        name: taco cohesion lint
        entry: scripts/lint_markdown_taco.sh
        language: system
        files: ^specs/.*\.md$
YAML
elif ! rg -q "id:\s*taco-cohesion" "${PRECOMMIT_CONFIG}"; then
  cat >> "${PRECOMMIT_CONFIG}" <<'YAML'

  - repo: local
    hooks:
      - id: taco-cohesion
        name: taco cohesion lint
        entry: scripts/lint_markdown_taco.sh
        language: system
        files: ^specs/.*\.md$
YAML
fi

cd "${ROOT_DIR}"
pre-commit install

echo "Installed pre-commit hook: taco-cohesion"
