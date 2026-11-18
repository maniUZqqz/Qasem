#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simulation wrapper (deploy/node/sim): runs the REAL agent.py of a code folder on a Linux box, but with only a few cheap job kinds.

    SIM_CODE=<folder with agent.py>  SIM_KINDS=echo,selftest.ffmpeg  python3 sim_run.py

The agent module is imported, its HANDLERS are cut down to SIM_KINDS (agent.py publishes sorted(HANDLERS) as caps['kinds'], so the
site only routes those kinds here) and agent.main() runs - the same code path START.bat starts on the GPU computer.
Used only by deploy/node/sim-*.sh on a test machine; never shipped to the node (deploy/ is not part of the node package).
"""
import os
import sys

code = os.environ["SIM_CODE"]
os.chdir(code)
sys.path.insert(0, code)
import agent  # noqa: E402

keep = {k for k in os.environ.get("SIM_KINDS", "echo").split(",") if k}
for kind in list(agent.HANDLERS):
    if kind not in keep:
        del agent.HANDLERS[kind]
print("sim: this node serves only %s" % ", ".join(sorted(agent.HANDLERS)), flush=True)
sys.argv = ["agent.py"] + sys.argv[1:]
sys.exit(agent.main() or 0)
