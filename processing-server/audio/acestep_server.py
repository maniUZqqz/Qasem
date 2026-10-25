"""Background music: ACE-Step 1.5 (MIT; its output may be used commercially) through its own REST API.

Run by agent.py inside venvs\\acestep (Download-Models.bat makes it):

    venvs\\acestep\\Scripts\\python.exe audio\\acestep_server.py --port 5642

This only prepares ACE-Step's own API server (acestep/api_server.py, as its start_api_server.bat does) for this
node: the checkpoints downloaded into models\\acestep\\checkpoints, no 5Hz language model (instrumental beds do
not need it and it would take 4 GB more of VRAM), no flash-attention (no Windows wheel for Python 3.12), no
automatic downloads, and the models load at start-up so an open port means "ready". The agent then speaks the
documented API: POST /release_task, POST /query_result, GET /v1/audio?path=..., GET /health.
The process exits with the agent (--parent-pid), like the other GPU workers.
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import parent_alive  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="UpMarket: ACE-Step 1.5 API server for this node")
    ap.add_argument("--port", type=int, default=5642)
    ap.add_argument("--home", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--parent-pid", type=int, default=0)
    args = ap.parse_args()
    repo = os.path.join(args.home, "vendor", "ACE-Step-1.5")
    root = os.path.join(args.home, "models", "acestep")
    for p in (os.path.join(repo, "acestep", "api_server.py"), os.path.join(root, "checkpoints", "acestep-v15-turbo")):
        if not os.path.exists(p):
            print("missing %s - run Download-Models.bat" % p, flush=True)
            sys.exit(2)
    env = {
        "ACESTEP_PROJECT_ROOT": root,            # checkpoints\ lives here
        "ACESTEP_CONFIG_PATH": "acestep-v15-turbo",
        "ACESTEP_INIT_LLM": "false",
        "ACESTEP_USE_FLASH_ATTENTION": "false",
        "ACESTEP_NO_INIT": "false",              # load at start-up: an open port means ready
        "ACESTEP_DOWNLOAD_SOURCE": "huggingface",
        "ACESTEP_TMPDIR": os.path.join(root, "tmp"),
        "TRITON_CACHE_DIR": os.path.join(root, "cache", "triton"),
        "TORCHINDUCTOR_CACHE_DIR": os.path.join(root, "cache", "inductor"),
        "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1",
    }
    for k, v in env.items():
        os.environ.setdefault(k, v)
    os.makedirs(os.environ["ACESTEP_TMPDIR"], exist_ok=True)
    os.chdir(root)
    sys.path.insert(0, repo)
    if args.parent_pid:
        def watchdog():
            while True:
                time.sleep(5)
                if not parent_alive(args.parent_pid):
                    print("[acestep] the agent is gone - exiting to free the GPU", flush=True)
                    os._exit(0)
        threading.Thread(target=watchdog, daemon=True).start()
    from acestep.api_server import main as api_main

    sys.argv = ["acestep-api", "--host", "127.0.0.1", "--port", str(args.port)]
    api_main()


if __name__ == "__main__":
    main()
