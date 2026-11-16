#!/usr/bin/env bash
# NM: install (or refresh) the component-converter toolchain in /opt/nm-c21 - idempotent, outside the panel's node_modules.
#   bash deploy/c21/install.sh            (run from the repo root or anywhere)
# Needs Node 20+ and the npm registry (reachable from Iran). Re-running only reinstalls npm packages when package.json changed.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${NM_C21_TOOLCHAIN:-/opt/nm-c21}"
mkdir -p "$DEST"
for f in convert.mjs shims.mjs extras.css rtl_check.py package.json; do
  install -m 0644 "$SRC/$f" "$DEST/$f"
done
cd "$DEST"
want="$(sha256sum package.json | cut -d' ' -f1)"
have="$(cat .pkg.sha 2>/dev/null || true)"
if [ ! -d node_modules/esbuild ] || [ "$want" != "$have" ]; then
  echo "npm install ..."
  flock -w 3600 /root/nm-heavy.lock npm install --no-audit --no-fund 2>&1 | tail -3 || npm install --no-audit --no-fund 2>&1 | tail -3
  echo "$want" > .pkg.sha
fi
# smoke test: a one-line component must convert
cat > /tmp/nm-c21-smoke.json <<'EOF'
{"id":"smoke/x","scope":"nbc21-smoke","entry":{"path":"d.tsx","code":"export default function D(){ return <div className=\"ml-4 text-left p-2 font-bold\">hi</div>; }"},"files":{},"roots":[],"export":"auto"}
EOF
node convert.mjs /tmp/nm-c21-smoke.json /tmp/nm-c21-smoke.out.json
python3 - <<'EOF'
import json
d = json.load(open('/tmp/nm-c21-smoke.out.json'))
assert d.get('ok'), d
assert 'margin-inline-start' in d['css'], 'RTL conversion missing'
print('nm-c21 toolchain ok: html=%d css=%d' % (len(d['html']), len(d['css'])))
EOF
rm -f /tmp/nm-c21-smoke.json /tmp/nm-c21-smoke.out.json
