#!/usr/bin/env bash
# One-shot installer for the ndemo demo-recording kit.
#   ./setup.sh             install everything (idempotent; safe to re-run)
# Env overrides:
#   NDEMO_REF=<git ref>    ndemo commit/branch to install (default: pinned, tested commit)
#   NDEMO_NO_SKILL_LINK=1  don't link ndemo into ~/.claude/skills
#   NDEMO_SKIP_BROWSER=1   skip `playwright install chromium`
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NDEMO_DIR="$KIT_DIR/ndemo"
NDEMO_REPO="https://github.com/splitbrain/ndemo"
# Pinned to the commit this kit was tested against. ndemo has no releases yet,
# so tracking main could break the sample without warning.
NDEMO_REF="${NDEMO_REF:-d60e17e84b524dc89e8145844a030c47f4b9537d}"
SKILL_LINK="$HOME/.claude/skills/ndemo"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[31mError:\033[0m %s\n' "$*" >&2; exit 1; }

OS="$(uname -s)"

# ─── 1. System dependencies ───────────────────────────────────────────
say "Checking system dependencies"

node_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }

need_node=0; need_ffmpeg=0
command -v node >/dev/null && [ "$(node_major)" -ge 20 ] || need_node=1
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || need_ffmpeg=1

if [ "$need_node$need_ffmpeg" != "00" ]; then
  if [ "$OS" = "Darwin" ]; then
    command -v brew >/dev/null || die "Homebrew not found. Install it from https://brew.sh, then re-run ./setup.sh"
    [ "$need_node" = 1 ]   && { say "Installing Node.js (brew)"; brew install node; }
    [ "$need_ffmpeg" = 1 ] && { say "Installing ffmpeg (brew)"; brew install ffmpeg; }
  else
    [ "$need_node" = 1 ]   && warn "Node.js >= 20 is required (e.g. via nvm or your package manager)"
    [ "$need_ffmpeg" = 1 ] && warn "ffmpeg is required (e.g. sudo apt-get install ffmpeg)"
    die "Install the missing tools above, then re-run ./setup.sh"
  fi
fi
ok "node $(node -v)"
ok "$(ffmpeg -hide_banner -version 2>/dev/null | sed -n '1s/^\(ffmpeg version [^ ]*\).*/\1/p')"

# ndemo encodes with libx264 + aac; some minimal ffmpeg builds lack libx264.
encoders="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
grep -q libx264 <<<"$encoders" || die "ffmpeg has no libx264 encoder. On macOS: brew reinstall ffmpeg"
grep -qE ' aac ' <<<"$encoders"  || die "ffmpeg has no aac encoder"
ok "ffmpeg encoders: libx264, aac"
command -v ffplay >/dev/null && ok "ffplay (for 'play --audio' rehearsals)" \
  || warn "ffplay missing: only needed for 'ndemo play --audio' live rehearsals"
command -v git >/dev/null || die "git is required"

# ─── 2. ndemo source ─────────────────────────────────────────────────
say "Fetching ndemo ($NDEMO_REF)"
if [ ! -d "$NDEMO_DIR/.git" ]; then
  git clone --quiet "$NDEMO_REPO" "$NDEMO_DIR"
fi
git -C "$NDEMO_DIR" fetch --quiet origin
git -C "$NDEMO_DIR" -c advice.detachedHead=false checkout --quiet "$NDEMO_REF"
ok "ndemo at $(git -C "$NDEMO_DIR" rev-parse --short HEAD)"

# ─── 3. Build ────────────────────────────────────────────────────────
say "Installing npm packages and building"
(cd "$NDEMO_DIR" && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent)
ok "built $NDEMO_DIR/dist/cli.js"

if [ "${NDEMO_SKIP_BROWSER:-0}" != 1 ]; then
  say "Installing Playwright Chromium (matches ndemo's Playwright version)"
  (cd "$NDEMO_DIR" && npx --no-install playwright install chromium)
fi

# ─── 4. Claude Code skill link ───────────────────────────────────────
# Lets you say "make a narrated demo of http://localhost:3000" in Claude Code
# from any project. Skipped if something else already lives at that path.
if [ "${NDEMO_NO_SKILL_LINK:-0}" != 1 ]; then
  say "Linking Claude Code skill"
  mkdir -p "$(dirname "$SKILL_LINK")"
  if [ -L "$SKILL_LINK" ] && [ "$(readlink "$SKILL_LINK")" = "$NDEMO_DIR" ]; then
    ok "$SKILL_LINK already linked"
  elif [ -e "$SKILL_LINK" ] || [ -L "$SKILL_LINK" ]; then
    warn "$SKILL_LINK exists and points elsewhere; left untouched"
  else
    ln -s "$NDEMO_DIR" "$SKILL_LINK"
    ok "$SKILL_LINK -> $NDEMO_DIR"
  fi
fi

# ─── 5. Doctor ───────────────────────────────────────────────────────
say "ndemo doctor"
# doctor exits non-zero when OPENAI_API_KEY is unset; that's expected before
# you add the key, and silent renders don't need it.
"$NDEMO_DIR/ndemo" doctor || true

echo
say "Done. Next:"
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "  1. Add your key (narrated renders only):"
  echo "       echo 'export OPENAI_API_KEY=sk-...' >> ~/.zshrc && source ~/.zshrc"
fi
echo "  •  ./run-sample.sh --silent     # no key needed: proves the pipeline"
echo "  •  ./run-sample.sh              # narrated version (OpenAI TTS)"
