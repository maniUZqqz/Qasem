#!/bin/bash
PY=/var/www/NM/upmarket/venv/bin/python
cd /root/stage/r4ready/backend
$PY -X utf8 manage.py shell -c "
from apps.compute.models import ComputeNode, ComputeJob
from apps.compute.models_platform import SelfTestRun, SelfTestResult
for n in ComputeNode.objects.filter(name__startswith='SIM-'):
    c = n.capabilities or {}
    print(n.pk, n.name, 'online', n.online, 'agent', c.get('agent'), 'kinds', len(c.get('kinds') or []), 'bootstrap', (c.get('bootstrap') or {}).get('summary'))
for r in SelfTestRun.objects.filter(node__name__startswith='SIM-').order_by('-id')[:3]:
    from collections import Counter
    print('run', r.pk, r.node.name, r.state, r.trigger, r.agent_version, dict(Counter(r.results.values_list('state', flat=True))))
" 2>&1 | tail -12
