from django.test import TestCase

from apps.growth_engine.core.testing import client_for, make_plain_user, make_staff
from apps.panel import registry
from apps.panel.models import PanelPage, PanelSection


class GrowthPanelRegistrationTests(TestCase):
    """The «جذب مشتری» menu section exists, is staff-only, and can be switched off from the Django admin."""

    def setUp(self):
        registry.seed()

    def test_section_and_pages_are_seeded_for_staff_only(self):
        section = PanelSection.objects.get(key="growth")
        self.assertTrue(section.staff_only)
        keys = set(section.pages.values_list("key", flat=True))
        self.assertTrue({"growth_dashboard", "growth_discovery", "growth_leads", "growth_lead"} <= keys)
        self.assertTrue(all(p.staff_only for p in section.pages.all()))

    def test_flags_hide_it_from_ordinary_users(self):
        flags = client_for(make_plain_user()).get("/api/v1/panel/flags/").json()
        self.assertFalse(flags["pages"]["growth_dashboard"])
        flags = client_for(make_staff()).get("/api/v1/panel/flags/").json()
        self.assertTrue(flags["pages"]["growth_dashboard"])

    def test_switching_the_section_off_hides_every_page(self):
        PanelSection.objects.filter(key="growth").update(enabled=False)
        flags = client_for(make_staff()).get("/api/v1/panel/flags/").json()
        self.assertFalse(any(v for k, v in flags["pages"].items() if k.startswith("growth_")))
