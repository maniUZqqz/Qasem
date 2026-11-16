#!/usr/bin/env bash
# NM: mirror of the whole ui-ux-pro-max-skill repository (MIT, Next Level Builder) on this server - idempotent; run again to update.
#   bash deploy/nm/uiux-mirror.sh
# The importer reads from the mirror:
#   cd backend && ../venv/bin/python -m apps.projects.builder.styles.import_uiux_full /opt/nm-mirror/ui-ux-pro-max-skill
# Licence: the repo's LICENSE (MIT) travels with the mirror and is copied next to the imported data (styles/dataset/LICENSE-ui-ux-pro-max-skill.txt).
set -euo pipefail
DEST="${NM_UIUX_MIRROR:-/opt/nm-mirror/ui-ux-pro-max-skill}"
URL="https://github.com/nextlevelbuilder/ui-ux-pro-max-skill"
mkdir -p "$(dirname "$DEST")"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch --depth 1 origin 2>&1 | tail -1 || true
  git -C "$DEST" reset --hard FETCH_HEAD 2>&1 | tail -1 || true
else
  git clone --depth 1 "$URL" "$DEST"
fi
test -f "$DEST/LICENSE" && head -3 "$DEST/LICENSE"
echo "mirror: $(git -C "$DEST" rev-parse HEAD) $(git -C "$DEST" log -1 --format=%cI)"
