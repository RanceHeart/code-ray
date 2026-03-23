#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE=""
COPY_SKILL=0

usage() {
  cat <<'EOF'
Install code-ray and optionally copy the repo-context skill into an OpenClaw workspace.

Usage:
  bash scripts/install.sh [--workspace PATH] [--with-skill]

Examples:
  bash scripts/install.sh
  bash scripts/install.sh --workspace ~/.openclaw/workspace-opus46 --with-skill
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      WORKSPACE="$2"
      shift 2
      ;;
    --with-skill)
      COPY_SKILL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if command -v uv >/dev/null 2>&1; then
  echo ">>> Installing code-ray with uv"
  uv tool install --force "$ROOT"
elif command -v pipx >/dev/null 2>&1; then
  echo ">>> Installing code-ray with pipx"
  pipx install --force "$ROOT"
else
  echo ">>> Installing code-ray with pip"
  python3 -m pip install --user --upgrade "$ROOT"
fi

if [[ "$COPY_SKILL" == "1" ]]; then
  if [[ -z "$WORKSPACE" ]]; then
    echo "--with-skill requires --workspace PATH" >&2
    exit 1
  fi
  mkdir -p "$WORKSPACE/skills/repo-context"
  cp "$ROOT/skills/repo-context/SKILL.md" "$WORKSPACE/skills/repo-context/SKILL.md"
  echo ">>> Copied skill to $WORKSPACE/skills/repo-context/SKILL.md"
fi

echo ">>> Done"
if command -v coderay >/dev/null 2>&1; then
  echo ">>> coderay is available at: $(command -v coderay)"
else
  echo ">>> coderay install finished, but your shell PATH may need refresh"
fi
