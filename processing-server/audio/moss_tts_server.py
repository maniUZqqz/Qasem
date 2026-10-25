"""Persian speech and voice cloning: MOSS-TTS-Realtime (1.7B, Apache-2.0) + the Persian LoRA (Apache-2.0).

Run by agent.py inside venvs\\moss-tts (Download-Models.bat makes it):

    venvs\\moss-tts\\Scripts\\python.exe audio\\moss_tts_server.py --port 5640 [--fake]

POST /run {"text", "reference": <wav path: the voice to speak in>, "out": <wav path>, "seed"?, "temperature"?}
-> {"ok", "seconds", "chunks", "sample_rate"}

The model is a zero-shot cloner: the voice always comes from the reference clip (a default Persian voice or a
shop's own cloned voice). Following the LoRA's serving notes: Persian digits become words, long text is cut
into ~12 s utterances, each utterance starts with "، " (the model swallows a cold first word otherwise), and
generation is capped at 1200 tokens (~90 s) per utterance.
Not exercised on real hardware by the site's tests (they use --fake); first real run: watch logs\\service-moss.log.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Worker, WorkerError, serve  # noqa: E402

SR = 24000


class MossTTS(Worker):
    name = "moss-fa"

    def load(self, args):
        os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")
        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio
        from peft import PeftModel
        from transformers import AutoModel, AutoTokenizer

        home = args.home
        repo = os.path.join(home, "vendor", "MOSS-TTS", "moss_tts_realtime")
        base = os.path.join(home, "models", "moss-tts", "MOSS-TTS-Realtime")
        lora = os.path.join(home, "models", "moss-tts", "persian-lora")
        codec_dir = os.path.join(home, "models", "moss-tts", "MOSS-Audio-Tokenizer")
        for p in (repo, base, lora, codec_dir):
            if not os.path.isdir(p):
                raise RuntimeError("missing %s - run Download-Models.bat" % p)
        sys.path.insert(0, repo)
        sys.path.insert(0, lora)
        from inferencer import MossTTSRealtimeInference
        from mossttsrealtime.modeling_mossttsrealtime import MossTTSRealtime
        from fa_normalize import chunk, normalize

        cuda = torch.cuda.is_available()
        device = "cuda" if cuda else "cpu"
        dtype = torch.bfloat16 if cuda and torch.cuda.get_device_capability()[0] >= 8 else (torch.float16 if cuda else torch.float32)
        total_mb = torch.cuda.get_device_properties(0).total_memory // 2 ** 20 if cuda else 0
        # the codec is 7 GB in float32; on a 12 GB card it shares the GPU with the 4.7 GB talker -> half precision
        codec_dtype = {"float32": torch.float32, "bfloat16": torch.bfloat16, "float16": torch.float16}.get(
            os.environ.get("NM_MOSS_CODEC_DTYPE", ""), torch.float32 if (not cuda or total_mb >= 20000) else dtype)

        model = MossTTSRealtime.from_pretrained(base, torch_dtype=dtype, attn_implementation="sdpa" if cuda else "eager")
        model = PeftModel.from_pretrained(model, lora).merge_and_unload().to(device).eval()
        tokenizer = AutoTokenizer.from_pretrained(base)
        codec = AutoModel.from_pretrained(codec_dir, trust_remote_code=True, torch_dtype=codec_dtype).eval().to(device)

        def load_audio(_self, path, target_sample_rate):
            # torchaudio.load needs torchcodec + FFmpeg DLLs on Windows; soundfile reads WAV/FLAC/OGG without them
            data, sr = sf.read(path, dtype="float32", always_2d=True)
            wav = torch.from_numpy(np.ascontiguousarray(data.T))
            if sr != target_sample_rate:
                wav = torchaudio.functional.resample(wav, sr, target_sample_rate)
            if wav.ndim == 2 and wav.shape[0] > 1:
                wav = wav.mean(dim=0, keepdim=True)
            return wav

        cache = {}
        original_encode = MossTTSRealtimeInference._encode_reference_audio

        def encode_cached(_self, path, device):
            st = os.stat(path)
            key = (os.path.abspath(path), st.st_size, int(st.st_mtime))
            if key not in cache:
                if len(cache) > 32:
                    cache.clear()
                cache[key] = original_encode(_self, path, device)
            return cache[key]

        MossTTSRealtimeInference._load_audio = load_audio
        MossTTSRealtimeInference._encode_reference_audio = encode_cached
        self.torch, self.np, self.sf = torch, np, sf
        self.codec, self.chunk, self.normalize = codec, chunk, normalize
        self.inferencer = MossTTSRealtimeInference(model, tokenizer, max_length=1200, codec=codec, codec_sample_rate=SR,
                                                   codec_encode_kwargs={"chunk_duration": 8})
        self.device_name = device
        self.device = "%s %s (codec %s)" % (device, str(dtype).replace("torch.", ""), str(codec_dtype).replace("torch.", ""))

    def _pieces(self, text):
        pieces = [p.strip() for p in self.chunk(self.normalize(text.strip())) if p.strip()]
        return [p if p[0] in "،.؛!؟…," else "، " + p for p in pieces]

    def run(self, body):
        torch = self.torch
        text = str(body.get("text") or "").strip()
        ref = body.get("reference")
        if not text:
            raise WorkerError("text is empty", 400)
        if not ref or not os.path.isfile(ref):
            raise WorkerError("reference voice file not found: %s" % ref, 400)
        seed = body.get("seed")
        if seed not in (None, ""):
            seed = int(seed)
            torch.manual_seed(seed)
            random.seed(seed)
            self.np.random.seed(seed % (2 ** 32))
        params = dict(temperature=float(body.get("temperature", 0.8)), top_p=float(body.get("top_p", 0.6)),
                      top_k=int(body.get("top_k", 30)), repetition_penalty=float(body.get("repetition_penalty", 1.1)),
                      repetition_window=50, device=self.device_name)
        pieces = self._pieces(text)
        gap = torch.zeros(int(float(body.get("gap", 0.3)) * SR))
        parts = []
        with torch.inference_mode():
            for piece in pieces:
                result = self.inferencer.generate(text=[piece], reference_audio_path=[ref], **params)
                tokens = torch.tensor(result[0]).to(self.device_name)
                w = self.codec.decode(tokens.permute(1, 0), chunk_duration=8)["audio"][0].detach().float().cpu()
                parts += [w if w.ndim == 1 else w.reshape(-1), gap]
        wav = torch.cat(parts[:-1]).clamp(-1, 1).numpy() if parts else self.np.zeros(1, dtype="float32")
        out = body["out"]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        self.sf.write(out, wav, SR, subtype="PCM_16")
        if self.device_name == "cuda":
            torch.cuda.empty_cache()
        return {"ok": True, "seconds": round(len(wav) / SR, 2), "chunks": len(pieces), "sample_rate": SR}

    def fake_run(self, body):
        if not str(body.get("text") or "").strip():
            raise WorkerError("text is empty", 400)
        ref = body.get("reference")
        if not ref or not os.path.isfile(ref):
            raise WorkerError("reference voice file not found: %s" % ref, 400)
        from _common import fake_tone, write_wav

        seconds = max(1.0, len(str(body["text"])) / 12.5)
        write_wav(body["out"], fake_tone(seconds, SR), SR)
        return {"ok": True, "seconds": round(seconds, 2), "chunks": 1, "sample_rate": SR, "fake": True}


if __name__ == "__main__":
    serve(MossTTS, 5640)
