"""A notification must open a page that exists — and the right tab of it.

`NotificationsBell` does `navigate(link)`. Three notifications pointed at
`/stores/<id>/settings`, a route the panel does not have (it renders a blank
page), and the ticket / order / receipt ones opened the *overview* of the sales
section instead of their own tab.

The check below is the guard: every `link=` the backend writes (a literal in any
`notify(...)` call, plus everything `apps.customers.links` can return) is
compared with the routes `frontend/src/features/panel/registry.ts` registers.
A new notification that links to a made-up route fails here, not in front of the
owner.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.stores.models import Store

from . import links
from .models import Conversation, Customer

BACKEND = Path(settings.BASE_DIR)
REGISTRY = BACKEND.parent / "frontend" / "src" / "features" / "panel" / "registry.ts"

#: Routes that exist outside the registry (they are not menu entries).
EXTRA_ROUTES = {"/stores/:id/chat", "/stores/:id/inbox"}


def registered_routes() -> set[str]:
    """`/stores/:id/...` paths from the registry's `to: (id) => \\`...\\`` entries."""
    text = REGISTRY.read_text(encoding="utf-8")
    found = set()
    for template in re.findall(r"to:\s*\(\w+\)\s*=>\s*`([^`]+)`", text):
        found.add(re.sub(r"\$\{[^}]+\}", ":id", template).rstrip("/") or "/")
    return found | EXTRA_ROUTES


def normalise(link: str) -> str:
    """`/stores/3/inbox?c=9` and `/stores/{store.id}/inbox?c={x}` -> `/stores/:id/inbox`."""
    path = link.split("?", 1)[0]
    path = re.sub(r"\{[^}]*\}", ":id", path)
    path = re.sub(r"/\d+(?=/|$)", "/:id", path)
    return path.rstrip("/") or "/"


def source_links() -> list[tuple[str, str]]:
    """Every literal panel route written as `link=...` or returned by `links.py`."""
    pattern = re.compile(r"""\blink\s*=\s*f?["'](/[^"']*)["']""")
    ret_pattern = re.compile(r"""return\s+f?["'](/stores/[^"']*)["']""")
    out = []
    for path in sorted(BACKEND.joinpath("apps").rglob("*.py")):
        name = path.name
        if name.startswith("test") or "migrations" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in pattern.findall(text):
            out.append((str(path.relative_to(BACKEND)), match))
        if name == "links.py":
            for match in ret_pattern.findall(text):
                out.append((str(path.relative_to(BACKEND)), match))
    return out


class NotificationLinkRegistryTests(SimpleTestCase):
    def setUp(self):
        if not REGISTRY.exists():
            self.skipTest("the panel sources are not on this machine")

    def test_every_link_in_the_backend_is_a_registered_panel_route(self):
        routes = registered_routes()
        links_found = source_links()
        self.assertGreaterEqual(len(links_found), 5, "the scan found suspiciously few links")
        stores_links = [(f, link) for f, link in links_found if link.startswith("/stores/")]
        bad = [(f, link) for f, link in stores_links if normalise(link) not in routes]
        self.assertEqual(bad, [], f"links to routes the panel does not have: {bad}")

    def test_the_known_broken_ones_are_gone(self):
        joined = " ".join(link for _f, link in source_links())
        self.assertNotIn("/settings", joined)

    def test_the_scan_really_catches_a_made_up_route(self):
        self.assertNotIn(normalise("/stores/3/settings"), registered_routes())
        self.assertIn(normalise("/stores/3/sales/tickets?x=1"), registered_routes())


class LinkBuilderTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("lnk-owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="فروشگاه")

    def _conversation(self, channel):
        customer = Customer.objects.create(store=self.store, name="م", channel=channel)
        return Conversation.objects.create(store=self.store, customer=customer)

    def test_tabs_not_the_section_overview(self):
        sid = self.store.pk
        self.assertEqual(links.orders_link(sid), f"/stores/{sid}/sales/orders")
        self.assertEqual(links.tickets_link(sid), f"/stores/{sid}/sales/tickets")
        self.assertEqual(links.receipts_link(sid), f"/stores/{sid}/sales/receipts")
        self.assertEqual(links.data_policy_link(sid), f"/stores/{sid}/data")

    def test_a_conversation_link_names_the_conversation(self):
        test_chat = self._conversation("web-test")
        real = self._conversation("telegram")
        self.assertEqual(links.conversation_link(test_chat), f"/stores/{self.store.pk}/chat?c={test_chat.pk}")
        self.assertEqual(links.conversation_link(real), f"/stores/{self.store.pk}/inbox?c={real.pk}")

    def test_every_builder_output_is_a_registered_route(self):
        if not REGISTRY.exists():
            self.skipTest("the panel sources are not on this machine")
        routes = registered_routes()
        sid = self.store.pk
        built = [
            links.orders_link(sid), links.tickets_link(sid), links.receipts_link(sid),
            links.data_policy_link(sid),
            links.conversation_link(self._conversation("web-test")),
            links.conversation_link(self._conversation("telegram")),
        ]
        for link in built:
            self.assertIn(normalise(link), routes, link)
