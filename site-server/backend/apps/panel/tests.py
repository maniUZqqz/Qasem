from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from . import registry
from .models import PanelFeature, PanelPage, PanelSection


class PanelFlagsTests(TestCase):
    def setUp(self):
        registry.seed()
        U = get_user_model()
        self.user = U.objects.create_user("u", "u@x.io", "pw")
        self.staff = U.objects.create_user("s", "s@x.io", "pw", is_staff=True)

    def test_seed_is_idempotent_and_keeps_state(self):
        n = PanelPage.objects.count()
        PanelPage.objects.filter(key="analytics").update(enabled=False)
        registry.seed()
        self.assertEqual(PanelPage.objects.count(), n)
        self.assertFalse(PanelPage.objects.get(key="analytics").enabled)

    def test_flags_shape_and_cascade(self):
        PanelPage.objects.filter(key="studio").update(enabled=False)
        PanelSection.objects.filter(key="market").update(enabled=False)
        c = APIClient()
        c.force_authenticate(self.user)
        data = c.get("/api/v1/panel/flags/").data
        self.assertFalse(data["pages"]["studio"])
        self.assertFalse(data["features"]["studio.video"], "قابلیتِ صفحهٔ خاموش هم خاموش است")
        self.assertFalse(data["pages"]["competitors"], "صفحهٔ دستهٔ خاموش هم خاموش است")
        self.assertTrue(data["pages"]["analytics"])
        self.assertFalse(data["pages"]["crm"], "صفحهٔ کارکنان برای کاربرِ عادی خاموش است")
        c.force_authenticate(self.staff)
        self.assertTrue(c.get("/api/v1/panel/flags/").data["pages"]["crm"])

    def test_anonymous_rejected(self):
        self.assertIn(APIClient().get("/api/v1/panel/flags/").status_code, (401, 403))

    def test_feature_toggle(self):
        PanelFeature.objects.filter(key="products.onboarding").update(enabled=False)
        c = APIClient()
        c.force_authenticate(self.user)
        data = c.get("/api/v1/panel/flags/").data
        self.assertFalse(data["features"]["products.onboarding"])
        self.assertTrue(data["pages"]["products"])
