"""اسکلتِ شخصیت (قطعه‌های لایه‌ای با لولا، سلسله‌مراتبِ پدر و فرزند و ترتیبِ عمق) و ریاضیاتِ تبدیل — فقط برای «یک قابِ ثابت».

SOURCE: ported from InstAI (maniUZqqz/Instai) instai/render/puppet/geometry.py + instai/render/puppet/rig.py @ 82733b0,
adapted for NMarketing brand mascots: only the still-frame part is kept (matrices, parent chain, z-order, one visible state per group);
the animation timeline, easing, blinking and lip-sync of the puppet renderer are NOT ported (a mascot post is one frame, see engine/stage.py).
Part pictures are PIL images held in memory (no part files on disk).

مختصاتِ هر قطعه پیکسلِ «بومِ طراحی» است (۶۰۰×۹۰۰)؛ ``pivot`` لولاست (درونِ تصویرِ خودِ قطعه) و ``pos`` جای لولا در فضای والد. قطعه‌هایی که ``group``
یکسان دارند (دهان، چشم، ابرو، شست) جایگزینِ هم‌اند: در هر لحظه فقط یک ``state`` از هر گروه دیده می‌شود.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PIL import Image

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

MOUTH_SHAPES = "ABCDEFGHX"                     # شکل‌های دهانِ Rhubarb (همان نام‌های InstAI)
MOUTH_FALLBACK = {"A": ["X"], "B": ["A", "X"], "C": ["B", "D", "A"], "D": ["C", "B", "A"], "E": ["C", "B", "A"], "F": ["E", "C", "B", "A"],
                  "G": ["B", "A"], "H": ["C", "B", "A"], "X": ["A", "B"]}
GROUP_DEFAULT = {"mouth": "X", "eyes": "open", "brows": "neutral"}
#: گروه‌هایی که فقط وقتی صریحاً خواسته شوند دیده می‌شوند (شستِ «👍»)
OPTIONAL_GROUPS = ("thumb",)


# ------------------------------------------------------------------ 2D affine maths (as SVG: x' = a*x + c*y + e, y' = b*x + d*y + f)

def mul(m: Matrix, n: Matrix) -> Matrix:
    """m after n (n is applied first)."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2, a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def translate(tx: float, ty: float) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def scale(sx: float, sy: float | None = None) -> Matrix:
    return (sx, 0.0, 0.0, sx if sy is None else sy, 0.0, 0.0)


def rotate(deg: float) -> Matrix:
    """چرخشِ مثبت = ساعت‌گرد روی صفحه (محورِ y پایین است)."""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (c, s, -s, c, 0.0, 0.0)


def apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def invert(m: Matrix) -> Matrix:
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise ValueError("singular matrix")
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(ia * e + ic * f), -(ib * e + id_ * f))


def pil_inverse(m: Matrix) -> tuple[float, float, float, float, float, float]:
    """ضریب‌های ``Image.transform(AFFINE)``: هر پیکسلِ خروجی را به پیکسلِ ورودی برمی‌گرداند (وارونِ m)."""
    ia, ib, ic, id_, ie, if_ = invert(m)
    return (ia, ic, ie, ib, id_, if_)


def bbox(m: Matrix, w: float, h: float) -> tuple[float, float, float, float]:
    pts = [apply(m, x, y) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


# ------------------------------------------------------------------ the rig

class RigError(ValueError):
    pass


@dataclass
class Part:
    name: str
    image: Image.Image | None
    pivot: tuple[float, float] = (0.0, 0.0)
    pos: tuple[float, float] = (0.0, 0.0)
    z: int = 10
    parent: str | None = None
    group: str | None = None
    state: str | None = None


#: چرخشِ هر قطعه: (dx, dy, rot درجه، sx، sy) در فضای والد
PoseTuple = tuple[float, float, float, float, float]


@dataclass
class Rig:
    size: tuple[int, int]
    anchor: tuple[float, float]
    parts: dict[str, Part] = field(default_factory=dict)

    def validate(self) -> None:
        for p in self.parts.values():
            if p.parent is not None and p.parent not in self.parts:
                raise RigError(f"part {p.name}: unknown parent {p.parent}")
        for p in self.parts.values():                     # cycles
            seen, cur = set(), p
            while cur.parent is not None:
                if cur.name in seen:
                    raise RigError(f"parent loop at {cur.name}")
                seen.add(cur.name)
                cur = self.parts[cur.parent]
        if not any(p.parent is None for p in self.parts.values()):
            raise RigError("no root part")

    def groups(self) -> dict[str, dict[str, Part]]:
        out: dict[str, dict[str, Part]] = {}
        for p in self.parts.values():
            if p.group and p.state:
                out.setdefault(p.group, {})[p.state] = p
        return out

    def choose_state(self, group: str, wanted: str) -> str | None:
        """حالتِ ``group`` که برای ``wanted`` نشان داده می‌شود (با زنجیرهٔ جایگزینِ دهان)؛ None اگر گروه نیست."""
        states = self.groups().get(group)
        if not states:
            return None
        if wanted in states:
            return wanted
        for alt in MOUTH_FALLBACK.get(wanted, []) if group == "mouth" else []:
            if alt in states:
                return alt
        default = GROUP_DEFAULT.get(group)
        return default if default in states else sorted(states)[0]

    def chain(self, name: str) -> list[Part]:
        """root -> ... -> part."""
        out, cur = [], self.parts[name]
        while True:
            out.append(cur)
            if cur.parent is None:
                break
            cur = self.parts[cur.parent]
        return out[::-1]

    def world_matrices(self, base: Matrix, pose: dict[str, PoseTuple]) -> dict[str, Matrix]:
        """ماتریسِ جهانیِ هر قطعه. ``pose[name]`` = (dx, dy, rot, sx, sy)؛ ``base`` کلِ شخصیت را روی بوم می‌گذارد. قطعه دورِ لولای خودش می‌چرخد و فرزندها دنبالش می‌روند."""
        mats: dict[str, Matrix] = {}

        def world(name: str) -> Matrix:
            if name in mats:
                return mats[name]
            p = self.parts[name]
            parent = world(p.parent) if p.parent else base
            dx, dy, rot, sx, sy = pose.get(name, (0.0, 0.0, 0.0, 1.0, 1.0))
            local = mul(translate(p.pos[0] + dx, p.pos[1] + dy), mul(rotate(rot), mul(scale(sx, sy), translate(-p.pivot[0], -p.pivot[1]))))
            mats[name] = mul(parent, local)
            return mats[name]

        for n in self.parts:
            world(n)
        return mats

    def visible_parts(self, mouth: str, eyes: str = "open", brows: str | None = None, show: tuple[str, ...] = ()) -> list[Part]:
        """قطعه‌هایی که باید کشیده شوند، از پشت به جلو، با یک حالت از هر گروه. گروه‌های اختیاری (شست) فقط اگر در ``show`` باشند."""
        want = {"mouth": mouth, "eyes": eyes, "brows": brows or GROUP_DEFAULT["brows"]}
        chosen = {grp: self.choose_state(grp, w) for grp, w in want.items()}
        out = []
        for p in self.parts.values():
            if p.group in OPTIONAL_GROUPS:
                if p.group not in show:
                    continue
            elif p.group and p.group in chosen and chosen[p.group] != p.state:
                continue
            if p.image is not None:
                out.append(p)
        return sorted(out, key=lambda p: (p.z, p.name))
