"""The director's vocabulary: what a tool is, how its parameters are checked, and what a tool may ask of the world.

A **tool call** is `{"tool": "<name>", "params": {...}, "why": "<one Persian sentence>"}`. A **plan** is a list of them. The
catalogue (`tools.TOOLS`) is *exactly the timeline operations the manual editor has*, so whatever the director does, a person
can open the result in the manual workspace and change it with the same operations.

Parameters are validated here, once, and never trusted afterwards: unknown names are dropped, numbers are clamped to the
declared range (with a note, not an error), choices must be one of the declared keys, and a required parameter that is
missing makes the *step* fail with a Persian sentence — never the whole plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

KINDS = ("num", "int", "bool", "choice", "text", "ref", "clip", "list")


@dataclass
class Param:
    name: str
    title: str                     # Persian label shown in the plan editor
    kind: str = "num"
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    required: bool = False
    doc: str = ""                  # English one-liner for the model's catalogue
    unit: str = ""
    max_len: int = 200

    def as_dict(self) -> dict:
        out = {"name": self.name, "title": self.title, "kind": self.kind, "required": self.required, "unit": self.unit}
        if self.default is not None:
            out["default"] = self.default
        if self.minimum is not None:
            out["min"] = self.minimum
        if self.maximum is not None:
            out["max"] = self.maximum
        if self.choices:
            out["choices"] = list(self.choices)
        return out


@dataclass
class ToolSpec:
    name: str
    title: str                     # Persian
    group: str                     # structure | text | visual | audio
    params: tuple[Param, ...]
    does: str                      # English one-liner for the model
    describe: Callable[[dict], str]   # Persian sentence of one step, from CLEAN params
    fn: Callable | None = None

    def as_dict(self) -> dict:
        return {"tool": self.name, "title": self.title, "group": self.group, "does": self.does,
                "params": [p.as_dict() for p in self.params]}

    def for_model(self) -> dict:
        """The compact entry the planning model sees."""
        out: dict = {}
        for p in self.params:
            entry: dict = {"type": p.kind}
            if p.minimum is not None:
                entry["min"] = p.minimum
            if p.maximum is not None:
                entry["max"] = p.maximum
            if p.choices:
                entry["choices"] = list(p.choices)
            if p.default is not None:
                entry["default"] = p.default
            if p.required:
                entry["required"] = True
            if p.doc:
                entry["doc"] = p.doc
            out[p.name] = entry
        return {"tool": self.name, "does": self.does, "params": out}


class StepError(Exception):
    """A step that cannot run; the message is Persian and is shown to the owner next to that step."""


def clean_params(spec: ToolSpec, raw: Any) -> tuple[dict, list[str]]:
    """raw params → (clean, notes). Raises `StepError` for a missing/invalid required value."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    notes: list[str] = []
    for p in spec.params:
        value = raw.get(p.name, None)
        if value is None or value == "":
            if p.required and p.default is None:
                raise StepError(f"«{p.title}» لازم است.")
            if p.default is not None:
                out[p.name] = p.default
            continue
        try:
            if p.kind in ("num", "int"):
                if isinstance(value, bool):
                    raise ValueError
                x = float(value)
                if x != x:
                    raise ValueError
                if p.minimum is not None and x < p.minimum:
                    x = p.minimum
                    notes.append(f"«{p.title}» به کمینهٔ مجاز رسید.")
                if p.maximum is not None and x > p.maximum:
                    x = p.maximum
                    notes.append(f"«{p.title}» به بیشینهٔ مجاز رسید.")
                out[p.name] = int(round(x)) if p.kind == "int" else round(x, 4)
            elif p.kind == "bool":
                out[p.name] = value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on", "بله")
            elif p.kind == "choice":
                v = str(value).strip()
                if v not in p.choices:
                    low = {c.lower(): c for c in p.choices}
                    if v.lower() in low:
                        v = low[v.lower()]
                    elif p.default is not None and not p.required:
                        notes.append(f"«{p.title}»: «{v}» شناخته نشد؛ پیش‌فرض به کار رفت.")
                        v = p.default
                    else:
                        raise StepError(f"«{p.title}» باید یکی از {'، '.join(p.choices)} باشد.")
                out[p.name] = v
            elif p.kind in ("text", "ref", "clip"):
                out[p.name] = str(value).strip()[: p.max_len]
            elif p.kind == "list":
                if not isinstance(value, (list, tuple)):
                    raise ValueError
                out[p.name] = list(value)[:60]
        except (TypeError, ValueError):
            raise StepError(f"مقدارِ «{p.title}» درست نیست.") from None
    return out, notes


@dataclass
class Ctx:
    """What a tool may ask of the world. Every member is optional and injectable (tests pass fakes; the web layer passes
    store-scoped implementations from `director.ctx`)."""

    #: ref → {"ref","title","kind":"video|audio|image","duration","has_audio","width","height"} or None
    describe: Callable[[str], dict | None] = lambda ref: None
    #: ref → [[start, end], …] where somebody speaks, in SOURCE seconds
    spans: Callable[[str], list] = lambda ref: []
    #: ref → {"beats": [seconds], "bpm": float|None}
    beats: Callable[[str], dict] = lambda ref: {"beats": [], "bpm": None}
    #: (ref, start, end) → [{"w","s","e"}] ASR words in SOURCE seconds, or raises/returns [] when ASR is unavailable
    words: Callable[[str, float, float], list] = lambda ref, a, b: []
    #: ref → local file path (for looking at pixels) or None
    path_of: Callable[[str], str | None] = lambda ref: None
    #: (text, voice) → audio ref "audio:<id>" (generates it), raising StepError with a Persian reason when impossible
    make_speech: Callable[[str, str], str] | None = None
    #: query → audio ref of a music track the shop has (or None)
    find_music: Callable[[str], str | None] = lambda query: None
    #: (ref, start, end) → {p5, p50, p95, clip_hi, cast_rb, cast_measurable, faces} of that stretch of a video, or {} when it cannot be measured
    look_stats: Callable[[str, float, float], dict] = lambda ref, a, b: {}
    #: (target from `music_match.target_for`, seconds the video needs) → library tracks best-first [{ref, title, score, why, bpm, duration}]
    rank_music: Callable[[dict, float], list] = lambda target, seconds: []
    #: (ref, start, end) → {"key", "s0", …}: the subject of that stretch of a video cut out (background removal) by the processing server, kept as a
    #: matte the clips can point at; raises StepError («در صف …» while the server is only off).  None where it cannot be done (tests, no node)
    make_matte: Callable[[str, float, float], dict] | None = None
    #: ref → `letterbox.detect()` of a video: where the real picture is inside black bars (`found`, `box`, `aspect`, `portrait`), {} when it cannot be told
    content_box: Callable[[str], dict] = lambda ref: {}
    #: the project's frame aspect etc. are read from the project itself; this is only the store (None in tests)
    store: Any = None
    #: Persian sentences about what was skipped or degraded (shown to the owner)
    notes: list[str] = field(default_factory=list)
