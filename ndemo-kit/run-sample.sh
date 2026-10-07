#!/usr/bin/env bash
# Render (or rehearse) the bundled sample demo.
#   ./run-sample.sh              narrated mp4 (needs OPENAI_API_KEY)
#   ./run-sample.sh --silent     mp4 without narration (no key, no cost)
#   ./run-sample.sh --live       play it in a visible browser, no recording
#   ./run-sample.sh --live --audio   same, with narration through your speakers
# Options: --port N (default 4180), --open (open the mp4 when done)
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NDEMO="$KIT_DIR/ndemo/ndemo"
SRC_PLAYBOOK="$KIT_DIR/sample/demo/sample-tour/sample-tour.yaml"

mode=narrated; live=0; audio=0; open_after=0; port=4180
while [ $# -gt 0 ]; do
  case "$1" in
    --silent) mode=silent ;;
    --live)   live=1 ;;
    --audio)  audio=1 ;;
    --open)   open_after=1 ;;
    --port)   port="$2"; shift ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

[ -f "$KIT_DIR/ndemo/dist/cli.js" ] || { echo "ndemo is not built yet. Run ./setup.sh first." >&2; exit 1; }

needs_key=0
if [ "$live" = 1 ]; then [ "$audio" = 1 ] && needs_key=1
elif [ "$mode" = narrated ]; then needs_key=1; fi
if [ "$needs_key" = 1 ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY is not set (needed for narration)." >&2
  echo "Either: echo 'export OPENAI_API_KEY=sk-...' >> ~/.zshrc && source ~/.zshrc" >&2
  echo "Or run without narration: ./run-sample.sh --silent" >&2
  exit 1
fi

# ─── Serve the sample app ───────────────────────────────────────────
if curl -s -o /dev/null "http://127.0.0.1:$port/"; then
  echo "Port $port is already in use. Pick another: ./run-sample.sh --port 4181" >&2
  exit 1
fi
node "$KIT_DIR/sample/serve.mjs" "$KIT_DIR/sample/app" "$port" >/dev/null &
server_pid=$!
cleanup() {
  if [ "$live" = 1 ]; then (cd "$KIT_DIR" && "$NDEMO" close >/dev/null 2>&1) || true; fi
  kill "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT
for _ in $(seq 1 50); do
  curl -s -o /dev/null "http://127.0.0.1:$port/" && break
  sleep 0.1
done
curl -s -o /dev/null "http://127.0.0.1:$port/" || { echo "Sample server failed to start" >&2; exit 1; }

# ─── Prepare a working copy of the playbook ─────────────────────────
# ndemo render rewrites the playbook it renders, and caches TTS audio next to
# it (keyed by narration+voice+speed), so re-runs don't re-bill OpenAI.
work_dir="$KIT_DIR/out/$mode"
playbook="$work_dir/sample-tour.yaml"
prep_flags=(); [ "$mode" = silent ] && prep_flags+=(--silent)
node "$KIT_DIR/tools/prepare-playbook.mjs" "$KIT_DIR/ndemo" "$SRC_PLAYBOOK" "$playbook" "$port" ${prep_flags[@]+"${prep_flags[@]}"}

cd "$KIT_DIR"   # ndemo keeps its browser state in ./.ndemo and runs setup steps from cwd

if [ "$live" = 1 ]; then
  "$NDEMO" open "$playbook"
  play_flags=(); [ "$audio" = 1 ] && play_flags+=(--audio)
  "$NDEMO" play "$playbook" ${play_flags[@]+"${play_flags[@]}"}
  read -r -p "Done. Press Enter to close the browser... " _ || true
  exit 0
fi

output="$KIT_DIR/out/sample-tour-$mode.mp4"
"$NDEMO" render "$playbook" --output "$output"

if [ "$open_after" = 1 ]; then
  if command -v open >/dev/null; then open "$output"; elif command -v xdg-open >/dev/null; then xdg-open "$output"; fi
fi
