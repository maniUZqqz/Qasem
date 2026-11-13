"""The safety layer: limits he can change, a count of what was asked of Instagram (per hour and per day),
and a pause after Instagram says "wait". Pure and small: files in data/, no browser."""
import json
import time
from pathlib import Path

from ig_common import Fail, age_text, fa
from ig_profile import read_json, write_atomic

# name: (default, smallest, biggest)
LIMITS = {
    "posts": (36, 12, 300),           # posts kept per person by the posts job (twelve come with the profile page itself)
    "detail_posts": (5, 1, 12),       # recent posts that get a full read (comments, likers)
    "comments": (20, 0, 200),         # comments kept per post
    "likers": (30, 0, 200),           # people who liked, kept per post
    "highlights": (3, 1, 30),         # highlights whose items are read in one go
    "highlight_items": (50, 1, 100),  # items kept per highlight
    "media_files": (80, 1, 1000),     # pictures and videos fetched in one download job
    "media_file_mb": (80, 1, 500),    # one file bigger than this is skipped
    "media_job_mb": (400, 5, 5000),   # a download job stops after this many megabytes
    "followers": (24, 0, 500),        # followers kept per person
    "following": (24, 0, 500),        # accounts followed, kept per person
    "pause_min": (3, 1, 30),          # seconds between two actions on a page: at least
    "pause_max": (6, 1, 60),          # ... and at most
    "harvest_scroll": (30, 5, 120),   # seconds between two turns of a whole followers list (his order 2026-11-04: «از ۳۰ ثانیه یه بار»)
    "pages_hour": (30, 1, 200),       # pages opened on Instagram per hour
    "pages_day": (150, 1, 1000),      # ... per day
    "scrolls_hour": (40, 1, 400),     # list pages loaded (comments, followers ...) per hour
    "scrolls_day": (200, 1, 2000),    # ... per day
    "cooldown_min": (20, 1, 240),     # minutes of silence after Instagram says "wait"
    "request_check_min": (120, 15, 1440),   # how often a sent follow request is checked (one profile page each time)
    "harvests_hour": (60, 1, 600),    # pages of a whole followers / following list (12 people each) per hour — its own count
    "harvests_day": (1000, 1, 6000),  # ... per day (24,000 followers ≈ 2,000 pages ≈ two days at the defaults)
    "lookups_hour": (300, 1, 1200),   # profiles read the fast way (one request of the page's own profile query, by numeric id) per hour
    "lookups_day": (3000, 1, 12000),  # ... per day
}
DEFAULTS = {k: v[0] for k, v in LIMITS.items()}
HOUR, DAY = 3600, 86400


class Stop(Fail):
    """A job that was not started, or was cut short, by a limit."""


class Budget:
    def __init__(self, root, clock=time.time):
        self.dir, self.clock = Path(root), clock

    # ---- files ----
    def _read(self, name, default):
        # a damaged count must not start again from zero (after a power cut that would let a day's limit be spent twice):
        # its .bak (at most ten minutes old) is read instead
        data = read_json(self.dir / name, default, backup=True)
        return data if isinstance(data, type(default)) else default

    def _write(self, name, data):
        self.dir.mkdir(parents=True, exist_ok=True)
        write_atomic(self.dir / name, json.dumps(data, ensure_ascii=False).encode("utf-8"), backup=True)

    # ---- limits ----
    def limits(self):
        saved = self._read("limits.json", {})
        out = dict(DEFAULTS)
        for key, (_, lo, hi) in LIMITS.items():
            value = saved.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi:
                out[key] = value
        return out

    def set_limits(self, values):
        """Save the given limits; returns (limits, bad) where bad lists the fields that were refused (nothing is saved then)."""
        bad = [k for k, v in values.items() if k not in LIMITS or isinstance(v, bool) or not isinstance(v, int) or not LIMITS[k][1] <= v <= LIMITS[k][2]]
        merged = {**self.limits(), **{k: v for k, v in values.items() if k not in bad}}
        if merged["pause_min"] > merged["pause_max"]:
            bad += [k for k in ("pause_min", "pause_max") if k in values and k not in bad] or ["pause_min"]
        if bad:
            return self.limits(), sorted(set(bad))
        self._write("limits.json", merged)
        return merged, []

    def reset_limits(self):
        (self.dir / "limits.json").unlink(missing_ok=True)
        return dict(DEFAULTS)

    # ---- what was spent ----
    def _state(self):
        state = self._read("budget.json", {})
        cutoff = self.clock() - DAY
        state["events"] = [e for e in state.get("events", []) if isinstance(e, list) and len(e) == 2 and e[0] > cutoff]
        return state

    def spend(self, kind, n=1):
        """Note that n pages ('page') or list pages ('scroll') were asked of Instagram."""
        state = self._state()
        state["events"] += [[round(self.clock(), 1), kind] for _ in range(n)]
        self._write("budget.json", state)

    def used(self, kind, window, state=None):
        cutoff = self.clock() - window
        return sum(1 for ts, k in (state or self._state())["events"] if k == kind and ts > cutoff)

    def check(self, kind, extra=1):
        """Raise Stop when the pause is on or this kind of request has no room left for `extra` more."""
        state, now, lim = self._state(), self.clock(), self.limits()
        until = (state.get("cooldown") or {}).get("until", 0)
        if until > now:
            raise Stop("cooldown", f"اینستاگرام گفته بود صبر کن؛ تا {age_text(until - now)} دیگر هیچ درخواستی نمی‌فرستم.")
        word = {"page": "صفحه‌هایی که باز می‌شود", "harvest": "صفحه‌های خواندن کامل فهرست", "lookup": "پروفایل‌هایی که سریع خوانده می‌شود"}.get(kind, "فهرست‌هایی که ورق زده می‌شود")
        for window, label in ((HOUR, "ساعتی"), (DAY, "روزانه")):
            cap = lim[f"{kind}s_{'hour' if window == HOUR else 'day'}"]
            if self.used(kind, window, state) + extra > cap:
                times = sorted(ts for ts, k in state["events"] if k == kind and ts > now - window)
                wait = max(0, (times[0] + window - now) if times else 0)
                raise Stop("budget", f"سقف {label} {word} پر شده ({fa(cap)} مورد). حدود {age_text(wait)} دیگر جا باز می‌شود؛ می‌توانی سقف را در «محدودیت‌ها» بالا ببری.")

    def free_at(self, kind, extra=1):
        """Epoch seconds when `extra` more of this kind fit in both windows (now if they fit; the cooldown counts too)."""
        state, now, lim = self._state(), self.clock(), self.limits()
        at = max(now, (state.get("cooldown") or {}).get("until", 0))
        for window, cap in ((HOUR, lim[f"{kind}s_hour"]), (DAY, lim[f"{kind}s_day"])):
            times = sorted(ts for ts, k in state["events"] if k == kind and ts > now - window)
            over = len(times) + extra - cap
            if over > 0:
                # the over-th oldest event has to leave the window; more than the cap can never fit, so wait a whole window then
                at = max(at, (times[min(over, len(times)) - 1] if times else now) + window + 1)
        return at

    # ---- the pause after "wait" ----
    def cool(self, reason, minutes=None):
        state = self._state()
        minutes = minutes or self.limits()["cooldown_min"]
        state["cooldown"] = {"until": round(self.clock() + minutes * 60), "reason": reason}
        self._write("budget.json", state)

    def clear_cooldown(self):
        state = self._state()
        state.pop("cooldown", None)
        self._write("budget.json", state)

    def snapshot(self):
        state, now = self._state(), self.clock()
        cool = state.get("cooldown") or {}
        return {"limits": self.limits(), "defaults": dict(DEFAULTS), "ranges": {k: [v[1], v[2]] for k, v in LIMITS.items()},
                "used": {kind: {"hour": self.used(kind, HOUR, state), "day": self.used(kind, DAY, state)} for kind in ("page", "scroll", "harvest", "lookup")},
                "cooldown": {"until": cool["until"], "reason": cool.get("reason", "")} if cool.get("until", 0) > now else None}
