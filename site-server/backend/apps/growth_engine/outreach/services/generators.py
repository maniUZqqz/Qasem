"""Message generators: how the body of a message is produced for a lead.

Today there is exactly one, ``placeholder`` (the author's text with ``{city}`` style placeholders filled in).
The registry is the hook for a later AI writer: it registers a generator under its own name, a template names it
in ``MessageTemplate.generator``, and nothing else changes - the system still appends the sender block and the
opt-out line afterwards (see ``rendering.compose``), so a generator cannot drop them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from . import rendering


@dataclass
class Generated:
    body: str
    subject: str = ""
    warnings: list[str] = field(default_factory=list)


class MessageGenerator(Protocol):
    name: str
    label: str

    def generate(self, template, lead) -> Generated: ...


class PlaceholderGenerator:
    name = "placeholder"
    label = "قالبِ ثابت با جاگذار"

    def generate(self, template, lead) -> Generated:
        values = rendering.lead_values(lead)
        body = rendering.render(template.body, values)
        subject = rendering.render(template.subject, values)
        return Generated(body=body.text, subject=subject.text, warnings=[*body.warnings, *[w for w in subject.warnings if w not in body.warnings]])


_REGISTRY: dict[str, MessageGenerator] = {}


def register(generator: MessageGenerator) -> None:
    _REGISTRY[generator.name] = generator


def get(name: str) -> MessageGenerator:
    """The generator called ``name``; an unknown name falls back to ``placeholder`` (never to nothing)."""
    return _REGISTRY.get(name) or _REGISTRY["placeholder"]


def names() -> list[str]:
    return list(_REGISTRY)


register(PlaceholderGenerator())


def build_message(template, lead, settings_obj) -> rendering.BuiltMessage:
    """The final message for ``lead``: generator output + the system's sender block and opt-out line."""
    generated = get(template.generator).generate(template, lead)
    return rendering.compose(generated.body, generated.subject, settings_obj, generated.warnings)
