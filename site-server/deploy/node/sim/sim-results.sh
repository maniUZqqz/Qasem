#!/bin/bash
PY=/var/www/NM/upmarket/venv/bin/python
cd /root/stage/r4ready/backend
$PY -X utf8 manage.py shell -c "
from apps.compute.models_platform import SelfTestRun
r = SelfTestRun.objects.filter(node__name='${1:-SIM-OLD-210}').order_by('-id').first()
print('run', r.pk, r.state, r.agent_version)
for x in r.results.order_by('key'):
    print('%-26s %-8s %s' % (x.key, x.state, (x.detail or '')[:130].replace(chr(10),' ')))
" 2>&1 | grep -v imported
