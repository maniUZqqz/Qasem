#!/bin/bash
# stop the simulation, delete the temporary nodes + test jobs (stage DB copy only), unmount and remove the capped data disk
S=/root/stage/r4ready; SIM=/root/stage/r4ready-sim
PY=/var/www/NM/upmarket/venv/bin/python
cp /root/stage/r4ready-sim-final.log $S/deploy/node/sim/LAST-RUN.txt
for f in old-loop.pid api.pid; do [ -f $SIM/$f ] && kill $(cat $SIM/$f) 2>/dev/null; done
pkill -f sim_run.py 2>/dev/null
for p in $(ps -eo pid,cmd | grep -E "r4ready-sim/(old|mnt)|fake_ollama.py 11555|runserver 127.0.0.1:18177" | grep -v grep | awk '{print $1}'); do kill $p 2>/dev/null; done
sleep 3
cd $S/backend
export AI_API_KEY="" AI_API_BASE_URL=""
$PY -X utf8 manage.py shell -c "
from apps.compute.models import ComputeNode, ComputeJob
from apps.compute.models_platform import SelfTestRun, NodeAuto
sim = ComputeNode.objects.filter(name__startswith='SIM-')
ids = list(sim.values_list('pk', flat=True))
n_jobs = ComputeJob.objects.filter(node_id__in=ids).count() + ComputeJob.objects.filter(origin__in=['sim', 'deferred']).count()
ComputeJob.objects.filter(node_id__in=ids).delete()
ComputeJob.objects.filter(origin__in=['sim', 'deferred']).delete()
SelfTestRun.objects.filter(node_id__in=ids).delete()
NodeAuto.objects.filter(node_id__in=ids).delete()
print('deleted temp nodes', sim.count(), 'test jobs', n_jobs)
sim.delete()
print('remaining SIM nodes', ComputeNode.objects.filter(name__startswith='SIM-').count(), '| real nodes', list(ComputeNode.objects.values_list('pk', 'name')))
" 2>&1 | grep -v imported
rm -rf $S/data/ai-deferred $S/data/node-commands
umount $SIM/mnt 2>&1; mountpoint -q $SIM/mnt && echo "STILL MOUNTED" || echo "unmounted"
python3 -c "import shutil; shutil.rmtree('$SIM', ignore_errors=True)"
ls -d $SIM 2>&1 | head -1
ps -eo pid,cmd | grep -E "r4ready-sim|fake_ollama|sim_run|runserver 127.0.0.1:18177" | grep -v grep | head
df -h / | tail -1
