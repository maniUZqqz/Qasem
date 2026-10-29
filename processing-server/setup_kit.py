"""Prepare the PersianAiKit editors (photo / video / voice) on this node in one go.

Not required any more: since agent v1.5 each editor prepares itself the first time a job needs it.
Running this ahead of time just avoids the wait on the first job. For every editor it
  1. builds it with the local .NET SDK when one is installed (also found when it is not on PATH), or
  2. downloads the ready Windows build from the site ({site}/3d/files/downloads/kit-app-*.zip, resumable),
then fetches ffmpeg (video) and the voice / photo models when missing.
    python setup_kit.py            the three editors, the default Persian voice
    python setup_kit.py --all      + all six Persian voices (about 280 MB more)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agent  # noqa: E402


def main():
    ok = True
    agent.prepare_data()          # the data folder (agent 2.0): an older copy's editors are moved there, not fetched again
    for key in ("photo", "video", "voice"):
        print("[%s]" % key, flush=True)
        try:
            agent.ensure_editor(key, tick=lambda m: print("   " + m, flush=True))
            print("   ready", flush=True)
        except Exception as e:  # noqa: BLE001
            ok = False
            print("   FAILED: %s" % e, flush=True)
    if "--all" in sys.argv:
        try:
            agent.fetch_pack("kit-models-voice.zip", tick=lambda m: print("   " + m, flush=True))
        except Exception as e:  # noqa: BLE001
            print("   all voices: FAILED: %s" % e)
    print("RESULT: %s" % ("editors ready" if ok else "INCOMPLETE - see the lines above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
