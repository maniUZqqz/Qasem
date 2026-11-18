#!/bin/bash
# Final simulation of "tonight" on the PATCHED stage (r4ready): stage server + 2.10 node + fake Ollama -> update -> self-tests -> queued AI -> cheap jobs.
# Runs detached; progress lines go to /root/stage/r4ready-sim-final.log, the last line is DONE or FAILED.
S=/root/stage/r4ready; SIM=/root/stage/r4ready-sim
PY=/var/www/NM/upmarket/venv/bin/python
LOG=/root/stage/r4ready-sim-final.log
exec >> $LOG 2>&1
say() { echo "[$(date +%T)] $*"; }
fail() { say "FAILED: $*"; echo FAILED; exit 1; }
: > $LOG
say "=== 0. clean start"
for f in old-loop.pid; do [ -f $SIM/$f ] && kill $(cat $SIM/$f) 2>/dev/null; done
pkill -f "sim_run.py" 2>/dev/null
for p in $(ps -eo pid,cmd | grep -E "r4ready-sim/(old|mnt)|fake_ollama.py 11555" | grep -v grep | awk '{print $1}'); do kill $p 2>/dev/null; done
sleep 2
python3 -c "import shutil; [shutil.rmtree('$SIM/'+d, ignore_errors=True) for d in ('old','mnt/data-old','mnt/data-new')]"
mkdir -p $SIM/mnt/data-old
mountpoint -q $SIM/mnt || fail "the capped data disk is not mounted"
df -h $SIM/mnt | tail -1

say "=== 1. fresh stage DB snapshot + stage server (no live lock fd, no live Redis)"
[ -f $SIM/api.pid ] && kill $(cat $SIM/api.pid) 2>/dev/null
sleep 1
python3 - <<'PYEOF'
import sqlite3
s = sqlite3.connect("file:/var/www/NM/upmarket/data/db.sqlite3?mode=ro", uri=True)
d = sqlite3.connect("/root/stage/r4ready/data/db.sqlite3")
s.backup(d); d.close(); s.close()
print("snapshot ok")
PYEOF
cd $S/backend
$PY -X utf8 manage.py migrate --noinput 2>&1 | tail -1
rm -rf $S/data/ai-deferred $S/data/node-commands
# the stage must never reach Metis from here: the deferred-AI demo is about "node off AND Metis unusable"
export AI_API_KEY="" AI_API_BASE_URL=""
(setsid nohup nice -n 5 $PY manage.py runserver 127.0.0.1:18177 --noreload > $SIM/runserver.log 2>&1 3>&- < /dev/null & echo $! > $SIM/api.pid)
sleep 8
curl -s -o /dev/null -w "api %{http_code}\n" http://127.0.0.1:18177/api/v1/compute/update/

say "=== 2. fake Ollama (the owner's four models) + the 2.10 node"
(setsid nohup python3 $SIM/fake_ollama.py 11555 > $SIM/fake-ollama.log 2>&1 3>&- < /dev/null &)
sleep 1
bash $SIM/sim-old.sh 1 > /dev/null 2>&1
# sim-old.sh started the loop without NM_OLLAMA_URL: restart it with the fake Ollama and the extra kinds
kill $(cat $SIM/old-loop.pid) 2>/dev/null; pkill -f sim_run.py; sleep 2
python3 -c "import shutil; shutil.rmtree('$SIM/mnt/data-old', ignore_errors=True)"
mkdir -p $SIM/mnt/data-old
# sim-old.sh's throw-away first start already got the update command: forget it, like a node that has never been told anything
rm -rf $S/data/node-commands
(cd $S/backend && $PY -X utf8 manage.py shell -c "
from apps.compute.models_platform import NodeAuto
NodeAuto.objects.all().delete()" > /dev/null 2>&1)
: > $SIM/old.log
export NM_SITE=http://127.0.0.1:18177 NM_TOKEN=$(cat $SIM/token-old.txt) NM_NODE=SIM-OLD-210 NM_DATA=$SIM/mnt/data-old NM_ALLOW_SECOND_AGENT=1
export NM_OLLAMA_URL=http://127.0.0.1:11555 PIP_NO_INDEX=1 PYTHONUNBUFFERED=1
export SIM_KINDS=echo,node.update,selftest.gpu,selftest.ffmpeg,edit.slides_mp4,ollama.chat,ollama.generate
(setsid nohup nice -n 10 bash $SIM/sim-loop.sh $SIM/old $SIM/old.log 3>&- > /dev/null 2>&1 < /dev/null & echo $! > $SIM/old-loop.pid)
say "old agent started; waiting for the self-update 2.10 -> current"
for i in $(seq 1 40); do
  sleep 3
  grep -q "update confirmed" $SIM/old.log && break
done
grep -E "node v2\.|panel command|Restarting the node|update confirmed|sim: this node" $SIM/old.log | cut -c1-160
grep -q "update confirmed" $SIM/old.log || fail "the 2.10 node did not confirm the update"
say "UPDATE OK: $(grep -m1 '^VERSION' $SIM/old/agent.py)"

say "=== 3. node on -> automatic self-test run (version) + a few cheap jobs"
cd $S/backend
for i in 1 2 3 4 5 6; do $PY -X utf8 manage.py shell -c "
from apps.compute.tasks import maintenance
import json
o = maintenance(); print(json.dumps({k: o[k] for k in ('autopilot','deferred','heal') if k in o}, ensure_ascii=False, default=str)[:260])" 2>&1 | tail -1; sleep 6; done
$PY -X utf8 manage.py shell -c "
from apps.compute.models import ComputeJob, ComputeNode
from apps.compute import services as SV
import time
n = ComputeNode.objects.get(name='SIM-OLD-210')
print('node online', n.online, 'agent', (n.capabilities or {}).get('agent'), 'ollama', (n.capabilities or {}).get('ollama'), (n.capabilities or {}).get('ollama_models'))
jobs = [SV.enqueue('echo', payload={'sleep': 0, 'hello': 'tonight'}, origin='sim'), SV.enqueue('selftest.ffmpeg', payload={}, origin='sim')]
print('submitted', [(j.kind, j.state) for j in jobs])
" 2>&1 | grep -v imported

say "=== 4. node OFF (loop killed) while the owner asks for an AI draft -> queued durably"
kill $(cat $SIM/old-loop.pid) 2>/dev/null; pkill -f sim_run.py; sleep 3
for i in $(seq 1 14); do
  online=$($PY -X utf8 manage.py shell -c "
from apps.compute.models import ComputeNode
print('ONLINE' if ComputeNode.objects.get(name='SIM-OLD-210').online else 'OFFLINE')" 2>&1 | tail -1)
  [ "$online" = "OFFLINE" ] && break
  sleep 8
done
say "node state: $online"
$PY -X utf8 manage.py shell -c "
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from django.urls import reverse
from apps.stores.models import Store
from apps.compute import deferred
from apps.compute.models import ComputeJob
store = Store.objects.get(pk=34)
c = APIClient(); c.force_authenticate(store.owner)
r = c.post(reverse('brandchar-persona-draft', kwargs={'store_id': 34}), {'brief': 'شاد و کوتاه', 'use_ai': True}, format='json', HTTP_HOST='localhost')
d = r.json()
print('HTTP', r.status_code, '| rule draft archetype:', d['persona']['archetype'], '| ai.used:', d['ai']['used'], '| queued:', (d.get('queued') or {}).get('message'))
print('notes:', [n for n in d['notes'] if 'صف' in n][:1])
print('placeholder rows:', [(j.kind, j.state, j.message, (j.payload or {}).get('title')) for j in ComputeJob.objects.filter(kind='wait.node', origin='deferred')])
open('/root/stage/r4ready-sim/deferred-uid.txt','w').write(d['queued']['uid'])
" 2>&1 | grep -v imported
DUID=$(cat $SIM/deferred-uid.txt)
say "wake while the node is OFF must do nothing:"
$PY -X utf8 manage.py shell -c "
from apps.compute import deferred
print('woken', deferred.wake(), 'status', deferred.status('$DUID')['state'])" 2>&1 | grep -v imported

say "=== 5. node comes back ON -> the queued request runs by itself (node first)"
export NM_SITE=http://127.0.0.1:18177 NM_TOKEN=$(cat $SIM/token-old.txt) NM_NODE=SIM-OLD-210 NM_DATA=$SIM/mnt/data-old NM_ALLOW_SECOND_AGENT=1
export NM_OLLAMA_URL=http://127.0.0.1:11555 PIP_NO_INDEX=1 PYTHONUNBUFFERED=1
export SIM_KINDS=echo,node.update,selftest.gpu,selftest.ffmpeg,edit.slides_mp4,ollama.chat,ollama.generate
(setsid nohup nice -n 10 bash $SIM/sim-loop.sh $SIM/old $SIM/old.log 3>&- > /dev/null 2>&1 < /dev/null & echo $! > $SIM/old-loop.pid)
sleep 25
for i in $(seq 1 12); do
  out=$($PY -X utf8 manage.py shell -c "
from apps.compute import deferred
import json
w = deferred.wake()
s = deferred.status('$DUID')
print(json.dumps({'woken': w, 'state': s['state'], 'msg': s.get('message')}, ensure_ascii=False))" 2>&1 | tail -1)
  say "$out"
  echo "$out" | grep -q '"state": "done"' && break
  sleep 10
done
$PY -X utf8 manage.py shell -c "
from apps.compute import deferred
s = deferred.status('$DUID')
print('FINAL', s['state'], '| attempts', s.get('attempts'), '| archetype', ((s.get('result') or {}).get('persona') or {}).get('archetype'), '| ai.used', ((s.get('result') or {}).get('ai') or {}).get('used'), '| label', ((s.get('result') or {}).get('ai') or {}).get('label'))
from apps.compute.models import ComputeJob
print('ollama jobs:', list(ComputeJob.objects.filter(kind__startswith='ollama.', origin__in=['ai','']).order_by('-id').values_list('kind','state','last_node_name')[:3]))
" 2>&1 | grep -v imported
grep -q '"state": "done"' $LOG || say "NOTE: the deferred request is not done yet"

say "=== 6. self-test run + cheap jobs + GPU-only kinds still waiting"
for i in 1 2 3 4 5 6 7 8; do $PY -X utf8 manage.py shell -c "
from apps.compute.tasks import maintenance
maintenance()" > /dev/null 2>&1; sleep 7; done
$PY -X utf8 manage.py shell -c "
from collections import Counter
from apps.compute.models import ComputeJob, ComputeNode
from apps.compute.models_platform import SelfTestRun
n = ComputeNode.objects.get(name='SIM-OLD-210')
print('node', n.name, 'agent', (n.capabilities or {}).get('agent'), 'kinds', sorted((n.capabilities or {}).get('kinds') or []))
for k in ('echo', 'selftest.ffmpeg', 'selftest.gpu', 'edit.slides_mp4'):
    js = ComputeJob.objects.filter(kind=k, node=n).order_by('-id')[:2]
    print('  claimed+ran', k, [(j.state, round(j.run_s or 0, 2)) for j in js])
print('GPU-only kinds in the queue (must stay QUEUED, none claimed by the sim):')
for k in ('comfy.graph', 'motion.render', 'voice.music', 'multiangle.virtual', 'up3d.render', 'photo.edit'):
    c = Counter(ComputeJob.objects.filter(kind=k).values_list('state', flat=True))
    node_ids = set(ComputeJob.objects.filter(kind=k, node__isnull=False, node__name__startswith='SIM-').values_list('id', flat=True))
    print('  ', k, dict(c), 'claimed-by-sim:', len(node_ids))
r = SelfTestRun.objects.filter(node=n).order_by('-id').first()
print('selftest run', r.pk, r.state, r.trigger, r.agent_version, dict(Counter(r.results.values_list('state', flat=True))))
for x in r.results.filter(key__in=['echo','update_flow','bootstrap','ollama_text','ai_queue','chagher_content','design_offline']):
    print('   ', x.key, x.state, (x.detail or '')[:110])
" 2>&1 | grep -v imported
say "=== 7. the Tonight report as the panel sees it"
$PY -X utf8 manage.py shell -c "
from apps.compute import tonight
r = tonight.build()
print('phase', r['phase'], '|', r['phase_text'])
for s in r['steps']:
    print('  [%-5s] %-45s %s' % (s['state'], s['title'][:45], s['detail'][:110]))
" 2>&1 | grep -v imported
echo DONE
