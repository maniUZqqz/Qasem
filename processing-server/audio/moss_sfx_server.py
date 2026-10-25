"""Ambience and sound effects: MOSS-SoundEffect v2.0 (DiT + DAC + Qwen3 text encoder, Apache-2.0).

Run by agent.py inside venvs\\moss-sfx (Download-Models.bat makes it):

    venvs\\moss-sfx\\Scripts\\python.exe audio\\moss_sfx_server.py --port 5641 [--fake]

POST /run {"prompt": English description, "seconds": 0.5-30, "out": <wav path>, "steps"?, "cfg_scale"?, "seed"?}
-> {"ok", "seconds", "sample_rate"}   (48 kHz mono)

On Windows torch.compile / Triton are not available, so TorchDynamo is switched off (the model card's own advice).
The DAC VAE checkpoint is a pickled model object from a pinned, sha256-verified file: PyTorch >= 2.6 needs
TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD for that.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Worker, WorkerError, fake_tone, serve, write_wav  # noqa: E402

MAX_SECONDS = 30.0


class MossSFX(Worker):
    name = "moss-sfx"

    def load(self, args):
        os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
        os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
        import soundfile as sf
        import torch

        repo = os.path.join(args.home, "vendor", "MOSS-TTS")
        model_dir = os.path.join(args.home, "models", "moss-sfx", "MOSS-SoundEffect-v2.0")
        for p in (os.path.join(repo, "moss_soundeffect_v2"), model_dir):
            if not os.path.isdir(p):
                raise RuntimeError("missing %s - run Download-Models.bat" % p)
        sys.path.insert(0, repo)
        from moss_soundeffect_v2 import MossSoundEffectPipeline

        cuda = torch.cuda.is_available()
        self.pipe = MossSoundEffectPipeline.from_pretrained(model_dir, torch_dtype=torch.bfloat16,
                                                            device="cuda" if cuda else "cpu")
        self.torch, self.sf = torch, sf
        self.device = "cuda bfloat16" if cuda else "cpu"

    @staticmethod
    def _params(body):
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise WorkerError("prompt is empty", 400)
        try:
            seconds = round(float(body.get("seconds") or 10.0), 1)
        except (TypeError, ValueError):
            raise WorkerError("seconds must be a number", 400)
        if not 0.5 <= seconds <= MAX_SECONDS:
            raise WorkerError("seconds must be between 0.5 and %g" % MAX_SECONDS, 400)
        return prompt, seconds

    def run(self, body):
        prompt, seconds = self._params(body)
        seed = int(body.get("seed") or 0)
        with self.torch.inference_mode():
            audio = self.pipe(prompt=prompt, seconds=seconds, num_inference_steps=int(body.get("steps") or 100),
                              cfg_scale=float(body.get("cfg_scale") or 4.0), sigma_shift=float(body.get("sigma_shift") or 5.0),
                              seed=seed, negative_prompt=str(body.get("negative_prompt") or ""))
        wav = audio[0].detach().float().cpu().clamp(-1, 1).numpy().T          # (T, C)
        out = body["out"]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        self.sf.write(out, wav, self.pipe.sample_rate, subtype="PCM_16")
        if self.device.startswith("cuda"):
            self.torch.cuda.empty_cache()
        return {"ok": True, "seconds": seconds, "sample_rate": self.pipe.sample_rate, "seed": seed}

    def fake_run(self, body):
        _prompt, seconds = self._params(body)
        write_wav(body["out"], fake_tone(seconds, 16000, 440.0), 16000)
        return {"ok": True, "seconds": seconds, "sample_rate": 16000, "fake": True}


if __name__ == "__main__":
    serve(MossSFX, 5641)
