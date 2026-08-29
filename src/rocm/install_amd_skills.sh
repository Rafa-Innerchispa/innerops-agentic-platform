#!/usr/bin/env bash
# Install official AMD Agent Skills for Cursor + Codex (InnerOS AMD .5).
set -euo pipefail

CANARY_DIR="${ROCM_CANARY_DIR:-/home/rlopez/data/rocm10-canary}"
CLONE="${CANARY_DIR}/amd-skills-src"
CURSOR_SKILLS="${HOME}/.cursor/skills"
CODEX_SKILLS="${HOME}/.agents/skills"

mkdir -p "$CURSOR_SKILLS" "$CODEX_SKILLS" "$CANARY_DIR/skills"

echo "=== install_amd_skills $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

if [[ ! -d "$CLONE/.git" ]]; then
  git clone --depth 1 https://github.com/amd/skills.git "$CLONE"
fi
git -C "$CLONE" fetch origin pull/87/head:pr-87-rocm-doctor 2>/dev/null || true
git -C "$CLONE" checkout pr-87-rocm-doctor 2>/dev/null || git -C "$CLONE" fetch origin pull/87/head:pr-87-rocm-doctor && git -C "$CLONE" checkout pr-87-rocm-doctor

SRC="$CLONE/staging/rocm-doctor"
if [[ ! -f "$SRC/SKILL.md" ]]; then
  echo "FAIL: staging/rocm-doctor missing in amd/skills PR #87" >&2
  exit 1
fi

rm -rf "$CURSOR_SKILLS/rocm-doctor" "$CODEX_SKILLS/rocm-doctor"
cp -a "$SRC" "$CURSOR_SKILLS/rocm-doctor"
cp -a "$SRC" "$CODEX_SKILLS/rocm-doctor"
rm -f "$CANARY_DIR/skills/"*.json "$CANARY_DIR/skills/skills_active.txt" 2>/dev/null || true

cat >"$CANARY_DIR/skills/INSTALLED.md" <<EOF
# AMD Skills installed $(date -u +%Y-%m-%dT%H:%M:%SZ)

| Skill | Cursor | Codex |
|-------|--------|-------|
| rocm-doctor | $CURSOR_SKILLS/rocm-doctor | $CODEX_SKILLS/rocm-doctor |

Source: https://github.com/amd/skills staging/rocm-doctor (PR #87; not on main yet).

Install CLI: \`curl -fsSL https://raw.githubusercontent.com/ROCm/rocm-cli/main/install.sh | sh -s -- nightly\`
EOF

echo "PASS: rocm-doctor -> $CURSOR_SKILLS/rocm-doctor and $CODEX_SKILLS/rocm-doctor"

if ! command -v rocm >/dev/null 2>&1; then
  echo "INFO: installing rocm CLI nightly to ~/.local/bin"
  curl -fsSL https://raw.githubusercontent.com/ROCm/rocm-cli/main/install.sh | sh -s -- nightly
fi
export PATH="${HOME}/.local/bin:${PATH}"
rocm --version || echo "WARN: rocm CLI not on PATH yet — add ~/.local/bin"
