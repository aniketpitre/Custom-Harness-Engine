#!/bin/sh
# One-command installer for Harness Engine.
#   curl -fsSL https://raw.githubusercontent.com/aniketpitre/Custom-Harness-Engine/main/install.sh | sh
# Installs the `harness` command in an isolated environment (uv, else pipx, else a private venv).
# Override the source with HARNESS_SOURCE (a PyPI name, wheel, archive/git URL, or local path). HARNESS_EXTRAS picks extras.
set -eu

# Default: the GitHub source archive (no git needed). Until a PyPI release exists this is the way to install.
SOURCE="${HARNESS_SOURCE:-https://github.com/aniketpitre/Custom-Harness-Engine/archive/refs/heads/main.tar.gz}"
EXTRAS="${HARNESS_EXTRAS-runtime}"
if [ -n "$EXTRAS" ]; then BRACKET="[$EXTRAS]"; else BRACKET=""; fi
case "$SOURCE" in
  git+*|http*) SPEC="harness-engine$BRACKET @ $SOURCE" ;;
  /*|./*)      SPEC="harness-engine$BRACKET @ file://$(cd "$SOURCE" && pwd)" ;;
  *.whl)       SPEC="$SOURCE" ;;
  *)           SPEC="$SOURCE$BRACKET" ;;
esac

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if have "$candidate" && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$candidate"; break
  fi
done

if have uv; then
  CMD="uv tool install --force --python ${PYTHON:-3.12} \"$SPEC\""
elif have pipx && [ -n "$PYTHON" ]; then
  CMD="pipx install --force --python $PYTHON \"$SPEC\""
elif [ -n "$PYTHON" ]; then
  VENV="${HARNESS_VENV:-$HOME/.harness/venv}"
  CMD="$PYTHON -m venv \"$VENV\" && \"$VENV/bin/pip\" install --upgrade pip && \"$VENV/bin/pip\" install \"$SPEC\" && mkdir -p \"$HOME/.local/bin\" && ln -sf \"$VENV/bin/harness\" \"$HOME/.local/bin/harness\""
else
  say "Harness Engine needs Python 3.11+ (or 'uv', which can fetch one)."
  say "Install uv:  curl -LsSf https://astral.sh/uv/install.sh | sh   then re-run this script."
  exit 1
fi

if [ "${HARNESS_INSTALL_DRY_RUN:-0}" = "1" ]; then
  say "$CMD"
  exit 0
fi

say "Installing Harness Engine ($SPEC)..."
sh -c "$CMD"

say ""
say "Installed. Next steps:"
say "  harness init      # model, API key, API token (about a minute)"
say "  harness doctor    # verify everything"
say "  harness serve     # start the API on 127.0.0.1:8000"
if ! have harness; then
  say ""
  say "Note: 'harness' is not on your PATH yet. Add \$HOME/.local/bin to PATH (uv/pipx: run 'uv tool update-shell' or 'pipx ensurepath')."
fi
