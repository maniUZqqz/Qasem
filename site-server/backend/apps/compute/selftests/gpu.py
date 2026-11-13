"""آزمونِ «کارت گرافیک دیده می‌شود؟»: nvidia-smi، درایور، torch.cuda در هر محیطی که torch دارد، onnxruntime با GPU، ffmpeg."""
from . import SelfTest, Spec, Verdict, register

GPU_PROVIDERS = ("CUDAExecutionProvider", "DmlExecutionProvider")


def build(ctx):
    return Spec("selftest.gpu", {}, timeout_s=300)


def check(ctx, job):
    rep = ctx.read_json(job, "gpu.json")
    if not isinstance(rep, dict):
        return Verdict.failed("گزارشِ gpu.json از سرورِ پردازش نرسید.")
    if not rep.get("visible"):
        return Verdict.failed("nvidia-smi کارتِ گرافیک را نمی‌بیند؛ درایورِ NVIDIA نصب و کارت فعال است؟", device="cpu")
    problems = []
    if rep.get("driver_ok") is False:
        problems.append("درایور %s برای CUDA 12 قدیمی است (۵۲۷ به بالا لازم است)" % rep.get("driver"))
    for env, row in (rep.get("envs") or {}).items():
        t = row.get("torch") or {}
        if t.get("torch") and not t.get("cuda"):
            problems.append("torch در محیطِ «%s» (نسخهٔ %s) کارت را نمی‌بیند؛ نسخهٔ CPU نصب شده است" % (env, t.get("torch")))
        o = row.get("onnxruntime") or {}
        if o.get("ort") and env == "matting" and not any(p in GPU_PROVIDERS for p in o.get("providers") or []):
            problems.append("onnxruntime در محیطِ «matting» فقط CPU دارد (%s)" % ", ".join(o.get("providers") or []))
    name = rep.get("name") or "GPU"
    vram = rep.get("vram_total_mb")
    parts = ["%s" % name]
    if vram:
        parts.append("%d مگابایت" % vram)
    if rep.get("driver"):
        parts.append("درایور %s" % rep["driver"])
    torch_ok = [e for e, r in (rep.get("envs") or {}).items() if (r.get("torch") or {}).get("cuda")]
    if torch_ok:
        parts.append("torch.cuda: " + "، ".join(torch_ok))
    ff = rep.get("ffmpeg") or {}
    if ff.get("nvenc_h264"):
        parts.append("ffmpeg با NVENC")
    elif ff.get("path"):
        problems.append("ffmpeg (%s) رمزگذاریِ NVENC ندارد" % ff.get("path"))
    detail = " · ".join(parts)
    if problems:
        return Verdict.failed("؛ ".join(problems) + " — " + detail, device="cuda", extra={"report": rep})
    return Verdict.passed(detail, device="cuda", extra={"report": rep})


register(SelfTest(key="gpu", label="کارتِ گرافیک و درایور (nvidia-smi، torch.cuda، onnxruntime)", group="gpu", kind="selftest.gpu",
                  build=build, check=check, order=10, min_agent="2.11", needs_features=("gpu-runtime", "ffmpeg-nvenc"), describe="کارت دیده می‌شود و کتابخانه‌ها از آن استفاده می‌کنند"))
