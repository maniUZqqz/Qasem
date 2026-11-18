#!/bin/bash
# emulate Celery beat on the stage: run apps.compute.tasks.maintenance() (autopilot tick, selftest advance, park wake) every few seconds
# usage: sim-tick.sh <rounds> <sleep seconds>
PY=/var/www/NM/upmarket/venv/bin/python
cd /root/stage/r4ready/backend
for i in $(seq 1 ${1:-6}); do
  $PY -X utf8 manage.py shell -c "
from apps.compute.tasks import maintenance
import json
print(json.dumps(maintenance(), ensure_ascii=False, default=str)[:600])
" 2>&1 | tail -2
  sleep ${2:-10}
done
