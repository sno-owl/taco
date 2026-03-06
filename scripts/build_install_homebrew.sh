#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist/homebrew"
BUILD_DIR="${ROOT_DIR}/dist/build"
STAGE_DIR="${BUILD_DIR}/homebrew-stage"
TEST_VENV="${ROOT_DIR}/.venv-test"
PYTHON_BIN="${TACO_BUILD_PYTHON_BIN:-python3.12}"

FORMULA_NAME="${TACO_HOMEBREW_FORMULA_NAME:-taco}"
TAP_NAME="${TACO_HOMEBREW_TAP_NAME:-local/taco}"

if ! command -v brew >/dev/null 2>&1; then
  echo "brew is required for install-plane automation." >&2
  exit 1
fi

if [[ ! "${TAP_NAME}" =~ ^[^/]+/[^/]+$ ]]; then
  echo "TACO_HOMEBREW_TAP_NAME must be user/repo (got ${TAP_NAME})" >&2
  exit 1
fi

if ! brew tap | rg -qx "${TAP_NAME}"; then
  brew tap-new --no-git "${TAP_NAME}"
fi

tap_user="${TAP_NAME%%/*}"
tap_repo="${TAP_NAME##*/}"
TAP_DIR="$(brew --repository)/Library/Taps/${tap_user}/homebrew-${tap_repo}"
FORMULA_PATH="${TAP_DIR}/Formula/${FORMULA_NAME}.rb"
FORMULA_REF="${TAP_NAME}/${FORMULA_NAME}"

mkdir -p "${DIST_DIR}" "${BUILD_DIR}" "$(dirname "${FORMULA_PATH}")"

cd "${ROOT_DIR}"

VERSION="${TACO_BUILD_VERSION:-$(git describe --tags --always --dirty)}"
dirty_suffix=""
if [[ -n "$(git status --porcelain)" ]]; then
  dirty_suffix="-dirty"
fi
COMMIT="${TACO_BUILD_COMMIT:-$(git rev-parse --short=12 HEAD)${dirty_suffix}}"
BUILT_AT="${TACO_BUILD_AT:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"

echo "[1/7] Run tests (if present)"
TEST_FILES="$(fd -E .venv -E .venv-build -E .venv-test -E dist -E build -E 'old code versions' -t f '(^test_.*\\.py$|.*_test\\.py$)' "${ROOT_DIR}" || true)"
if [[ -n "${TEST_FILES}" ]]; then
  rm -rf "${TEST_VENV}"
  "${PYTHON_BIN}" -m venv "${TEST_VENV}"
  # shellcheck disable=SC1090
  source "${TEST_VENV}/bin/activate"
  python -m pip install --upgrade pip
  pip install -e "${ROOT_DIR}" pytest
  pytest -q
else
  echo "No test files found. Skipping pytest."
fi

echo "[2/7] Build taco binary (PyInstaller --onedir)"
TACO_BUILD_VERSION="${VERSION}" TACO_BUILD_COMMIT="${COMMIT}" TACO_BUILD_AT="${BUILT_AT}" \
  ./scripts/build_binary_pyinstaller.sh

echo "[3/7] Stage payload"
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}/bin" "${STAGE_DIR}/share/taco" "${STAGE_DIR}/libexec/taco"
# PyInstaller --onedir output is at dist/build/taco/
cp -a "${BUILD_DIR}/taco/." "${STAGE_DIR}/libexec/taco/"
# Create a wrapper script that execs the real binary so Homebrew can symlink into bin/
cat > "${STAGE_DIR}/bin/taco" <<'WRAPPER'
#!/usr/bin/env bash
exec "$(dirname "$0")/../libexec/taco/taco" "$@"
WRAPPER
chmod +x "${STAGE_DIR}/bin/taco"

cp "${ROOT_DIR}/TAACOnoGUI.py" "${STAGE_DIR}/share/taco/"
cp "${ROOT_DIR}/adj_lem_list.txt" "${STAGE_DIR}/share/taco/"
cp "${ROOT_DIR}/wn_noun_2.txt" "${STAGE_DIR}/share/taco/"
cp "${ROOT_DIR}/wn_verb_2.txt" "${STAGE_DIR}/share/taco/"
cp ${ROOT_DIR}/COCA_newspaper_magazine_export_*.csv "${STAGE_DIR}/share/taco/"
cp ${ROOT_DIR}/mag_news_*.csv "${STAGE_DIR}/share/taco/"
ARCHIVE_NAME="taco-${VERSION}.tar.gz"
ARCHIVE_PATH="${DIST_DIR}/${ARCHIVE_NAME}"
CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"
MANIFEST_PATH="${DIST_DIR}/build-manifest.json"

echo "[4/7] Package archive and checksum"
tar -C "${STAGE_DIR}" -czf "${ARCHIVE_PATH}" .
ARCHIVE_SHA="$(shasum -a 256 "${ARCHIVE_PATH}" | cut -d ' ' -f1)"
printf '%s  %s\n' "${ARCHIVE_SHA}" "${ARCHIVE_NAME}" > "${CHECKSUM_PATH}"

cat > "${MANIFEST_PATH}" <<EOF
{
  "version": "${VERSION}",
  "commit": "${COMMIT}",
  "built_at": "${BUILT_AT}",
  "archive": "${ARCHIVE_PATH}",
  "archive_sha256": "${ARCHIVE_SHA}",
  "formula": "${FORMULA_REF}"
}
EOF

echo "[5/7] Update local tap formula"
cat > "${FORMULA_PATH}" <<EOF
class Taco < Formula
  desc "TAACO-powered markdown cohesion lint CLI"
  homepage "https://github.com/sno-owl/taco"
  url "file://${ARCHIVE_PATH}"
  version "${VERSION}"
  sha256 "${ARCHIVE_SHA}"

  def install
    libexec.install Dir["libexec/taco/*"]
    bin.write_exec_script libexec/"taco"
    (prefix/"share/taco").install Dir["share/taco/*"]
  end

  test do
    version_out = shell_output("#{bin}/taco --version")
    assert_match "taco", version_out

    sig_out = shell_output("#{bin}/taco signatures")
    assert_match "jargon_spray_sparse_local_cohesion_v1", sig_out

    doctor_out = shell_output("#{bin}/taco doctor --data-dir #{prefix}/share/taco --format json")
    assert_match "\"ok\": true", doctor_out
  end
end
EOF

echo "[6/7] Install/upgrade via Homebrew"
if brew list --formula "${FORMULA_REF}" >/dev/null 2>&1; then
  brew reinstall --formula "${FORMULA_REF}"
else
  brew install --formula "${FORMULA_REF}"
fi

echo "[7/7] Smoke check"
TMP_MD="$(mktemp /tmp/taco-smoke-XXXXXX.md)"
cat > "${TMP_MD}" <<'MD'
This specification defines a stable audit ledger.
Therefore each write references a prior state hash.
MD

if ! taco analyze "${TMP_MD}" --profile focused --data-dir "$(brew --prefix "${FORMULA_REF}")/share/taco" >/dev/null; then
  echo "Smoke test failed" >&2
  rm -f "${TMP_MD}"
  exit 1
fi

rm -f "${TMP_MD}"

echo "Install plane completed successfully."
echo "Version: ${VERSION}"
echo "Commit: ${COMMIT}"
echo "Formula: ${FORMULA_PATH}"
echo "Formula ref: ${FORMULA_REF}"
echo "Manifest: ${MANIFEST_PATH}"
