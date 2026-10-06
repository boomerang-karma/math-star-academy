#!/usr/bin/env bash
# Build the single Lambda bundle (arm64, Python 3.12) used by every function.
#
#   scripts/build/lambda_bundle.sh            -> build/lambda/
#
# Dependencies are resolved from uv.lock (exactly what the tests ran against) and
# installed as manylinux_2_28 aarch64 wheels (Lambda python3.12 = Amazon Linux 2023,
# glibc 2.34), so the bundle is reproducible on any OS
# without Docker. The ICP profile is copied to config/icp.json (LEADINTEL_ICP_PATH).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/build/lambda"
REQS="$ROOT/build/requirements-lambda.txt"

command -v uv >/dev/null 2>&1 || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT/config"

# Runtime dependencies only (no dev/infra groups), plus the Bedrock extra for AI briefs.
uv export --project "$ROOT" --frozen --no-dev --no-emit-project --extra ai \
  --format requirements-txt --output-file "$REQS" >/dev/null

uv pip install \
  --requirement "$REQS" \
  --target "$OUT" \
  --python-platform aarch64-manylinux_2_28 \
  --python-version 3.12 \
  --only-binary :all: \
  --no-compile \
  --quiet

cp -R "$ROOT/src/leadintel" "$OUT/leadintel"
cp -R "$ROOT/database" "$OUT/database"          # migrations + seeds for the migrator Lambda
cp "$ROOT/config/icp.json" "$OUT/config/icp.json"

find "$OUT" -type d -name "__pycache__" -prune -exec rm -rf {} +

SIZE="$(du -sh "$OUT" | cut -f1)"
echo "Lambda bundle ready: $OUT ($SIZE)"
