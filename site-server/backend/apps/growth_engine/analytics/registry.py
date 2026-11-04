"""Dashboard extension point.

A module that has numbers for the Growth Dashboard registers a function here (usually from its
``AppConfig.ready``). The dashboard calls every provider and returns the results under
``extra[<name>]``, so the analytics package never imports the modules that feed it.

A provider takes no arguments and returns plain JSON-able data computed from the database -
never an estimate or a placeholder.
"""
from __future__ import annotations

from collections.abc import Callable

_PROVIDERS: dict[str, Callable[[], dict]] = {}


def register(name: str, provider: Callable[[], dict]) -> None:
    _PROVIDERS[name] = provider


def collect() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name, provider in _PROVIDERS.items():
        try:
            out[name] = provider()
        except Exception:  # noqa: BLE001 - one broken block must not blank the whole dashboard
            import logging

            logging.getLogger(__name__).exception("growth dashboard provider %s failed", name)
            out[name] = {"error": True}
    return out
