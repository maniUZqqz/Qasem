"""وارسیِ خودکارِ درزها: آیا کسی می‌فهمد این‌جا بریده و چسبانده شده؟

برای هر درز (b ⇐ start در ابتدا، end ⇐ a در انتها) سه چیز در ویدیوی نهایی اندازه گرفته و با «حرکتِ عادیِ»
همین ویدیو (فریم‌به‌فریمِ منبع در دو طرفِ تکه) مقایسه می‌شود:

* **پرش** — میانگینِ قدرِ مطلقِ تفاوتِ روشناییِ دو فریمِ پشتِ هم (۰…۲۵۵)، تقسیم بر میانهٔ همین عدد در منبع.
  ۱ یعنی درز درست مثلِ یک گذارِ عادی است؛ بالای ۲٫۵ (و دستِ کم ۳ واحد بیشتر از عادی) یعنی دیده می‌شود.
* **SSIM** — شباهتِ ساختاریِ دو فریمِ دو طرفِ درز در برابرِ SSIM ِ عادیِ فریم‌های پشتِ همِ منبع.
* **پیوستگیِ حرکت** — اندازهٔ جریانِ نوری در درز در برابرِ دو گذارِ قبل و بعدش (توقف/شتابِ ناگهانی = «تکان»).

بزرگ‌ترین پرشِ داخلِ تکه (مثلاً بینِ تکه‌های زنجیره) هم گزارش می‌شود. همه روی روشنایی در عرضِ ۳۲۰ پیکسل.
"""
from __future__ import annotations

import cv2
import numpy as np

from . import media

WIDTH = 320


def _gray(frames: list) -> list:
    return [cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).astype(np.float32) for f in frames]


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = cv2.GaussianBlur(a, (11, 11), 1.5), cv2.GaussianBlur(b, (11, 11), 1.5)
    saa = cv2.GaussianBlur(a * a, (11, 11), 1.5) - mu_a ** 2
    sbb = cv2.GaussianBlur(b * b, (11, 11), 1.5) - mu_b ** 2
    sab = cv2.GaussianBlur(a * b, (11, 11), 1.5) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + c1) * (2 * sab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (saa + sbb + c2))
    return float(m.mean())


def _flow_mag(dis, a: np.ndarray, b: np.ndarray) -> float:
    f = dis.calc(a.astype(np.uint8), b.astype(np.uint8), None)
    return float(np.sqrt((f ** 2).sum(axis=2)).mean())


def verdict(ratio: float, excess: float) -> str:
    if ratio <= 1.6 or excess < 2.0:
        return "invisible"
    if ratio <= 2.5 or excess < 3.0:
        return "slight"
    return "visible"


LABELS = {"invisible": "نامحسوس", "slight": "کمی محسوس", "visible": "محسوس"}


def measure(base, base_info: dict, result, result_info: dict, start: int, end: int, *, window: int = 24) -> dict:
    n = base_info["n_frames"]
    b, a = start - 1, end + 1
    lo, hi = max(0, b - window), min(n - 1, a + window)
    h = max(2, int(round(WIDTH * base_info["height"] / base_info["width"] / 2)) * 2)
    count = hi - lo + 1
    res = _gray(media.read_frames(result, result_info, lo, count, width=WIDTH, height=h))
    org = _gray(media.read_frames(base, base_info, lo, count, width=WIDTH, height=h))

    def diff(frames, i):  # گذارِ i-1 ⇐ i (اندیسِ مطلق)
        return float(np.abs(frames[i - lo] - frames[i - 1 - lo]).mean())

    outside = [i for i in range(lo + 1, hi + 1) if i <= b or i > a]
    normal_d = [diff(org, i) for i in outside] or [diff(org, i) for i in range(lo + 1, hi + 1)]
    normal_s = [ssim(org[i - lo], org[i - 1 - lo]) for i in outside[::2]] or [1.0]
    normal = float(np.median(normal_d)) if normal_d else 0.0
    typ_ssim = float(np.median(normal_s))
    floor = max(normal, 1.0)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)

    def seam(i: int) -> dict:
        d = diff(res, i)
        s = ssim(res[i - lo], res[i - 1 - lo])
        near = [k for k in (i - 2, i - 1, i + 1, i + 2) if lo + 1 <= k <= hi]
        m_seam = _flow_mag(dis, res[i - 1 - lo], res[i - lo])
        m_near = [_flow_mag(dis, res[k - 1 - lo], res[k - lo]) for k in near]
        m_ref = float(np.mean(m_near)) if m_near else m_seam
        ratio = d / floor
        v = verdict(ratio, d - normal)
        if s < typ_ssim - 0.12 and v == "invisible":
            v = "slight"
        return {"frame": i, "diff": round(d, 2), "ratio": round(ratio, 2), "ssim": round(s, 3),
                "typical_ssim": round(typ_ssim, 3), "motion": round(m_seam, 2), "motion_around": round(m_ref, 2),
                "motion_jump": round(abs(m_seam - m_ref) / (m_ref + 0.5), 2),
                "verdict": v, "label": LABELS[v]}

    out = {"normal_diff": round(normal, 2), "typical_ssim": round(typ_ssim, 3), "seams": {}}
    if b >= 0:
        out["seams"]["start"] = seam(b + 1)
    if a < n:
        out["seams"]["end"] = seam(a)
    inner = [(diff(res, i), i) for i in range(max(lo + 1, b + 2), min(hi, a - 1) + 1)]
    if inner:
        d, i = max(inner)
        out["inner_max"] = {"frame": i, "diff": round(d, 2), "ratio": round(d / floor, 2),
                            "verdict": verdict(d / floor, d - normal)}
    worst = max([s["ratio"] for s in out["seams"].values()] or [1.0])
    jump = max([s["motion_jump"] for s in out["seams"].values()] or [0.0])
    score = 100.0 * max(0.0, min(1.0, 1 - (worst - 1.0) / 3.0)) * max(0.5, min(1.0, 1.15 - 0.3 * jump))
    out["score"] = int(round(score))
    order = ["invisible", "slight", "visible"]
    out["verdict"] = max([s["verdict"] for s in out["seams"].values()] or ["invisible"], key=order.index)
    out["label"] = LABELS[out["verdict"]]
    return out
