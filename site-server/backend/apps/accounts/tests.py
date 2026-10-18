from django.contrib.auth.models import User
from rest_framework.test import APITestCase


class AuthFlowTests(APITestCase):
    def test_register_login_me(self):
        resp = self.client.post(
            "/api/v1/auth/register/",
            {"username": "shopowner", "email": "owner@example.com", "password": "Str0ngPass!x"},
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(User.objects.filter(username="shopowner").exists())

        resp = self.client.post(
            "/api/v1/auth/login/", {"username": "shopowner", "password": "Str0ngPass!x"}
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        access = resp.data["access"]
        self.assertIn("refresh", resp.data)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = self.client.get("/api/v1/auth/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["username"], "shopowner")

    def test_me_requires_auth(self):
        resp = self.client.get("/api/v1/auth/me/")
        self.assertEqual(resp.status_code, 401)

    def test_weak_password_rejected(self):
        resp = self.client.post(
            "/api/v1/auth/register/", {"username": "weakuser", "password": "123"}
        )
        self.assertEqual(resp.status_code, 400)
