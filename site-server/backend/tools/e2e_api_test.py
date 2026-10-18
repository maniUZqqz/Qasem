"""
End-to-end drive of the REAL HTTP API against the fake model stack.

`manage.py selftest` proves the AI pipelines survive a misbehaving model, but
it calls the Celery tasks directly. This script instead does what the browser
does: it logs in over HTTP and walks every screen of the product — stores,
products, intelligence, market research, image studio, captions, video script,
video, voice-over, sales chat with orders/receipts/tickets, notifications,
campaigns, n8n publishing and analytics — against a live Django server.

Nothing touches the developer's data: a throwaway SQLite file and media folder
are created in a temp directory and deleted afterwards.

    python tools/e2e_api_test.py            # synchronous mode (no Redis needed)
    python tools/e2e_api_test.py --queue    # real Redis + two Celery workers
    python tools/e2e_api_test.py --keep     # keep the temp dir for inspection
"""

import argparse
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from tools import fake_ai_stack  # noqa: E402

PASS, FAIL = "✓", "✗"


# --------------------------------------------------------------------------- utils
def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_port(port: int, timeout: float = 60.0, host: str = "127.0.0.1") -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


class Failure(Exception):
    pass


def check(condition, message):
    if not condition:
        raise Failure(message)


def png_bytes(width=640, height=480, color=(40, 90, 160)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------- fake n8n
class FakeN8N(BaseHTTPRequestHandler):
    """Records every publish payload so delivery can actually be asserted."""

    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {"unparsed": raw[:200].decode("utf-8", "replace")}
        self.received.append({"payload": payload, "token": self.headers.get("X-Upmarket-Token")})
        body = json.dumps({"ok": True, "id": len(self.received)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


# --------------------------------------------------------------------------- client
class Api:
    """Thin API client that behaves like the frontend (JWT + /api/v1 base)."""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.session = requests.Session()
        self.token = None

    def request(self, method, path, *, expect=None, **kwargs):
        url = f"{self.base}/api/v1{path}"
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = self.session.request(method, url, headers=headers, timeout=900, **kwargs)
        if expect is not None:
            allowed = expect if isinstance(expect, (list, tuple, set)) else [expect]
            if response.status_code not in allowed:
                raise Failure(
                    f"{method} {path} -> {response.status_code} (expected {allowed}): "
                    f"{response.text[:300]}"
                )
        return response

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def patch(self, path, **kw):
        return self.request("PATCH", path, **kw)

    def put(self, path, **kw):
        return self.request("PUT", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    #: States in which a job is parked until a person looks at the preview.
    AWAITING_HUMAN = {"PREVIEW", "WAITING_APPROVAL"}

    def wait_job(self, job_id, timeout=900, approve=False):
        """Poll a job exactly like useJobRunner does, until it is terminal.

        `approve=True` plays the owner's part too. Video jobs default to SAFE
        mode: they render one segment, park, and wait for somebody to approve it
        before spending GPU time on the next. This test predates that, so it sat
        polling a parked job for its whole 30-minute timeout and then reported
        "never finished" — a failure that said nothing about the product and
        cost half an hour on every launcher self-check. Approving here is what
        the panel's «ادامه بده» button does, so the park → approve → resume path
        is now exercised instead of tripped over. `self.approvals` counts them.
        """
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = self.get(f"/jobs/{job_id}/", expect=200).json()
            if last["state"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                return last
            if last["state"] in self.AWAITING_HUMAN:
                if not approve:
                    raise Failure(
                        f"job {job_id} is parked for approval ({last['state']}) and this step "
                        "does not approve — it would have waited out the whole timeout"
                    )
                self.post(f"/jobs/{job_id}/approve/", expect=200)
                self.approvals = getattr(self, "approvals", 0) + 1
            time.sleep(0.5)
        raise Failure(f"job {job_id} never finished (last state {last and last['state']})")

    def run_job(self, path, payload=None, *, timeout=900):
        """POST an action that returns 202 {job_id} and wait for completion."""
        response = self.post(path, json=payload or {}, expect=202)
        job = self.wait_job(response.json()["job_id"], timeout=timeout)
        check(job["state"] == "COMPLETED", f"{path}: job {job['state']} — {job['error'][:200]}")
        return job


# --------------------------------------------------------------------------- scenario
class Scenario:
    """Every screen of the product, driven over HTTP in the order a user would."""

    def __init__(self, api: Api, base: str, queue_mode: bool, stop_fakes=None):
        self.api = api
        self.base = base
        self.queue_mode = queue_mode
        # lets the outage step pull the plug on Ollama/ComfyUI mid-run
        self.stop_fakes = stop_fakes or (lambda: None)
        self.state = {}

    # ---------------------------------------------------------------- auth
    def auth(self):
        api = self.api
        api.post(
            "/auth/register/",
            json={"username": "e2e_owner", "password": "e2e-Pass-4321", "email": "e2e@example.com"},
            expect=201,
        )
        tokens = api.post(
            "/auth/login/", json={"username": "e2e_owner", "password": "e2e-Pass-4321"}, expect=200
        ).json()
        check("access" in tokens and "refresh" in tokens, "login did not return a token pair")
        api.token = tokens["access"]
        me = api.get("/auth/me/", expect=200).json()
        check(me["username"] == "e2e_owner", f"/auth/me returned {me}")
        refreshed = api.post(
            "/auth/refresh/", json={"refresh": tokens["refresh"]}, expect=200
        ).json()
        check("access" in refreshed, "refresh did not return a new access token")

        api.token = None
        api.get("/stores/", expect=401)
        api.token = tokens["access"]
        return "ثبت‌نام، ورود، refresh، و رد درخواست بدون توکن"

    # ---------------------------------------------------------------- store
    def store(self):
        api = self.api
        store = api.post(
            "/stores/",
            json={
                "name": "تک‌لند",
                "business_type": "لوازم جانبی صوتی",
                "description": "فروشگاه آنلاین هدفون و اسپیکر",
                "target_audience": "جوانان ۲۰ تا ۳۵ سال",
                "contact": {"phone": "0912xxxxxxx"},
                "social_links": {"instagram": "@tekland"},
            },
            expect=201,
        ).json()
        self.state["store"] = store["id"]
        check(bool(store["slug"]), "store got no slug")

        listed = api.get("/stores/", expect=200).json()
        check(listed["count"] == 1, f"store list count = {listed['count']}")

        profile = api.get(f"/stores/{store['id']}/profile/", expect=200).json()
        check("payment_info" in profile, "profile serializer is missing payment_info")
        saved = api.put(
            f"/stores/{store['id']}/profile/",
            json={
                "brand_voice": "صمیمی و حرفه‌ای",
                "tone": "دوستانه",
                "shipping_policy": "ارسال رایگان بالای ۵۰۰ هزار تومان",
                "return_policy": "۷ روز ضمانت بازگشت",
                "refund_policy": "بازگشت وجه تا ۴۸ ساعت",
                "payment_info": "کارت ۶۰۳۷-۹۹۷۵-xxxx-xxxx به نام تک‌لند",
                "business_rules": "قیمت‌ها نهایی است",
            },
            expect=200,
        ).json()
        check(saved["payment_info"].startswith("کارت"), "payment_info was not stored")

        api.patch(f"/stores/{store['id']}/", json={"target_audience": "دانشجو و کارمند"}, expect=200)
        return f"فروشگاه #{store['id']} + پروفایل برند و سیاست‌ها"

    # ---------------------------------------------------------------- catalog
    def catalog(self):
        api, store_id = self.api, self.state["store"]
        category = api.post(
            "/categories/", json={"store": store_id, "name": "هدفون"}, expect=201
        ).json()
        product = api.post(
            "/products/",
            json={
                "store": store_id,
                "category": category["id"],
                "name": "هدفون بی‌سیم TK-900",
                "brand": "TekLand",
                "price": "2450000",
                "compare_at_price": "2900000",
                "stock_quantity": 12,
                "description": "هدفون بلوتوثی با نویز کنسلینگ فعال و باتری ۴۰ ساعته",
                "short_description": "صدای شفاف، باتری ۴۰ ساعته",
                "tags": ["هدفون", "بلوتوث"],
            },
            expect=201,
        ).json()
        self.state["product"] = product["id"]

        second = api.post(
            "/products/",
            json={
                "store": store_id,
                "name": "اسپیکر بلوتوثی TK-200",
                "price": "980000",
                "stock_quantity": 4,
                "description": "اسپیکر قابل حمل ضدآب",
            },
            expect=201,
        ).json()
        self.state["product2"] = second["id"]

        api.post(
            f"/products/{product['id']}/attributes/",
            json={"key": "باتری", "value": "۴۰ ساعت"},
            expect=201,
        )
        api.post(
            f"/products/{product['id']}/variants/",
            json={"name": "مشکی", "stock_quantity": 5},
            expect=201,
        )

        image = api.post(
            f"/products/{product['id']}/images/",
            files={"image": ("product.png", png_bytes(), "image/png")},
            data={"is_main": "true"},
            expect=201,
        ).json()
        self.state["image"] = image["id"]

        # uploads are untrusted input: bytes that are not an image must be refused
        api.post(
            f"/products/{product['id']}/images/",
            files={"image": ("evil.png", b"not really an image", "image/png")},
            expect=400,
        )
        api.post(
            f"/products/{product['id']}/images/",
            files={"image": ("script.svg", b"<svg/>", "image/svg+xml")},
            expect=400,
        )

        extra = api.post(
            f"/products/{product['id']}/images/",
            files={"image": ("second.png", png_bytes(320, 320, (200, 60, 60)), "image/png")},
            expect=201,
        ).json()
        api.delete(f"/products/{product['id']}/images/{extra['id']}/", expect=204)

        detail = api.get(f"/products/{product['id']}/", expect=200).json()
        check(len(detail["images"]) == 1, f"expected 1 image, got {len(detail['images'])}")
        check(len(detail["attributes"]) == 1, "attribute was not saved")
        check(len(detail["variants"]) == 1, "variant was not saved")

        api.patch(f"/products/{product['id']}/", json={"stock_quantity": 20}, expect=200)
        listed = api.get(f"/products/?store={store_id}", expect=200).json()
        check(listed["count"] == 2, f"product list count = {listed['count']}")
        return "۲ محصول، دسته، ویژگی، واریانت، آپلود/حذف عکس + رد فایل جعلی"

    # ---------------------------------------------------------------- tenancy
    def tenancy(self):
        api = self.api
        other = Api(self.base)
        other.post(
            "/auth/register/",
            # The email is not decoration: registration made it mandatory when
            # password reset was built, because an account with no address has
            # no way back in. This call was written before that and silently
            # started failing the whole tenancy step.
            json={
                "username": "e2e_intruder",
                "password": "e2e-Pass-9876",
                "email": "e2e-intruder@example.com",
            },
            expect=201,
        )
        other.token = other.post(
            "/auth/login/",
            json={"username": "e2e_intruder", "password": "e2e-Pass-9876"},
            expect=200,
        ).json()["access"]

        check(other.get("/stores/", expect=200).json()["count"] == 0, "intruder sees other stores")
        check(
            other.get("/products/", expect=200).json()["count"] == 0,
            "intruder sees other products",
        )
        store_id, product_id = self.state["store"], self.state["product"]
        for path in (
            f"/stores/{store_id}/",
            f"/products/{product_id}/",
            f"/products/{product_id}/intelligence/",
            f"/products/{product_id}/captions/",
            f"/stores/{store_id}/analytics/",
        ):
            other.get(path, expect=404)
        other.post(f"/products/{product_id}/analyze/", expect=404)
        other.post(f"/stores/{store_id}/chat/", json={"message": "سلام"}, expect=404)

        check(api.get("/stores/", expect=200).json()["count"] == 1, "owner lost their store")
        return "کاربر دوم هیچ‌کدام از داده‌های فروشگاه اول را نمی‌بیند (۷ مسیر)"

    # ---------------------------------------------------------------- intelligence
    def intelligence(self):
        api, product_id = self.api, self.state["product"]
        empty = api.get(f"/products/{product_id}/intelligence/", expect=200)
        check(empty.json() is None, "un-analysed product must answer 200 + null, not 404")

        api.run_job(f"/products/{product_id}/analyze/")
        data = api.get(f"/products/{product_id}/intelligence/", expect=200).json()
        check(data is not None, "intelligence still empty after the job completed")
        for field in ("target_audience", "selling_points", "objections", "marketing_angles"):
            check(len(data[field]) >= 1, f"{field} is empty")
        check(len(data["visual_analysis"]) == 1, "the product photo was not analysed")
        check(bool(data["positioning"]), "positioning missing")
        return f"{len(data['selling_points'])} نقطه قوت، {len(data['visual_analysis'])} تحلیل بصری"

    def market(self):
        api, product_id = self.api, self.state["product"]
        empty = api.get(f"/products/{product_id}/market-analysis/", expect=200)
        check(empty.json() is None, "un-researched product must answer 200 + null")

        api.run_job(
            f"/products/{product_id}/market-analysis/",
            {"research_inputs": "رقیب: AudioX AX-7 — ۲٬۱۰۰٬۰۰۰ تومان در دیجی‌کالا"},
        )
        data = api.get(f"/products/{product_id}/market-analysis/", expect=200).json()
        check(data is not None, "market research row missing")
        competitors = data["conclusions"].get("competitors") or []
        check(len(competitors) >= 1, "no competitors in the conclusions")
        check(len(data["conclusions"].get("comparison") or []) >= 1, "no comparison lines")
        check(data["confidence"] in {"LOW", "MEDIUM", "HIGH"}, "bad confidence")
        return f"{len(competitors)} رقیب، اطمینان {data['confidence']}"

    # ---------------------------------------------------------------- image studio
    def image_studio(self):
        api, product_id = self.api, self.state["product"]
        check(
            api.get(f"/products/{product_id}/image-studio/", expect=200).json() == [],
            "image studio should start empty",
        )
        api.post(f"/products/{product_id}/image-studio/", json={"kind": "NOPE"}, expect=400)

        made = {}
        for kind, style in (
            ("POSTER", "مینیمال"),
            ("PRODUCT_SHOT", "اینستاگرامی"),
            ("ENHANCED", ""),
        ):
            api.run_job(
                f"/products/{product_id}/image-studio/",
                {"kind": kind, "style": style, "source_image_id": self.state["image"]},
            )
            made[kind] = True

        images = api.get(f"/products/{product_id}/image-studio/", expect=200).json()
        check(len(images) == 3, f"expected 3 generated images, got {len(images)}")
        by_kind = {item["kind"]: item for item in images}
        check(set(by_kind) == set(made), f"kinds generated: {sorted(by_kind)}")

        poster = by_kind["POSTER"]
        check(
            poster["workflow_version"] == "flux_img_edit@v1",
            f"poster must edit the real photo, used {poster['workflow_version']}",
        )
        overlay = (poster.get("metadata") or {}).get("text_overlay") or {}
        check(bool(overlay.get("headline")), "no Persian headline drawn on the poster")
        check(
            any(digit in overlay.get("badge", "") for digit in "۰۱۲۳۴۵۶۷۸۹"),
            f"price badge is not in Persian digits: {overlay.get('badge')!r}",
        )

        # the file must be downloadable exactly as the browser asks for it
        served = requests.get(poster["image"], timeout=60)
        check(served.status_code == 200, f"poster media URL -> {served.status_code}")
        check(len(served.content) > 2000, "poster file served but nearly empty")
        self.state["poster"] = poster["id"]
        return f"۳ تصویر ({', '.join(sorted(by_kind))})، پوستر با «{overlay['headline']}»"

    # ---------------------------------------------------------------- captions
    def captions(self):
        api, product_id = self.api, self.state["product"]
        check(api.get(f"/products/{product_id}/captions/", expect=200).json() == [], "not empty")

        api.post(
            f"/products/{product_id}/captions/",
            json={"platforms": ["INSTAGRAM"], "image_id": 999999},
            expect=400,
        )
        api.post(
            f"/products/{product_id}/captions/",
            json={"platforms": ["INSTAGRAM"], "video_script_id": 999999},
            expect=400,
        )

        api.run_job(
            f"/products/{product_id}/captions/",
            {
                "platforms": ["INSTAGRAM", "TELEGRAM", "LINKEDIN"],
                "tone": "دوستانه",
                "image_id": self.state["poster"],
            },
        )
        captions = api.get(f"/products/{product_id}/captions/", expect=200).json()
        check(len(captions) == 3, f"expected 3 captions, got {len(captions)}")
        for caption in captions:
            check(
                caption["short_text"] and caption["medium_text"] and caption["long_text"],
                f"{caption['platform']}: an empty caption length",
            )
            check(bool(caption["cta"]), f"{caption['platform']}: no CTA")
            check(
                caption["about_image"] == self.state["poster"],
                "caption is not linked to the poster it was written for",
            )
        self.state["caption"] = captions[0]["id"]
        return f"{len(captions)} پلتفرم، هر کدام ۳ طول + CTA، متصل به پوستر"

    # ---------------------------------------------------------------- video
    def video_script(self):
        api, product_id = self.api, self.state["product"]
        empty = api.get(f"/products/{product_id}/video-script/", expect=200)
        check(empty.json() is None, "no script yet must be 200 + null, not 404")

        api.run_job(
            f"/products/{product_id}/video-script/",
            {"duration": 15, "objective": "فروش مستقیم", "language": "fa"},
        )
        script = api.get(f"/products/{product_id}/video-script/", expect=200).json()
        check(script is not None, "script row missing")
        check(len(script["scenes"]) == 3, f"expected 3 scenes, got {len(script['scenes'])}")
        check(script["narration_language"] == "fa", "narration language not stored")
        for scene in script["scenes"]:
            check(bool(scene["visual_prompt"]), f"scene {scene['index']} has no visual prompt")
            check(bool(scene["narration"]), f"scene {scene['index']} has no narration")
        self.state["script"] = script["id"]
        return f"{len(script['scenes'])} صحنه، CTA: «{script['cta'][:26]}»"

    def video_render(self):
        api, script_id = self.api, self.state["script"]
        if not self.queue_mode:
            response = api.post(f"/video-scripts/{script_id}/generate/", expect=503)
            body = response.json()["error"]
            check(body["code"] == "queue_unavailable", f"unexpected error code {body['code']}")
            check("Redis" in body["message"], "the 503 must name Redis so the user can act")
            return "بدون صف: ۵۰۳ با پیام روشن فارسی (طبق طراحی)"

        # double click: the second POST must be refused, not queue a twin run
        first = api.post(f"/video-scripts/{script_id}/generate/", expect=202).json()
        second = api.post(f"/video-scripts/{script_id}/generate/", expect=[202, 409])
        check(
            second.status_code == 409,
            "a second 'generate video' click queued a duplicate render",
        )
        check(
            second.json()["error"]["code"] == "already_running",
            f"unexpected duplicate-click error: {second.json()}",
        )
        # SAFE is the default mode, so this job parks after each segment; the
        # test approves like an owner would and insists that it really had to.
        api.approvals = 0
        job = api.wait_job(first["job_id"], timeout=1800, approve=True)
        check(job["state"] == "COMPLETED", f"video job {job['state']} — {job['error'][:200]}")
        check(
            api.approvals >= 1,
            "the video job never parked for approval — SAFE mode is supposed to be the default",
        )

        script = api.get(f"/products/{self.state['product']}/video-script/", expect=200).json()
        check(script["status"] == "READY", f"script status is {script['status']}")
        check(bool(script["final_video"]), "no final video URL")
        segments = script["segments"]
        check(len(segments) == 3, f"expected 3 segments, got {len(segments)}")
        for segment in segments:
            check(segment["status"] == "DONE", f"segment {segment['index']}: {segment['error']}")
            check(bool(segment["last_frame"]), f"segment {segment['index']}: no last frame")
        served = requests.get(script["final_video"], timeout=120)
        check(served.status_code == 200, f"final video URL -> {served.status_code}")
        check(len(served.content) > 1000, "final video is empty")

        # Re-running must NOT regenerate segments that are already DONE
        # (rule 8: never redo successful GPU work). Their rows must be untouched.
        before = {segment["index"]: segment["updated_at"] for segment in segments}
        rerun = api.post(f"/video-scripts/{script_id}/generate/", expect=[202, 409])
        check(rerun.status_code == 202, "re-running a finished video was refused")
        api.wait_job(rerun.json()["job_id"], timeout=1800, approve=True)
        after_script = api.get(
            f"/products/{self.state['product']}/video-script/", expect=200
        ).json()
        after = {segment["index"]: segment["updated_at"] for segment in after_script["segments"]}
        check(
            before == after,
            f"finished segments were regenerated on re-run: {before} -> {after}",
        )
        return (
            f"{len(segments)} قطعه + final.mp4 ({len(served.content) // 1024}KB)، "
            "کلیک دوم ۴۰۹، اجرای مجدد قطعات آماده را دوباره نساخت"
        )

    def voice(self):
        api, script_id = self.api, self.state["script"]
        if not self.queue_mode:
            api.post(f"/video-scripts/{script_id}/voice/", expect=400)
            return "بدون ویدیوی نهایی: ۴۰۰ «اول ویدیو را بسازید» (طبق طراحی)"

        job = api.post(f"/video-scripts/{script_id}/voice/", expect=202).json()
        finished = api.wait_job(job["job_id"], timeout=900)
        if finished["state"] == "FAILED":
            # edge-tts needs the internet; that is an environment limit, not a bug
            check(
                "tts" in finished["error"].lower() or "edge" in finished["error"].lower(),
                f"voice failed for a non-TTS reason: {finished['error'][:200]}",
            )
            return f"TTS در دسترس نبود (اینترنت لازم است): {finished['error'][:60]}"
        script = api.get(f"/products/{self.state['product']}/video-script/", expect=200).json()
        check(bool(script["final_video_voiced"]), "voiced video URL missing")
        served = requests.get(script["final_video_voiced"], timeout=120)
        check(served.status_code == 200, f"voiced video URL -> {served.status_code}")
        return f"ویدیوی صدادار ({len(served.content) // 1024}KB)"

    # ---------------------------------------------------------------- sales chat
    def chat(self):
        api, store_id = self.api, self.state["store"]
        api.post(f"/stores/{store_id}/chat/", json={"message": "  "}, expect=400)

        first = api.post(
            f"/stores/{store_id}/chat/",
            json={"message": "سلام، قیمت هدفون چنده؟", "customer_name": "رضا"},
            expect=200,
        ).json()
        conversation_id = first["conversation_id"]
        check(bool(first["message"]["text"]), "empty AI reply")
        check(first["action"] == "ANSWER", f"unexpected action {first['action']}")
        self.state["conversation"] = conversation_id

        ordered = api.post(
            f"/stores/{store_id}/chat/",
            json={"message": "همینو می‌خرم، سفارش بده", "conversation_id": conversation_id},
            expect=200,
        ).json()
        check(ordered["order"] is not None, f"no order created: {ordered.get('order_error')}")
        order_id = ordered["order"]["id"]
        self.state["order"] = order_id
        check(ordered["order"]["status"] == "DRAFT", f"order status {ordered['order']['status']}")

        pay = api.post(
            f"/stores/{store_id}/chat/",
            json={"message": "چطور پرداخت کنم؟", "conversation_id": conversation_id},
            expect=200,
        ).json()
        check(pay["payment_request"] is not None, "no payment request returned")
        check(
            "کارت" in pay["payment_request"]["payment_info"],
            "payment info did not come from the store profile",
        )

        messages = api.get(f"/conversations/{conversation_id}/messages/", expect=200).json()
        check(len(messages) == 6, f"expected 6 stored messages, got {len(messages)}")

        conversations = api.get(f"/stores/{store_id}/conversations/", expect=200).json()
        check(conversations["count"] == 1, f"conversation list = {conversations['count']}")
        return f"۳ نوبت گفتگو، سفارش #{order_id}، درخواست پرداخت از پروفایل"

    def payment_flow(self):
        api, order_id = self.api, self.state["order"]
        orders = api.get(f"/stores/{self.state['store']}/orders/", expect=200).json()
        check(orders["count"] == 1, f"order list = {orders['count']}")
        check(
            orders["results"][0]["status"] == "AWAITING_RECEIPT",
            f"order should await a receipt, is {orders['results'][0]['status']}",
        )

        api.post(
            f"/orders/{order_id}/receipt/",
            files={"image": ("receipt.txt", b"just text", "image/png")},
            expect=400,
        )
        api.post(f"/orders/{order_id}/receipt/", expect=400)

        received = api.post(
            f"/orders/{order_id}/receipt/",
            files={"image": ("receipt.png", png_bytes(300, 500, (30, 120, 60)), "image/png")},
            data={"note": "واریز از همراه‌بانک"},
            expect=201,
        ).json()
        check(received["status"] == "AWAITING_APPROVAL", f"status {received['status']}")
        check(len(received["receipts"]) == 1, "receipt not attached to the order")

        rejected = api.post(f"/orders/{order_id}/reject/", json={"note": "مبلغ کمتر"}, expect=200).json()
        check(rejected["status"] == "AWAITING_RECEIPT", f"after reject: {rejected['status']}")
        api.post(f"/orders/{order_id}/reject/", expect=400)

        api.post(
            f"/orders/{order_id}/receipt/",
            files={"image": ("receipt2.png", png_bytes(300, 500), "image/png")},
            expect=201,
        )
        confirmed = api.post(f"/orders/{order_id}/confirm/", expect=200).json()
        check(confirmed["status"] == "CONFIRMED", f"after confirm: {confirmed['status']}")
        api.post(f"/orders/{order_id}/cancel/", expect=400)
        return "رسید نامعتبر رد شد، رسید واقعی → رد انسانی → رسید دوم → تأیید"

    def tickets_and_handoff(self):
        api, store_id = self.api, self.state["store"]
        complaint = api.post(
            f"/stores/{store_id}/chat/",
            json={"message": "محصول خراب به دستم رسید", "conversation_id": self.state["conversation"]},
            expect=200,
        ).json()
        check(complaint["ticket"] is not None, "no support ticket created for a complaint")
        ticket_id = complaint["ticket"]["id"]
        check(complaint["ticket"]["priority"] == "URGENT", "damaged goods must be urgent")

        tickets = api.get(f"/stores/{store_id}/tickets/", expect=200).json()
        check(tickets["count"] == 1, f"ticket list = {tickets['count']}")
        resolved = api.post(
            f"/tickets/{ticket_id}/resolve/", json={"note": "کالای جایگزین ارسال شد"}, expect=200
        ).json()
        check(resolved["status"] == "RESOLVED", f"ticket status {resolved['status']}")

        escalated = api.post(
            f"/stores/{store_id}/chat/",
            json={"message": "برای من قیمت خاص می‌خواهم", "conversation_id": self.state["conversation"]},
            expect=200,
        ).json()
        check(escalated["state"] == "ESCALATED", f"conversation state {escalated['state']}")

        human = api.post(
            f"/stores/{store_id}/chat/",
            json={"message": "کسی هست؟", "conversation_id": self.state["conversation"]},
            expect=200,
        ).json()
        check(human["message"] is None, "AI answered a conversation that was escalated to a human")

        api.post(f"/conversations/{self.state['conversation']}/handoff/", json={"state": "NOPE"}, expect=400)
        back = api.post(
            f"/conversations/{self.state['conversation']}/handoff/", json={"state": "AI"}, expect=200
        ).json()
        check(back["state"] == "AI", "handoff back to AI failed")
        return "تیکت فوری + حل آن، ارجاع به انسان، سکوت AI، بازگشت به AI"

    def notifications(self):
        api = self.api
        listed = api.get("/notifications/?unread=true", expect=200).json()
        check(listed["unread_count"] >= 3, f"expected several notifications, got {listed['unread_count']}")
        types = {item["type"] for item in listed["results"]}
        for expected in ("ORDER", "RECEIPT", "TICKET", "ESCALATION"):
            check(expected in types, f"no {expected} notification was raised")
        one = listed["results"][0]["id"]
        api.post(f"/notifications/{one}/read/", expect=200)
        api.post("/notifications/read-all/", expect=200)
        after = api.get("/notifications/?unread=true", expect=200).json()
        check(after["unread_count"] == 0, f"{after['unread_count']} notifications still unread")
        return f"{len(types)} نوع اعلان ({', '.join(sorted(types))}) + خوانده‌شدن"

    # ---------------------------------------------------------------- campaigns
    def campaigns(self):
        api = self.api
        campaign = api.post(
            "/campaigns/",
            json={
                "product": self.state["product"],
                "name": "کمپین هدفون پاییز",
                "goal": "فروش مستقیم",
                "audience": "دانشجو",
                "poster": self.state["poster"],
                "caption": self.state["caption"],
                "video_script": self.state["script"],
            },
            expect=201,
        ).json()
        self.state["campaign"] = campaign["id"]
        check(campaign["approval_state"] == "DRAFT", f"new campaign is {campaign['approval_state']}")

        # content of a different product must never be grouped into a campaign
        api.post(
            "/campaigns/",
            json={
                "product": self.state["product2"],
                "name": "کمپین اشتباه",
                "poster": self.state["poster"],
            },
            expect=400,
        )
        api.post(f"/campaigns/{campaign['id']}/publish/", json={"platforms": ["telegram"]}, expect=400)

        rejected = api.post(
            f"/campaigns/{campaign['id']}/reject/", json={"note": "پوستر عوض شود"}, expect=200
        ).json()
        check(rejected["approval_state"] == "REJECTED", "reject did not stick")
        approved = api.post(f"/campaigns/{campaign['id']}/approve/", expect=200).json()
        check(approved["approval_state"] == "APPROVED", "approve did not stick")

        listed = api.get(f"/campaigns/?store={self.state['store']}", expect=200).json()
        check(listed["count"] == 1, f"campaign list = {listed['count']}")
        return f"کمپین #{campaign['id']}: پیش‌نویس → رد → تأیید + رد محتوای محصول دیگر"

    def publishing(self):
        api, campaign_id = self.api, self.state["campaign"]
        api.post(f"/campaigns/{campaign_id}/publish/", json={"platforms": []}, expect=400)
        api.post(f"/campaigns/{campaign_id}/publish/", json={"platforms": ["myspace"]}, expect=400)

        api.run_job(
            f"/campaigns/{campaign_id}/publish/", {"platforms": ["instagram", "telegram"]}
        )
        campaign = api.get(f"/campaigns/{campaign_id}/", expect=200).json()
        check(campaign["approval_state"] == "PUBLISHED", f"state {campaign['approval_state']}")
        jobs = {job["platform"]: job for job in campaign["publish_jobs"]}
        check(set(jobs) == {"instagram", "telegram"}, f"publish jobs: {sorted(jobs)}")
        for platform, job in jobs.items():
            check(job["status"] == "SENT", f"{platform}: {job['status']} — {job['last_error'][:120]}")

        check(len(FakeN8N.received) == 2, f"n8n received {len(FakeN8N.received)} payloads")
        payload = FakeN8N.received[0]["payload"]
        check(FakeN8N.received[0]["token"] == "e2e-secret", "webhook token header missing")
        for key in ("platform", "store", "campaign", "product", "content"):
            check(key in payload, f"webhook payload has no '{key}'")
        poster_url = payload["content"].get("poster_url")
        check(
            bool(poster_url) and poster_url.startswith("http"),
            f"poster URL must be absolute for n8n: {poster_url!r}",
        )
        check(
            requests.get(poster_url, timeout=60).status_code == 200,
            "the poster URL sent to n8n does not actually resolve",
        )
        check(bool(payload["content"]["caption"]["cta"]), "caption not included in the payload")

        # publishing the same campaign twice must not silently double-post
        api.post(
            f"/campaigns/{campaign_id}/publish/", json={"platforms": ["instagram"]}, expect=400
        )
        api.run_job(
            f"/campaigns/{campaign_id}/publish/", {"platforms": ["instagram"], "resend": True}
        )
        check(len(FakeN8N.received) == 3, "explicit resend did not go out")
        return f"۲ پلتفرم تحویل شد، ارسال تکراری بلاک شد، resend صریح کار کرد"

    # ---------------------------------------------------------------- analytics
    def analytics(self):
        api, store_id = self.api, self.state["store"]
        overview = api.get(f"/stores/{store_id}/analytics/", expect=200).json()
        check(overview["products"]["total"] == 2, f"products: {overview['products']}")
        check(
            overview["orders"]["by_status"].get("CONFIRMED") == 1,
            f"orders: {overview['orders']}",
        )
        check(float(overview["orders"]["confirmed_revenue"]) > 0, "confirmed revenue is zero")
        check(
            overview["content"]["generated_images"] == 3, f"content: {overview['content']}"
        )
        check(overview["content"]["captions"] == 3, f"captions: {overview['content']}")
        check(
            overview["campaigns"]["by_state"].get("PUBLISHED") == 1,
            f"campaigns: {overview['campaigns']}",
        )
        check(overview["publishing"]["by_status"].get("SENT", 0) >= 2, "publishing not counted")
        check(overview["ai"]["requests"] > 0, "no AI requests were recorded")
        check(overview["jobs"]["by_state"].get("COMPLETED", 0) > 0, "no completed jobs counted")

        series = api.get(f"/stores/{store_id}/analytics/timeseries/?days=7", expect=200).json()
        check(len(series["series"]) == 7, f"timeseries returned {len(series['series'])} points")
        check(
            sum(point["ai_requests"] for point in series["series"]) > 0,
            "the AI requests made today do not appear in the timeseries",
        )

        sales = api.get(f"/stores/{store_id}/analytics/sales/?days=30", expect=200).json()
        check(float(sales["revenue"]["confirmed_total"]) > 0, f"revenue: {sales['revenue']}")
        check(sales["revenue"]["confirmed_orders"] == 1, f"revenue: {sales['revenue']}")
        check(sales["pending"]["open_tickets"] == 0, "the resolved ticket still counts as open")
        check(sales["conversion"]["rate_percent"] > 0, "conversion rate not computed")
        check(len(sales["top_products"]) >= 1, "no best-selling products")
        check(len(sales["series"]) == 30, f"sales series has {len(sales['series'])} points")
        return (
            f"{overview['products']['total']} محصول، ۱ سفارش تأییدشده، "
            f"درآمد {sales['revenue']['confirmed_total']}، {len(sales['top_products'])} پرفروش"
        )

    # ---------------------------------------------------------------- jobs & embeddings
    def jobs(self):
        api = self.api
        listed = api.get("/jobs/", expect=200).json()
        check(listed["count"] >= 8, f"only {listed['count']} jobs recorded")
        check(
            all(job["state"] in {"COMPLETED", "FAILED", "CANCELLED"} for job in listed["results"]),
            "a job is still active after every pipeline finished",
        )
        active = api.get("/jobs/?active=true", expect=200).json()
        check(active["count"] == 0, f"{active['count']} jobs are stuck in an active state")

        typed = api.get("/jobs/?type=product_analysis", expect=200).json()
        check(typed["count"] >= 1, "type filter returned nothing")
        scoped = api.get(f"/jobs/?product_id={self.state['product']}", expect=200).json()
        check(scoped["count"] >= 4, f"product filter returned {scoped['count']}")
        check(api.get("/jobs/?product_id=abc", expect=200).json()["count"] == 0, "bad filter leaked")

        api.get("/jobs/99999999/", expect=404)
        api.post("/jobs/99999999/cancel/", expect=404)
        cancelled = api.post(f"/jobs/{listed['results'][0]['id']}/cancel/", expect=200).json()
        check(
            cancelled["state"] in {"COMPLETED", "FAILED", "CANCELLED"},
            "cancelling a finished job changed its state",
        )
        return f"{listed['count']} Job، صفر Job فعالِ جامانده، فیلترها و لغو سالم"

    def embeddings(self):
        api, store_id = self.api, self.state["store"]
        status = api.get(f"/stores/{store_id}/embeddings/", expect=200).json()
        check(status["enabled"] is True, "EMBEDDINGS_ENABLED was not picked up")
        check(status["products"] == 2, f"embeddings status products = {status['products']}")

        api.run_job(f"/stores/{store_id}/embeddings/rebuild/")
        after = api.get(f"/stores/{store_id}/embeddings/", expect=200).json()
        check(after["embedded"] == 2, f"{after['embedded']} of 2 products embedded")

        reply = api.post(
            f"/stores/{store_id}/chat/", json={"message": "اسپیکر ضدآب دارید؟"}, expect=200
        ).json()
        check(bool(reply["message"]["text"]), "semantic-search chat turn returned no reply")
        return f"{after['embedded']} بردار ساخته شد و چت با جستجوی معنایی جواب داد"

    # ---------------------------------------------------------------- bare product
    def product_without_photo(self):
        """The second product has no photo and no analysis — the common case
        right after someone adds a product and immediately clicks a button."""
        api, product_id = self.api, self.state["product2"]

        api.post(
            f"/products/{product_id}/image-studio/", json={"kind": "ENHANCED"}, expect=400
        )

        # captions before any analysis must still work, not depend on it
        api.run_job(f"/products/{product_id}/captions/", {"platforms": ["TELEGRAM"]})
        captions = api.get(f"/products/{product_id}/captions/", expect=200).json()
        check(len(captions) == 1, f"expected 1 caption, got {len(captions)}")
        check(captions[0]["about_label"] == "برای خود محصول", captions[0]["about_label"])

        # a poster with no product photo falls back to text-to-image
        api.run_job(f"/products/{product_id}/image-studio/", {"kind": "POSTER"})
        poster = api.get(f"/products/{product_id}/image-studio/", expect=200).json()[0]
        check(
            poster["workflow_version"] == "flux_txt2img@v1",
            f"no-photo poster should be txt2img, was {poster['workflow_version']}",
        )
        check(poster["source_image"] is None, "a poster with no photo claims a source image")

        api.run_job(f"/products/{product_id}/analyze/")
        intelligence = api.get(f"/products/{product_id}/intelligence/", expect=200).json()
        check(intelligence is not None, "analysis of a photo-less product produced nothing")
        check(intelligence["visual_analysis"] == [], "invented a visual analysis with no photo")

        api.run_job(f"/products/{product_id}/video-script/", {"duration": 10})
        script = api.get(f"/products/{product_id}/video-script/", expect=200).json()
        response = api.post(f"/video-scripts/{script['id']}/generate/", expect=[400, 503])
        if response.status_code == 400:
            check(
                response.json()["error"]["code"] == "no_product_image",
                f"unexpected error: {response.json()}",
            )
        return "بدون عکس: کپشن و تحلیل کار کرد، پوستر txt2img شد، ویدیو با پیام روشن رد شد"

    # ---------------------------------------------------------------- deletion
    def deletion(self):
        """Removing a product must take its generated content with it and leave
        the rest of the store untouched."""
        api, store_id, product_id = self.api, self.state["store"], self.state["product2"]
        before = api.get(f"/stores/{store_id}/analytics/", expect=200).json()

        api.delete(f"/products/{product_id}/", expect=204)
        api.get(f"/products/{product_id}/", expect=404)
        api.get(f"/products/{product_id}/captions/", expect=404)

        after = api.get(f"/stores/{store_id}/analytics/", expect=200).json()
        check(
            after["products"]["total"] == before["products"]["total"] - 1,
            f"product count went {before['products']['total']} -> {after['products']['total']}",
        )
        check(
            after["content"]["captions"] < before["content"]["captions"],
            "the deleted product's captions were left behind",
        )
        # the other product and its content survive
        kept = api.get(f"/products/{self.state['product']}/", expect=200).json()
        check(len(kept["images"]) == 1, "deleting one product damaged another")
        check(
            len(api.get(f"/products/{self.state['product']}/captions/", expect=200).json()) == 3,
            "the surviving product lost its captions",
        )
        return "محصول با همهٔ محتوایش حذف شد، بقیهٔ فروشگاه دست‌نخورده ماند"

    # ---------------------------------------------------------------- outages
    def comfyui_down(self):
        """ComfyUI off but Ollama running — the single most common local slip.

        The job must not die with a raw English ConnectionError: the owner has
        to be told, in Persian, that the renderer is simply not started.
        """
        api, product_id = self.api, self.state["product"]
        self.stop_fakes("comfy")

        started = time.monotonic()
        job = api.wait_job(
            api.post(
                f"/products/{product_id}/image-studio/", json={"kind": "POSTER"}, expect=202
            ).json()["job_id"],
            timeout=300,
        )
        elapsed = time.monotonic() - started
        check(job["state"] == "FAILED", f"image job ended {job['state']} with ComfyUI down")
        check("ComfyUI" in job["error"], f"the error never names ComfyUI: {job['error'][:160]}")
        check(
            any("؀" <= ch <= "ۿ" for ch in job["error"]),
            f"ComfyUI outage message is not in Persian: {job['error'][:160]}",
        )
        check(elapsed < 90, f"a switched-off ComfyUI took {elapsed:.0f}s to report")
        check(
            api.get("/jobs/?active=true", expect=200).json()["count"] == 0,
            "the failed render left a job stuck in an active state",
        )
        return f"پیام فارسی «ComfyUI در دسترس نیست» در {elapsed:.1f}s، بدون Job سرگردان"

    def services_down(self):
        """Kill the fakes and prove nothing hangs, stalls or lies.

        This is the state the owner's machine is in whenever Ollama or ComfyUI
        is not running, so every panel must fail fast, say so in Persian, and
        leave no job stuck in a state the UI would spin on forever.
        """
        api, product_id = self.api, self.state["product"]
        self.stop_fakes("all")

        timings = []
        for path, payload in (
            (f"/products/{product_id}/analyze/", {}),
            (f"/products/{product_id}/captions/", {"platforms": ["INSTAGRAM"]}),
            (f"/products/{product_id}/image-studio/", {"kind": "POSTER"}),
            (f"/products/{product_id}/video-script/", {"duration": 10}),
        ):
            started = time.monotonic()
            response = api.post(path, json=payload, expect=[202, 503])
            if response.status_code == 202:
                job = api.wait_job(response.json()["job_id"], timeout=180)
                check(
                    job["state"] == "FAILED",
                    f"{path}: job ended {job['state']} with every service down",
                )
                check(job["error"].strip(), f"{path}: failed with an empty message")
                check(
                    any("؀" <= ch <= "ۿ" for ch in job["error"]),
                    f"{path}: error is not in Persian: {job['error'][:120]}",
                )
            timings.append(time.monotonic() - started)

        check(max(timings) < 120, f"a dead service took {max(timings):.0f}s to report back")

        chat = api.post(
            f"/stores/{self.state['store']}/chat/", json={"message": "سلام"}, expect=503
        ).json()
        check(chat["error"]["code"] == "ai_unavailable", f"chat error: {chat['error']}")

        active = api.get("/jobs/?active=true", expect=200).json()
        check(active["count"] == 0, f"{active['count']} jobs stuck active after the outage")

        alerts = api.get("/notifications/?unread=true", expect=200).json()
        check(
            any(item["type"] == "AI_ERROR" for item in alerts["results"]),
            "the owner was never told the AI could not answer a waiting customer",
        )
        return f"۴ عملیات + چت: شکست سریع (حداکثر {max(timings):.1f}s)، صفر Job سرگردان، اعلان خطا"

    # ---------------------------------------------------------------- docs
    def api_docs(self):
        schema = requests.get(f"{self.base}/api/schema/", timeout=60)
        check(schema.status_code == 200, f"/api/schema/ -> {schema.status_code}")
        docs = requests.get(f"{self.base}/api/docs/", timeout=60)
        check(docs.status_code == 200, f"/api/docs/ -> {docs.status_code}")
        return "اسکیمای OpenAPI و صفحهٔ Swagger سالم‌اند"


# --------------------------------------------------------------------------- runner
STEPS = [
    ("auth", "احراز هویت"),
    ("store", "فروشگاه و پروفایل برند"),
    ("catalog", "کاتالوگ محصول"),
    ("tenancy", "ایزوله‌سازی بین کاربران"),
    ("intelligence", "هوش محصول"),
    ("market", "تحلیل بازار و رقبا"),
    ("image_studio", "استودیوی تصویر"),
    ("captions", "کپشن‌ها"),
    ("video_script", "سناریوی ویدیو"),
    ("video_render", "تولید ویدیو"),
    ("voice", "صداگذاری"),
    ("chat", "چت فروش"),
    ("payment_flow", "پرداخت و رسید"),
    ("tickets_and_handoff", "تیکت و ارجاع به انسان"),
    ("notifications", "اعلان‌ها"),
    ("campaigns", "کمپین‌ها"),
    ("publishing", "انتشار n8n"),
    ("analytics", "آمار"),
    ("jobs", "Jobها"),
    ("embeddings", "جستجوی معنایی"),
    ("api_docs", "مستندات API"),
    ("product_without_photo", "محصول بدون عکس"),
    ("deletion", "حذف محصول"),
    ("comfyui_down", "خاموش‌بودن ComfyUI"),
    ("services_down", "خاموش‌بودن همهٔ سرویس‌ها"),
]


class Runner:
    def __init__(self, args):
        self.args = args
        self.tmp = Path(tempfile.mkdtemp(prefix="upmarket-e2e-"))
        self.processes = []
        self.servers = []
        self.ai_fakes = []

    # -------------------------------------------------------------- lifecycle
    def start_fakes(self):
        ollama_port, comfy_port = free_port(), free_port()
        self.ollama_url, self.comfy_url, servers = fake_ai_stack.serve(ollama_port, comfy_port)
        self.ai_fakes = list(zip(("ollama", "comfy"), servers))
        self.servers.extend(servers)

        n8n_port = free_port()
        FakeN8N.received = []
        n8n = HTTPServer(("127.0.0.1", n8n_port), FakeN8N)
        threading.Thread(target=n8n.serve_forever, daemon=True).start()
        self.servers.append(n8n)
        self.n8n_url = f"http://127.0.0.1:{n8n_port}/webhook/upmarket"

    def child_env(self, api_port):
        env = dict(os.environ)
        env.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "SQLITE_PATH": str(self.tmp / "e2e.sqlite3"),
                "MEDIA_ROOT": str(self.tmp / "media"),
                "DJANGO_DEBUG": "true",
                "DJANGO_SECRET_KEY": "e2e-only-not-a-real-secret-key-0123456789",
                "OLLAMA_BASE_URL": self.ollama_url,
                "COMFYUI_BASE_URL": self.comfy_url,
                "COMFYUI_POLL_INTERVAL": "0.2",
                "OLLAMA_TIMEOUT": "60",
                "OLLAMA_RETRIES": "1",
                "N8N_WEBHOOK_URL": self.n8n_url,
                "N8N_WEBHOOK_TOKEN": "e2e-secret",
                "PUBLIC_BASE_URL": f"http://127.0.0.1:{api_port}",
                "EMBEDDINGS_ENABLED": "true",
                "WEB_SEARCH_PROVIDER": "none",
                "THROTTLE_ANON": "10000/minute",
                "THROTTLE_USER": "10000/minute",
                "GPU_AUTO_UNLOAD": "false",
                "CELERY_TASK_ALWAYS_EAGER": "false" if self.args.queue else "true",
            }
        )
        if self.args.queue:
            env["REDIS_URL"] = f"redis://127.0.0.1:{self.redis_port}/0"
        return env

    def spawn(self, name, argv, cwd=BACKEND, env=None):
        log = (self.tmp / f"{name}.log").open("wb")
        process = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT)
        self.processes.append((name, process, log))
        return process

    def start_redis(self):
        """Bundled portable Redis first, then whatever is on PATH."""
        bundled = BACKEND.parent / "redis" / "redis-server.exe"
        if bundled.exists():
            command, cwd = str(bundled), bundled.parent
        else:
            found = shutil.which("redis-server")
            if not found:
                raise Failure(
                    "--queue needs Redis: run install-redis.bat (portable copy into "
                    f"{bundled.parent}) or put redis-server on PATH"
                )
            command, cwd = found, BACKEND
        self.redis_port = free_port()
        self.spawn(
            "redis",
            [command, "--port", str(self.redis_port), "--save", ""],
            cwd=cwd,
            env=dict(os.environ),
        )
        if not wait_for_port(self.redis_port, 30):
            raise Failure(f"Redis ({command}) did not open port {self.redis_port}")

    def start_backend(self):
        self.api_port = free_port()
        env = self.child_env(self.api_port)
        migrate = subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            cwd=str(BACKEND),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if migrate.returncode != 0:
            raise Failure(f"migrate failed:\n{migrate.stdout[-2000:]}{migrate.stderr[-2000:]}")

        self.spawn(
            "backend",
            [sys.executable, "manage.py", "runserver", f"127.0.0.1:{self.api_port}", "--noreload"],
            env=env,
        )
        if not wait_for_port(self.api_port, 60):
            raise Failure("Django did not start — see backend.log")

        if self.args.queue:
            for name, queues in (("celery-ai", "celery,ai"), ("celery-gpu", "gpu")):
                self.spawn(
                    name,
                    [
                        sys.executable, "-m", "celery", "-A", "config", "worker",
                        "-l", "info", "-Q", queues, "--pool=solo", "-n", f"{name}@e2e",
                    ],
                    env=env,
                )
            time.sleep(6)  # workers need a moment to consume their queues
        return f"http://127.0.0.1:{self.api_port}"

    def stop_ai_fakes(self, which="all"):
        """Shut down a fake model service — the API keeps serving.

        `which` is "comfy" (only the renderer), "ollama", or "all".
        """
        keep = []
        for name, server in self.ai_fakes:
            if which in ("all", name):
                try:
                    server.shutdown()
                    server.server_close()
                except Exception:
                    pass
            else:
                keep.append((name, server))
        self.ai_fakes = keep

    def stop(self):
        for name, process, log in self.processes:
            try:
                process.terminate()
                process.wait(timeout=10)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            log.close()
        for server in self.servers:
            try:
                server.shutdown()
            except Exception:
                pass

    def dump_logs(self):
        for name, _process, _log in self.processes:
            path = self.tmp / f"{name}.log"
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            interesting = [
                line
                for line in text.splitlines()
                if "Traceback" in line or "ERROR" in line or "Error" in line
            ]
            if interesting:
                print(f"\n  --- {name}.log (خطاها) ---")
                for line in interesting[-25:]:
                    print(f"    {line[:200]}")

    # -------------------------------------------------------------- main
    def run(self):
        mode = "صف واقعی (Redis + Celery)" if self.args.queue else "همگام (بدون Redis)"
        print(f"\n  UpMarket — تست سرتاسری API روی مدل‌های شبیه‌سازی‌شده — حالت: {mode}")
        print(f"  پوشهٔ موقت: {self.tmp}\n")

        failures = 0
        try:
            self.start_fakes()
            if self.args.queue:
                self.start_redis()
            base = self.start_backend()
            scenario = Scenario(Api(base), base, self.args.queue, stop_fakes=self.stop_ai_fakes)

            only = {s.strip() for s in (self.args.only or "").split(",") if s.strip()}
            if only:
                # every step builds on the account/store/catalog the first three
                # create, so --only always runs those as prerequisites
                only |= {"auth", "store", "catalog"}
            for key, title in STEPS:
                if only and key not in only:
                    continue
                started = time.monotonic()
                try:
                    detail = getattr(scenario, key)()
                except Failure as exc:
                    print(f"  {FAIL} {title:26s} {exc}")
                    failures += 1
                    if self.args.stop_on_fail:
                        break
                except Exception as exc:  # noqa: BLE001 — the report must never crash
                    print(f"  {FAIL} {title:26s} {type(exc).__name__}: {exc}")
                    failures += 1
                    if self.args.stop_on_fail:
                        break
                else:
                    print(f"  {PASS} {title:26s} {detail}  ({time.monotonic() - started:.1f}s)")
        except Failure as exc:
            print(f"  {FAIL} راه‌اندازی: {exc}")
            failures += 1
        finally:
            if failures:
                self.dump_logs()
            self.stop()
            if self.args.keep:
                print(f"\n  لاگ‌ها نگه داشته شدند: {self.tmp}")
            else:
                shutil.rmtree(self.tmp, ignore_errors=True)

        print("")
        if failures:
            print(f"  {failures} مرحله شکست خورد.\n")
            return 1
        print("  همهٔ مراحل سالم بودند.\n")
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", action="store_true", help="run with real Redis + Celery workers")
    parser.add_argument("--keep", action="store_true", help="keep the temp dir and logs")
    parser.add_argument("--only", default="", help="comma-separated step keys")
    parser.add_argument("--stop-on-fail", action="store_true", help="stop at the first failure")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

    raise SystemExit(Runner(args).run())


if __name__ == "__main__":
    main()
