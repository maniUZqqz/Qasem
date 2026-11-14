"""کلاینتِ HTTP ِ پنل (فقط کتابخانهٔ استاندارد؛ روی کارگرِ ویندوز هم بی‌نصبِ اضافه کار می‌کند)."""
import json
import mimetypes
import os
import time
import socket
import urllib.error
import urllib.request
import uuid

# پنل وقتی ری‌استارت می‌شود (۵۰۲/۵۰۳/۵۰۴) یا سقفِ درخواست می‌گیرد (۴۲۹) هنوز کاری را انجام نداده؛ فرستادنِ دوباره امن است.
# فاصله‌ها به ثانیه؛ اگر سرور Retry-After بدهد همان (حداکثر ۶۰ ثانیه) می‌ماند.
RETRY_STATUS = (429, 502, 503, 504)
RETRY_DELAYS = (2, 5, 10, 20)
RETRY_AFTER_MAX = 60


class ApiError(Exception):
    def __init__(self, message='', status=None, retry_after=None):
        super().__init__(message)
        self.status = status                # کدِ HTTP، یا None اگر سرور اصلاً در دسترس نبود
        self.retry_after = retry_after      # ثانیه، اگر سرور گفته بود

    @property
    def permanent(self):
        """خطای ۴xx (جز ۴۲۹): تکرارش فایده ندارد."""
        return self.status is not None and 400 <= self.status < 500 and self.status != 429


def _retry_after(err):
    try:
        v = err.headers.get('Retry-After') if getattr(err, 'headers', None) else None
        return min(RETRY_AFTER_MAX, max(0, int(float(v)))) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


class ApiClient:
    def __init__(self, server=None, token=None, scheme='Token', timeout=60):
        self.server = (server or os.environ.get('UP3D_SERVER') or 'http://127.0.0.1:8030').rstrip('/')
        self.token = token or os.environ.get('UP3D_TOKEN', '')
        self.scheme = scheme
        self.timeout = timeout

    sleep = staticmethod(time.sleep)        # آزمون جایگزینش می‌کند

    def _req(self, method, path, data=None, headers=None, raw=False, timeout=None, retries=None):
        """retries: چند بار دوباره (پیش‌فرض ۴). فقط 429/502/503/504 و نرسیدن به سرور تکرار می‌شود؛ ۴xxِ دیگر و زمان‌گذشتن نه
        (زمان‌گذشتن یعنی شاید سرور کار را کرده؛ تکرارِ ناخواسته ممنوع)."""
        n = len(RETRY_DELAYS) if retries is None else max(0, int(retries))
        for i in range(n + 1):
            try:
                return self._once(method, path, data, headers, raw, timeout)
            except ApiError as e:
                if i >= n or not (e.status in RETRY_STATUS or (e.status is None and getattr(e, 'connect_failed', False))):
                    raise
                self.sleep(e.retry_after if e.retry_after is not None else RETRY_DELAYS[min(i, len(RETRY_DELAYS) - 1)])

    def _once(self, method, path, data=None, headers=None, raw=False, timeout=None):
        url = self.server + path
        h = {'Accept': 'application/json'}
        if self.token:
            h['Authorization'] = '%s %s' % (self.scheme, self.token)
        body = None
        if data is not None and not isinstance(data, (bytes, bytearray)):
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            h['Content-Type'] = 'application/json; charset=utf-8'
        elif data is not None:
            body = data
        h.update(headers or {})
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                payload = r.read()
        except urllib.error.HTTPError as e:
            raise ApiError('%s %s ⇐ %s %s' % (method, path, e.code, e.read()[:400].decode('utf-8', 'replace')),
                           status=e.code, retry_after=_retry_after(e)) from e
        except urllib.error.URLError as e:
            err = ApiError('سرور در دسترس نیست: %s' % e)
            err.connect_failed = not isinstance(getattr(e, 'reason', None), (socket.timeout, TimeoutError))   # نرسیدن، نه زمان‌گذشتن
            raise err from e
        if raw:
            return payload
        return json.loads(payload.decode('utf-8')) if payload else {}

    def get(self, path, **kw):
        return self._req('GET', path, **kw)

    def post(self, path, data=None, **kw):
        return self._req('POST', path, data if data is not None else {}, **kw)

    def download(self, path, dest, timeout=600, attempts=4):
        """بستهٔ کار؛ با خطِ ناپایدار چند بار تلاش (فاصلهٔ ۵، ۱۰، ۲۰ ثانیه)."""
        last = None
        for i in range(attempts):
            try:
                data = self._req('GET', path, raw=True, timeout=timeout)
                with open(dest, 'wb') as fh:
                    fh.write(data)
                return dest
            except ApiError as e:
                last = e
                if e.permanent:                          # 4xx (جز ۴۲۹): تکرار فایده ندارد
                    raise
                time.sleep(5 * (2 ** i))
        raise last

    def upload(self, path, files, fields=None, timeout=1800):
        """files: {field: filepath}"""
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in (fields or {}).items():
            parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode('utf-8'))
        for k, fp in files.items():
            name = os.path.basename(fp)
            ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
            with open(fp, 'rb') as fh:
                content = fh.read()
            parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: %s\r\n\r\n' % (
                boundary, k, name, ctype)).encode('utf-8') + content + b'\r\n')
        parts.append(('--%s--\r\n' % boundary).encode('utf-8'))
        return self._req('POST', path, b''.join(parts), {'Content-Type': 'multipart/form-data; boundary=%s' % boundary},
                         timeout=timeout)

    # ── راحتی برای SDK
    def render_scene(self, doc, profile='preview', title=None, wait=False):
        r = self.post('/api/v1/up3d/scenes/', {'title': title or doc.get('meta', {}).get('title') or 'از SDK', 'document': doc})
        job = self.post('/api/v1/up3d/scenes/%s/render/' % r['id'], {'profile': profile})
        return self.wait(job['id']) if wait else job

    def wait(self, job_id, every=5, timeout=6 * 3600):
        t0 = time.time()
        while time.time() - t0 < timeout:
            j = self.get('/api/v1/up3d/jobs/%s/' % job_id)
            if j['state'] in ('COMPLETED', 'FAILED', 'CANCELLED'):
                return j
            time.sleep(every)
        raise ApiError('زمانِ انتظار تمام شد')
