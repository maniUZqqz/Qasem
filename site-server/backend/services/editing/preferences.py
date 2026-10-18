"""«یاد می‌گیرد چطور ادیت می‌کنی». §9.

§9 describes the goal exactly: a shop that always lowers the colour, always puts
the subtitle high, always cuts pauses over half a second should eventually be
able to say «مثل همیشه ادیت کن» and get that.

Three decisions hold this together.

**Rejections teach more than acceptances.** A shop that turned down the
stabiliser four times has told us something clear; a shop that accepted our
brightness suggestion has mostly told us the suggestion was not annoying.
So a repeatedly-refused tool stops being offered, while a repeatedly-accepted
one only nudges a default.

**A habit needs a handful of examples.** Learning from one edit produces a
system that behaves differently every session for no reason the shop can see,
which is worse than not learning at all. `MIN_EXAMPLES` is the floor, and below
it the platform defaults stand.

**Nothing learned here can invent a value the toolbox would refuse.** Every
learned number goes back through the same `Param.coerce` as a model's output.
A preference table is data a user can edit, and data a user can edit is not
allowed to become a parameter nobody validated.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from .tools import TOOLS

logger = logging.getLogger(__name__)

#: Below this many decisions about one tool, we have a coincidence, not a habit.
MIN_EXAMPLES = 4

#: Refuse a tool this often and we stop offering it. Four out of five is a
#: person telling us plainly; three out of five is a person with a mixed
#: library of videos.
REJECTION_RATE = 0.75

#: Where the learned table lives on the store profile.
KEY = "editing"

#: Defaults, used until a shop has taught us otherwise.
DEFAULTS = {
    "min_silence": 0.6,
    "silence_keep": 0.15,
    "smoothing": 10,
    "audio_target": -18,
    "always_normalize_audio": False,
    "subtitle_position": "bottom",
    "never": [],
    #: The last few sentences of direction this shop gave in DIRECTED mode,
    #: newest last. Shown back to the model so «مثل همیشه» has a referent.
    "directions": [],
}

#: Only decisions a PERSON made teach a habit. AUTO and DIRECTED runs record
#: what the system chose, and counting those as acceptances taught the system
#: its own defaults back as the shop's preference after four runs.
HUMAN_SOURCES = ("MANUAL", "SUGGESTED")

MAX_DIRECTIONS = 5


def habits(store) -> dict:
    """What we have learned about this shop, over the defaults."""
    learned = dict(DEFAULTS)
    if store is None:
        return learned
    try:
        saved = store.profile.ai_preferences.get(KEY)
    except Exception:  # noqa: BLE001 — no profile row, or not a Store
        return learned
    if isinstance(saved, dict):
        learned.update({k: v for k, v in saved.items() if k in DEFAULTS})
    learned["never"] = [t for t in (learned.get("never") or []) if t in TOOLS]
    learned["directions"] = [
        str(d)[:200] for d in (learned.get("directions") or []) if str(d).strip()
    ][-MAX_DIRECTIONS:]
    return learned


def save(store, learned: dict) -> None:
    """Write the table back, keeping every other AI preference intact."""
    if store is None:
        return
    profile = store.profile
    preferences = dict(profile.ai_preferences or {})
    preferences[KEY] = {k: v for k, v in learned.items() if k in DEFAULTS}
    profile.ai_preferences = preferences
    profile.save(update_fields=["ai_preferences"])


def remember_direction(store, instruction: str) -> None:
    """Keep the shop's sentence of direction, so the next one can say «مثل قبل».

    Stored on the habit table rather than derived from decisions: a direction
    is a preference the shop stated outright, not one inferred from counts.
    """
    text = " ".join(str(instruction or "").split())[:200]
    if store is None or not text:
        return
    learned = habits(store)
    directions = [d for d in learned.get("directions", []) if d != text]
    directions.append(text)
    learned["directions"] = directions[-MAX_DIRECTIONS:]
    save(store, learned)


def record(store, *, tool: str, params: dict, accepted: bool, source: str = "SUGGESTED"):
    """Remember one decision about one tool.

    Stored as rows rather than folded straight into the table, because a habit
    derived from counts can be re-derived when the rules change, and a number
    that was averaged into a preference three months ago cannot.
    """
    if store is None or tool not in TOOLS:
        return None
    from apps.content.models import EditDecision

    return EditDecision.objects.create(
        store=store, tool=tool, params=params or {}, accepted=accepted, source=source,
    )


def learn(store) -> dict:
    """Re-derive the habit table from everything this shop has decided."""
    from apps.content.models import EditDecision

    rows = list(
        EditDecision.objects.filter(store=store, source__in=HUMAN_SOURCES)
        .order_by("-created_at")[:400]
    )
    learned = dict(DEFAULTS)
    # Directions are a stated preference, not a derived one; they survive the
    # re-derivation of everything else.
    learned["directions"] = habits(store).get("directions", [])
    if not rows:
        return learned

    by_tool = defaultdict(list)
    for row in rows:
        by_tool[row.tool].append(row)

    never = []
    for tool, decisions in by_tool.items():
        if len(decisions) < MIN_EXAMPLES:
            continue
        refused = sum(1 for d in decisions if not d.accepted)
        if refused / len(decisions) >= REJECTION_RATE:
            never.append(tool)
    learned["never"] = never

    accepted = [row for row in rows if row.accepted]
    learned.update(_numbers_from(accepted))

    normalises = [r for r in by_tool.get("normalize_audio", []) if r.accepted]
    if len(normalises) >= MIN_EXAMPLES:
        learned["always_normalize_audio"] = True

    positions = [
        str(r.params.get("position"))
        for r in by_tool.get("subtitle", []) if r.accepted and r.params.get("position")
    ]
    if len(positions) >= MIN_EXAMPLES:
        learned["subtitle_position"] = max(set(positions), key=positions.count)

    return _sanitise(learned)


def _numbers_from(accepted) -> dict:
    """Median of what they actually chose, for the numbers we keep as defaults.

    Median, not mean: one video edited with an extreme setting should not move
    the default for every video after it, and that single outlier is exactly
    what a mean carries forward.
    """
    wanted = {
        ("trim_silence", "min_silence"): "min_silence",
        ("trim_silence", "keep"): "silence_keep",
        ("stabilize", "smoothing"): "smoothing",
        ("normalize_audio", "target"): "audio_target",
    }
    gathered = defaultdict(list)
    for row in accepted:
        for (tool, param), key in wanted.items():
            if row.tool == tool and isinstance(row.params.get(param), (int, float)):
                gathered[key].append(float(row.params[param]))

    out = {}
    for key, values in gathered.items():
        if len(values) < MIN_EXAMPLES:
            continue
        values.sort()
        middle = len(values) // 2
        out[key] = (
            values[middle] if len(values) % 2
            else (values[middle - 1] + values[middle]) / 2
        )
    return out


def _sanitise(learned: dict) -> dict:
    """Every learned number back through the toolbox's own validation.

    A preference table is data a user can edit. Letting it produce a parameter
    the toolbox would have refused from a model would make the preferences a way
    around the very check that exists to stop bad parameters.
    """
    checks = {
        "min_silence": ("trim_silence", "min_silence"),
        "silence_keep": ("trim_silence", "keep"),
        "smoothing": ("stabilize", "smoothing"),
        "audio_target": ("normalize_audio", "target"),
    }
    for key, (tool_key, param_name) in checks.items():
        if key not in learned:
            continue
        spec = next(p for p in TOOLS[tool_key].params if p.name == param_name)
        try:
            learned[key], _ = spec.coerce(learned[key])
        except Exception:  # noqa: BLE001 — fall back rather than carry rubbish
            learned[key] = DEFAULTS[key]
    learned["directions"] = [
        str(d)[:200] for d in (learned.get("directions") or []) if str(d).strip()
    ][-MAX_DIRECTIONS:]
    return learned


def refresh(store) -> dict:
    """Learn, save, and return the new table."""
    learned = learn(store)
    save(store, learned)
    return learned


def explain(store) -> list[str]:
    """What we think we know, in sentences the shop can disagree with.

    A system that silently behaves differently for one customer is one they
    cannot correct. Saying it out loud is what makes it a preference instead of
    a mystery.
    """
    learned = habits(store)
    lines = []
    if learned["min_silence"] != DEFAULTS["min_silence"]:
        lines.append(
            f"سکوت‌های بیشتر از {learned['min_silence']:g} ثانیه را حذف می‌کنید"
        )
    if learned["always_normalize_audio"]:
        lines.append("همیشه بلندی صدا را یکسان می‌کنید")
    if learned["subtitle_position"] != DEFAULTS["subtitle_position"]:
        place = {"top": "بالای", "middle": "وسط", "bottom": "پایین"}[
            learned["subtitle_position"]
        ]
        lines.append(f"زیرنویس را {place} تصویر می‌گذارید")
    for tool in learned["never"]:
        lines.append(f"«{TOOLS[tool].title}» را معمولاً رد می‌کنید، پس دیگر پیشنهاد نمی‌شود")
    return lines
