#!/bin/bash
# build a "2.10" folder (the code the owner's GPU computer has) + start it as the temporary node SIM-OLD-210 (stage DB, capped data disk)
S=/root/stage/r4ready; SIM=/root/stage/r4ready-sim
PY=/var/www/NM/upmarket/venv/bin/python
OLD=$SIM/old
SRC=$SIM/old210-src          # the 2.10 fixture (deploy/node/sim/old210): agent.py 2.10 + edit_render.py + update.py 1.1 + nm_data.py + nm_fetch.py
python3 -c "import shutil; shutil.rmtree('$OLD', ignore_errors=True)"
mkdir -p $OLD
cp $SRC/agent.py $SRC/edit_render.py $SRC/update.py $SRC/nm_data.py $SRC/nm_fetch.py $OLD/
for f in edit_jobs.py photo_matting.py edit_rvm.py edit_track.py START.bat Update.bat; do [ -f $S/processing/$f ] && cp $S/processing/$f $OLD/; done
echo '{"site": "http://127.0.0.1:18177"}' > $OLD/site.json
grep -m1 '^VERSION' $OLD/agent.py $OLD/update.py
cd $S/backend
$PY -X utf8 manage.py shell -c "
from apps.compute.models import ComputeNode
import secrets
n,created = ComputeNode.objects.get_or_create(name='SIM-OLD-210', defaults={'token': secrets.token_hex(20), 'enabled': True, 'notes': 'r4ready simulation of agent 2.10 (stage DB only)'})
open('$SIM/token-old.txt','w').write(n.token)
print('node', n.pk, created)
" 2>&1 | tail -1
[ -f $SIM/old-loop.pid ] && kill $(cat $SIM/old-loop.pid) 2>/dev/null
: > $SIM/old.log
export NM_SITE=http://127.0.0.1:18177 NM_TOKEN=$(cat $SIM/token-old.txt) NM_NODE=SIM-OLD-210 NM_DATA=$SIM/mnt/data-old NM_ALLOW_SECOND_AGENT=1
export SIM_KINDS=echo,node.update,selftest.gpu,selftest.ffmpeg,edit.slides_mp4 PIP_NO_INDEX=1 PYTHONUNBUFFERED=1
mkdir -p $NM_DATA
(setsid nohup nice -n 10 bash $SIM/sim-loop.sh $OLD $SIM/old.log > /dev/null 2>&1 < /dev/null & echo $! > $SIM/old-loop.pid)
sleep ${1:-20}
tail -25 $SIM/old.log
