#!/usr/bin/env bash
set -Eeuo pipefail

ARCH_DOC_PATH="docs/ARCHITECTURE.md"

# Keep this list aligned with docs/ARCHITECTURE.md section 16.
RELEVANT_PATH_REGEX='^(app/|core/|plugins/|themes/|config/|clawgotchi/|main\.py$|install\.sh$|update\.sh$)'

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

staged_files="$(git diff --cached --name-only --diff-filter=ACMRTD)"
if [[ -z "${staged_files}" ]]; then
  exit 0
fi

if ! printf '%s\n' "${staged_files}" | grep -Eq "${RELEVANT_PATH_REGEX}"; then
  exit 0
fi

if printf '%s\n' "${staged_files}" | grep -Fxq "${ARCH_DOC_PATH}"; then
  exit 0
fi

cat >&2 <<'EOF'
[arch-doc-check] Architecture-relevant files are staged, but docs/ARCHITECTURE.md is not.

Please update and stage docs/ARCHITECTURE.md in the same commit.
If no architecture behavior changed, add a short note in section 16 explaining why.
EOF

exit 1
