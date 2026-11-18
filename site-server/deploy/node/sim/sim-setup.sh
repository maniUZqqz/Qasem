#!/bin/bash
# one-time setup of the node simulation (deploy/node/sim/README.md): working folder, capped data disk, and the 2.10 fixture.
# usage: REPO=/root/stage/<key> SIM=/root/stage/<key>-sim bash sim-setup.sh
REPO=${REPO:-/root/stage/r4ready}; SIM=${SIM:-/root/stage/r4ready-sim}
set -e
mkdir -p $SIM/mnt
cp $REPO/deploy/node/sim/*.sh $REPO/deploy/node/sim/*.py $SIM/
rm -rf $SIM/old210-src && cp -r $REPO/deploy/node/sim/old210 $SIM/old210-src
# the 2.10 agent itself is not stored in the public repo (it still mentions a tool that has its own repository); take it from the server backup
OLD_AGENT=${OLD_AGENT:-/root/backups/nodeplatform-20261113-105742/files/processing/agent.py}
[ -f "$OLD_AGENT" ] || { echo "the agent 2.10 file is missing: set OLD_AGENT=<path of processing/agent.py at version 2.10>"; exit 1; }
grep -q '^VERSION = "2.10"' "$OLD_AGENT" || { echo "$OLD_AGENT is not agent 2.10"; exit 1; }
cp "$OLD_AGENT" $SIM/old210-src/agent.py
if ! mountpoint -q $SIM/mnt; then
  dd if=/dev/zero of=$SIM/data.img bs=1M count=450 status=none && mkfs.ext4 -qF $SIM/data.img && mount -o loop $SIM/data.img $SIM/mnt
fi
df -h $SIM/mnt | tail -1
echo "ready: now run  bash $SIM/sim-final.sh  (detached: setsid nohup bash ... 3>&- &)"
