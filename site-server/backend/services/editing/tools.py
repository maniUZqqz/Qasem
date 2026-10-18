"""The toolbox. §9 — «مدل ارزان = مغز، کد = دست».

§9 draws the line this module enforces: «مدل هرگز دسترسی مستقیم به سیستم ندارد.
فقط می‌تواند از جعبه‌ابزار ما استفاده کند، و هر دستورش قبل از اجرا بررسی
می‌شود.» A model never touches a file, never composes a command, never names a
path. It writes down which tool, where, and how much — and everything it wrote
passes through `validate` before a single frame is read.

That is not only a safety property. It is what makes the cheap model usable at
all: deciding «از ثانیه ۱۸ تا ۲۱ سکوت است، حذفش کن» is a small judgement a small
model makes well, while composing a correct ffmpeg invocation is a large one it
makes badly.

**Why parameters are clamped rather than rejected.** A model that asks to
brighten by 3.0 when the tool allows 0.4 has the right idea and the wrong
magnitude; refusing it throws away a good decision over a bad number. So the
value is pulled into range and the clamp is *recorded on the operation*, which
means it shows up in the plan a human approves instead of quietly becoming a
different edit than the one that was described.

Unknown tools and unknown parameters are refused outright, though. Those are not
magnitude errors — a model inventing a parameter has misunderstood the tool, and
executing the rest of its request as if nothing happened is how an edit ends up
doing something nobody asked for.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

#: What a tool acts on. Kept explicit because the executor batches by kind: all
#: the video filters become one filtergraph, all the cuts become one segment
#: list, and mixing them up produces a command that runs and gives nonsense.
VIDEO_FILTER = "VIDEO_FILTER"
AUDIO_FILTER = "AUDIO_FILTER"
CUT = "CUT"
OVERLAY = "OVERLAY"


class ToolError(Exception):
    """A request the toolbox refuses. Always names what and why, in Persian."""


@dataclass(frozen=True)
class Param:
    name: str
    title: str
    kind: str = "number"        # number | seconds | text | choice | bool
    default: float | str | bool = 0
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    required: bool = False

    def coerce(self, value) -> tuple[object, str | None]:
        """Return (value, note). `note` is set when the value had to be moved."""
        if self.kind == "bool":
            return bool(value), None
        if self.kind in ("text",):
            return str(value)[:500], None
        if self.kind == "choice":
            text = str(value)
            if text not in self.choices:
                raise ToolError(
                    f"«{self.title}» باید یکی از این‌ها باشد: {'، '.join(self.choices)}"
                )
            return text, None
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ToolError(f"«{self.title}» باید عدد باشد، نه {value!r}") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise ToolError(f"«{self.title}» عدد معتبری نیست")

        note = None
        if self.minimum is not None and number < self.minimum:
            note = f"«{self.title}» از {number:g} به {self.minimum:g} محدود شد"
            number = self.minimum
        if self.maximum is not None and number > self.maximum:
            note = f"«{self.title}» از {number:g} به {self.maximum:g} محدود شد"
            number = self.maximum
        return number, note


@dataclass(frozen=True)
class Tool:
    key: str
    title: str
    kind: str
    why: str
    params: tuple[Param, ...] = ()
    #: Builds the ffmpeg fragment. None for tools the executor handles
    #: structurally (cuts are not filters).
    build: Callable[[dict], str] | None = None
    #: Whether re-running this tool on its own output makes things worse.
    #: The agent loop uses it to avoid stacking the same correction twice.
    idempotent: bool = True
    needs_audio: bool = False

    def describe(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "kind": self.kind,
            "why": self.why,
            "params": [
                {
                    "name": p.name, "title": p.title, "kind": p.kind,
                    "default": p.default, "min": p.minimum, "max": p.maximum,
                    "choices": list(p.choices), "required": p.required,
                }
                for p in self.params
            ],
        }


# --------------------------------------------------------------- the tools

#: Trim limits are the ones that matter most. A model asked to "remove the
#: silence" on a video whose audio track failed can otherwise propose removing
#: the entire thing, and a 0-second video is a worse outcome than a slow one.
_START = Param("start", "از ثانیه", kind="seconds", minimum=0, required=True)
_END = Param("end", "تا ثانیه", kind="seconds", minimum=0, required=True)
#: An optional window for a picture correction: one shot of a phone video,
#: not the whole clip. −1 (the default) means the whole clip.
_FROM = Param("from_s", "از ثانیه (اختیاری، برای یک نما)", kind="number", default=-1,
              minimum=-1, maximum=86400)
_TO = Param("to_s", "تا ثانیه (اختیاری)", kind="number", default=-1, minimum=-1, maximum=86400)


def _f(value) -> str:
    """ffmpeg wants plain decimals, never scientific notation."""
    return f"{float(value):.4f}".rstrip("0").rstrip(".") or "0"


#: Where a watermark sits, as an ffmpeg expression pair. Insets are in text
#: heights so the margin looks the same at every resolution.
_CORNERS = {
    "tr": ("w-tw-h/20", "h/20"),
    "tl": ("h/20", "h/20"),
    "br": ("w-tw-h/20", "h-th-h/20"),
    "bl": ("h/20", "h-th-h/20"),
}


def _escape_drawtext(text: str) -> str:
    """ffmpeg's drawtext has its own escaping, and getting it wrong is not a
    cosmetic bug: a colon or a quote in a shop's name ends the option list and
    the whole filtergraph fails to parse."""
    out = str(text)[:80]
    for char, replacement in (
        ("\\", "\\\\"), (":", "\:"), ("'", "’"),
        ("%", "\%"), (",", "\,"), ("[", "\["), ("]", "\]"),
    ):
        out = out.replace(char, replacement)
    return out


#: Where the executor substitutes the path of the text file it writes for the
#: watermark. The text goes through a file rather than the option string:
#: drawtext's own escaping rejected '%' ("Stray % near…" — so «۵۰٪ تخفیف»
#: killed the whole edit) and replaced apostrophes; `expansion=none` with a
#: textfile carries any string untouched.
WATERMARK_TEXTFILE = "__WATERMARK_TEXTFILE__"

#: Bundled Persian font, the same one text_overlay draws posters with. Without
#: a fontfile, fontconfig on Windows has no configuration and Persian renders
#: as boxes.
FONT_DIR = Path(__file__).resolve().parents[1] / "imaging" / "fonts"
FONT_FILE = str(FONT_DIR / "Vazirmatn-Bold.ttf")


def _watermark(params: dict) -> str:
    if not str(params.get("text", "")).strip():
        raise ToolError("«متن» واترمارک خالی است")
    from services.video.ffmpeg import filter_path

    x, y = _CORNERS[str(params.get("position", "br"))]
    opacity = float(params["opacity"])
    # Size as a share of the frame height, so the mark the shop approved on
    # the 360p proxy is the same mark on the 1080p export — an absolute
    # fontsize=28 was 8 % of one and 1.6 % of the other.
    return (
        f"drawtext=fontfile={filter_path(FONT_FILE)}:expansion=none"
        f":textfile={WATERMARK_TEXTFILE}"
        f":x={x}:y={y}"
        f":fontsize='h*{_f(float(params['size']) / 100)}'"
        f":fontcolor=white@{_f(opacity)}"
        f":box=1:boxcolor=black@{_f(opacity * 0.4)}:boxborderw='h*0.008'"
    )


def _blur_region(params: dict) -> str:
    """Blur a percentage box, resolution-independent.

    Clamped so the box always stays inside the frame: `crop` fails outright on
    an out-of-bounds rectangle, which would take the whole edit down over a
    model that guessed 90% wide at 40% from the left.

    **The pad names carry a hash of the region.** This is the only filter here
    that needs named pads, and two blurs in one plan would otherwise both call
    their intermediate `[blurred]`; ffmpeg reads the second as a redefinition
    and the whole graph fails to build. Hashing gives distinct names for
    distinct regions and the same name for the same one, which is the right
    answer to asking for an identical blur twice.
    """
    x = float(params["x"]) / 100
    y = float(params["y"]) / 100
    w = min(float(params["width"]) / 100, 1 - x)
    h = min(float(params["height"]) / 100, 1 - y)
    if w <= 0 or h <= 0:
        raise ToolError("ناحیه‌ی محو شدن بیرون از قاب است")
    tag = hashlib.sha1(
        f"{x}:{y}:{w}:{h}:{params['strength']}".encode()
    ).hexdigest()[:6]
    # The radius is relative to the cropped region, not an absolute pixel
    # count. `boxblur=18` looks correct and fails on every small region: the
    # radius has to be smaller than the plane, and the **chroma** plane is half
    # size, so anything under ~72px wide is rejected outright — the exact case
    # a face or a plate always is. An expression cannot go out of range.
    divisor = max(2.0, 30.0 / max(1.0, float(params["strength"])))
    blur = (
        f"boxblur=lr='min(w\\,h)/{_f(divisor)}':lp=2"
        f":cr='min(w\\,h)/{_f(divisor * 2)}':cp=2"
    )
    return (
        f"split[bg{tag}][fg{tag}];"
        f"[fg{tag}]crop=iw*{_f(w)}:ih*{_f(h)}:iw*{_f(x)}:ih*{_f(y)},"
        f"{blur}[bl{tag}];"
        f"[bg{tag}][bl{tag}]overlay=x=W*{_f(x)}:y=H*{_f(y)}"
    )


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    TOOLS[tool.key] = tool
    return tool


register(Tool(
    key="cut",
    title="برش",
    kind=CUT,
    why="بخشی که به درد نمی‌خورد از ویدیو برداشته می‌شود",
    params=(_START, _END),
    idempotent=False,
))

register(Tool(
    key="trim_silence",
    title="حذف سکوت",
    kind=CUT,
    why="سکوت‌های طولانی وسط حرف، بیننده را می‌پراند",
    params=(
        Param("min_silence", "کوتاه‌ترین سکوتی که حذف شود", kind="seconds",
              default=0.6, minimum=0.25, maximum=5.0),
        Param("keep", "چقدر از سکوت نگه داشته شود", kind="seconds",
              default=0.15, minimum=0.0, maximum=1.0),
    ),
    idempotent=False,
    needs_audio=True,
))

register(Tool(
    key="brightness",
    title="روشنایی",
    kind=VIDEO_FILTER,
    why="تصویر تاریک یا سوخته را به نور طبیعی برمی‌گرداند",
    params=(Param("amount", "میزان", default=0.0, minimum=-0.4, maximum=0.4), _FROM, _TO),
    build=lambda p: f"eq=brightness={_f(p['amount'])}",
))

register(Tool(
    key="contrast",
    title="کنتراست",
    kind=VIDEO_FILTER,
    why="تصویر مه‌آلود و بی‌جان را جان می‌دهد",
    params=(Param("amount", "میزان", default=1.0, minimum=0.6, maximum=1.8), _FROM, _TO),
    build=lambda p: f"eq=contrast={_f(p['amount'])}",
))

register(Tool(
    key="saturation",
    title="اشباع رنگ",
    kind=VIDEO_FILTER,
    why="رنگ‌های پریده یا زیادی تند را به حالت طبیعی می‌برد",
    params=(Param("amount", "میزان", default=1.0, minimum=0.4, maximum=1.8), _FROM, _TO),
    build=lambda p: f"eq=saturation={_f(p['amount'])}",
))

register(Tool(
    key="white_balance",
    title="تعادل رنگ سفید",
    kind=VIDEO_FILTER,
    why="زردی لامپ یا آبی بودن سایه‌ها را می‌گیرد",
    params=(
        Param("temperature", "گرمی/سردی", default=0.0, minimum=-0.3, maximum=0.3),
        _FROM, _TO,
    ),
    # Per-channel gains, not `colorbalance`: on this ffmpeg build colorbalance
    # measurably did nothing to a warm grey (162,139,117 → 162,138,116), so the
    # tool was a no-op the whole time it existed. A positive temperature warms
    # (more red, less blue); the analysis layer hands in the sign that cancels
    # the cast it measured on neutral pixels.
    build=lambda p: (
        f"colorchannelmixer=rr={_f(1 + float(p['temperature']) / 2)}"
        f":bb={_f(1 - float(p['temperature']) / 2)}"
    ),
))

register(Tool(
    key="deflicker",
    title="رفع پرش نور",
    kind=VIDEO_FILTER,
    why="نوسان روشنایی بین فریم‌ها را صاف می‌کند",
    params=(Param("size", "شدت", default=5, minimum=3, maximum=10),),
    build=lambda p: f"deflicker=size={int(p['size'])}",
))

register(Tool(
    key="stabilize",
    title="ثابت‌کردن تصویر",
    kind=VIDEO_FILTER,
    why="لرزش دوربین دستی را می‌گیرد",
    params=(
        Param("smoothing", "میزان نرمی", default=10, minimum=3, maximum=30),
        Param("zoom", "بزرگ‌نمایی برای پر کردن لبه‌ها", default=1, minimum=0, maximum=5),
    ),
    # Two passes really: the detect pass writes a transform file and the
    # executor substitutes its path for STABILIZE_INPUT below. Without
    # `input=` the transform pass looked for `transforms.trf` in the worker's
    # working directory and failed the whole render; the model never sees a
    # path either way.
    build=lambda p: (
        f"vidstabtransform=input=__STABILIZE_INPUT__:smoothing={int(p['smoothing'])}"
        f":zoom={_f(p['zoom'])}:optzoom=1:interpol=bicubic"
    ),
))

STABILIZE_INPUT = "__STABILIZE_INPUT__"

register(Tool(
    key="zoom",
    title="زوم آرام",
    kind=VIDEO_FILTER,
    why="روی جمله یا محصول مهم، تصویر آرام بزرگ می‌شود",
    params=(
        _START, _END,
        Param("scale", "تا چه اندازه", default=1.15, minimum=1.02, maximum=1.6),
    ),
    build=None,  # time-scoped; the executor wraps it in an enable= expression
))

register(Tool(
    key="speed",
    title="سرعت پخش",
    kind=VIDEO_FILTER,
    why="بخش‌های کند را تندتر می‌کند بدون اینکه حذف شوند",
    params=(Param("factor", "چند برابر", default=1.0, minimum=0.5, maximum=3.0),),
    # The executor applies this LAST, after the cut re-stamp (a re-stamp after
    # it silently cancelled the speed change — measured 4.04 s instead of 2 s)
    # and pairs it with `atempo` on the audio, which used to run on unchanged
    # over a frozen final frame.
    build=lambda p: f"setpts=PTS/{_f(max(0.5, float(p['factor'])))}",
    idempotent=False,
))

register(Tool(
    key="crop_format",
    title="تغییر قاب",
    kind=VIDEO_FILTER,
    why="یک ویدیو برای ریلز، استوری و پست، هرکدام با قاب خودش",
    params=(
        Param("format", "قالب", kind="choice",
              choices=("reel", "story", "feed", "square", "wide"), default="reel"),
    ),
    build=None,  # delegated to services.video.repurpose, which owns the maths
))

register(Tool(
    key="denoise_audio",
    title="حذف نویز",
    kind=AUDIO_FILTER,
    why="خش، همهمه، صدای یخچال و خیابان را از پشت صدای شما برمی‌دارد",
    # 12 is the natural setting (strength 1.0); lower keeps more of the room,
    # higher removes more at the risk of an underwater sound.
    params=(Param("amount", "شدت", default=12, minimum=3, maximum=30),),
    # Not a filter string: the executor runs the admin's noise-removal engine
    # (DeepFilterNet → RNNoise → …) as a pre-pass on the audio track and feeds
    # the cleaned track into the same single render as everything else.
    build=None,
    needs_audio=True,
))

register(Tool(
    key="normalize_audio",
    title="یکسان‌کردن بلندی صدا",
    kind=AUDIO_FILTER,
    why="صدای آرام بلند و صدای بلند مهار می‌شود",
    params=(Param("target", "بلندی هدف", default=-18, minimum=-30, maximum=-10),),
    build=lambda p: f"loudnorm=I={_f(p['target'])}:TP=-1.5:LRA=11",
    needs_audio=True,
))

register(Tool(
    key="fade",
    title="محو شدن",
    kind=VIDEO_FILTER,
    why="شروع و پایان ناگهانی را نرم می‌کند",
    params=(
        Param("where", "کجا", kind="choice", choices=("in", "out"), default="in"),
        Param("duration", "چند ثانیه", kind="seconds", default=0.4,
              minimum=0.1, maximum=2.0),
        # -1 means "work it out": a fade-in starts at 0, a fade-out ends at the
        # end of the video. The old default of 0 for BOTH meant a fade-out
        # requested without a time blacked the video from 0.4 s to the end.
        Param("at", "از ثانیه", kind="seconds", default=-1, minimum=-1),
    ),
    build=None,  # the executor resolves `at` against the real duration and cuts
))

# ---------------------------------------------------------------------------
#  §23.4 — the effects the roadmap lists as «کاملاً شدنی با کد» and that were
#  never built: rotate, watermark, transitions, and a privacy blur.
#
#  They are Tools like every other one, which is the point: they go through the
#  same `validate`, get the same clamps, and appear in the same plan a human
#  approves. An "advanced effects" module bolted on beside the toolbox would be
#  a second path to the same filtergraph, and only one of the two would have
#  the safety checks.
# ---------------------------------------------------------------------------

register(Tool(
    key="rotate",
    title="چرخاندن",
    kind=VIDEO_FILTER,
    why="ویدیویی که گوشی افقی گرفته و عمودی ذخیره شده",
    params=(
        Param("degrees", "چند درجه", kind="choice",
              choices=("90", "180", "270"), default="90"),
    ),
    # `transpose` only does quarter turns, which is all a wrongly-oriented
    # phone video ever needs. An arbitrary angle would letterbox the frame and
    # nobody asking to "rotate" a clip means that.
    build=lambda p: {
        "90": "transpose=1",
        "180": "transpose=1,transpose=1",
        "270": "transpose=2",
    }[str(p["degrees"])],
    idempotent=False,
))

register(Tool(
    key="watermark",
    title="واترمارک متنی",
    kind=VIDEO_FILTER,
    why="اسم فروشگاه روی ویدیو می‌ماند وقتی کسی بازنشرش می‌کند",
    params=(
        Param("text", "متن", kind="text", default="", required=True),
        Param("position", "جا", kind="choice",
              choices=("tr", "tl", "br", "bl"), default="br"),
        Param("size", "اندازه (٪ ارتفاع)", default=3.5, minimum=1.5, maximum=8),
        Param("opacity", "شفافیت", default=0.55, minimum=0.1, maximum=1.0),
    ),
    build=lambda p: _watermark(p),
))

register(Tool(
    key="blur_region",
    title="محو کردن یک ناحیه",
    kind=VIDEO_FILTER,
    why="چهره‌ی رهگذر، پلاک ماشین یا آدرسی که نباید در تصویر بماند",
    params=(
        Param("x", "از چپ (٪)", default=0, minimum=0, maximum=100),
        Param("y", "از بالا (٪)", default=0, minimum=0, maximum=100),
        Param("width", "پهنا (٪)", default=25, minimum=2, maximum=100),
        Param("height", "ارتفاع (٪)", default=25, minimum=2, maximum=100),
        Param("strength", "شدت", default=6, minimum=1, maximum=10),
    ),
    # Percentages, not pixels: the plan is built against the proxy and applied
    # to the original, and those are different resolutions. A pixel box would
    # land somewhere else on the final render — the exact class of bug the
    # proxy note in ROADMAP §23.4 warns about.
    build=lambda p: _blur_region(p),
    idempotent=False,
))

register(Tool(
    key="sharpen",
    title="واضح‌تر کردن",
    kind=VIDEO_FILTER,
    why="تصویری که کمی نرم افتاده — نه برای نجات دادن فوکوس اشتباه",
    params=(Param("amount", "شدت", default=0.8, minimum=0.1, maximum=2.0),),
    build=lambda p: f"unsharp=5:5:{_f(p['amount'])}:5:5:0",
    idempotent=False,
))

register(Tool(
    key="vignette",
    title="تیرگی لبه‌ها",
    kind=VIDEO_FILTER,
    why="چشم را به وسط قاب می‌برد، جایی که محصول است",
    params=(Param("strength", "شدت", default=0.4, minimum=0.1, maximum=1.0),),
    # `angle` is what ffmpeg exposes; the number the person picks is mapped
    # onto its usable half rather than handed through raw, because the top of
    # the raw range blacks out most of the frame.
    build=lambda p: f"vignette=angle=PI/{_f(5 - 3 * float(p['strength']))}",
    idempotent=False,
))

register(Tool(
    key="transition",
    title="گذار بین دو برش",
    kind=VIDEO_FILTER,
    why="دو برش پشت‌سرهم پرش دارد؛ محو کوتاه آن را می‌پوشاند",
    params=(
        # -1 = every cut in the plan; a time picks the cut nearest to it.
        Param("at", "ثانیه‌ی گذار", kind="seconds", default=-1, minimum=-1),
        Param("duration", "طول", kind="seconds", default=0.3,
              minimum=0.1, maximum=1.5),
    ),
    # A cross-fade needs two inputs; after a keep-list has been concatenated
    # there is only one stream, so this is a fade-out into a fade-in around the
    # join. The executor derives the pair from the REMOVED spans, each limited
    # to its own window with `enable=` — a bare fade=in blacks every frame
    # before its start and a bare fade=out every frame after its end, and the
    # previous version, multiplying the two, rendered the entire clip black.
    build=None,
    idempotent=False,
))


register(Tool(
    key="subtitle",
    title="زیرنویس",
    kind=OVERLAY,
    why="بیشتر مردم ویدیو را بی‌صدا می‌بینند",
    params=(
        Param("position", "جای زیرنویس", kind="choice",
              choices=("bottom", "middle", "top"), default="bottom"),
        # Percent of the frame height per line. libass reads force_style
        # FontSize in its own 288-line units, so the old default of 42 drew
        # 280-pixel letters on a 1080×1920 reel — the caption covered 40 % of
        # the frame in three wrapped rows.
        Param("size", "اندازه‌ی متن (٪ ارتفاع)", default=5.5, minimum=3, maximum=9),
    ),
    build=None,  # the executor supplies the subtitle file it generated
))


# ------------------------------------------------------------- validation


@dataclass
class Operation:
    """One validated edit. Everything downstream works on these, never on the
    model's raw output."""

    tool: str
    params: dict = field(default_factory=dict)
    reason: str = ""
    #: Set when a value had to be pulled into range. Shown to the human who
    #: approves the plan — a silent clamp makes the edit different from the one
    #: that was described.
    notes: list[str] = field(default_factory=list)

    @property
    def spec(self) -> Tool:
        return TOOLS[self.tool]

    def as_dict(self) -> dict:
        return {
            "tool": self.tool,
            "title": TOOLS[self.tool].title,
            "params": self.params,
            "reason": self.reason,
            "notes": self.notes,
        }


def validate_one(raw: dict, *, duration: float | None = None,
                 has_audio: bool = True) -> Operation:
    """One request from the model → one operation, or a refusal that says why."""
    if not isinstance(raw, dict):
        raise ToolError("هر دستور باید یک شیء باشد")

    key = str(raw.get("tool", "")).strip()
    if key not in TOOLS:
        # Named rather than ignored: a model that invented a tool did not
        # understand the task, and running the rest of its plan as though
        # nothing happened is how an edit does something nobody asked for.
        raise ToolError(
            f"ابزاری به نام «{key}» نداریم. ابزارهای موجود: {'، '.join(sorted(TOOLS))}"
        )
    tool = TOOLS[key]

    if tool.needs_audio and not has_audio:
        raise ToolError(f"«{tool.title}» صدا لازم دارد و این ویدیو صدا ندارد")

    given = raw.get("params")
    given = given if isinstance(given, dict) else {}
    known = {p.name for p in tool.params}
    unknown = set(given) - known
    if unknown:
        raise ToolError(
            f"«{tool.title}» پارامتری به نام {'، '.join(sorted(unknown))} ندارد"
        )

    params, notes = {}, []
    for spec in tool.params:
        if spec.name not in given:
            if spec.required:
                raise ToolError(f"«{tool.title}» بدون «{spec.title}» معنا ندارد")
            params[spec.name] = spec.default
            continue
        value, note = spec.coerce(given[spec.name])
        params[spec.name] = value
        if note:
            notes.append(note)

    operation = Operation(
        tool=key, params=params, reason=str(raw.get("reason", ""))[:300], notes=notes,
    )
    _check_time_range(operation, duration)
    return operation


def _check_time_range(operation: Operation, duration: float | None) -> None:
    """A range has to be inside the video and pointing forwards."""
    params = operation.params
    if "start" not in params or "end" not in params:
        return
    start, end = float(params["start"]), float(params["end"])
    if end <= start:
        raise ToolError(
            f"«{operation.spec.title}»: پایان ({end:g}) باید بعد از شروع ({start:g}) باشد"
        )
    if duration is not None:
        if start >= duration:
            raise ToolError(
                f"«{operation.spec.title}»: ثانیه‌ی {start:g} بعد از پایان ویدیو "
                f"({duration:g} ثانیه) است"
            )
        if end > duration:
            params["end"] = duration
            operation.notes.append(
                f"پایان از {end:g} به {duration:g} (پایان ویدیو) کوتاه شد"
            )


def validate(raw_operations, *, duration: float | None = None,
             has_audio: bool = True) -> tuple[list[Operation], list[str]]:
    """A whole plan. Returns (accepted, refusals).

    One bad operation does not throw the plan away. A model that got nine edits
    right and one wrong should have its nine applied, and the refusal shown next
    to them — discarding all ten teaches nobody anything and leaves the shop
    with an unedited video.
    """
    accepted, refused = [], []
    for raw in (raw_operations or [])[:60]:
        try:
            accepted.append(validate_one(raw, duration=duration, has_audio=has_audio))
        except ToolError as exc:
            refused.append(str(exc))
    return accepted, refused


def catalogue() -> list[dict]:
    """Every tool, for the panel and for the model's prompt."""
    return [TOOLS[key].describe() for key in sorted(TOOLS)]
