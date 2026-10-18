"""کلاینتِ HTTP ِ پنل (فقط کتابخانهٔ استاندارد؛ روی کارگرِ ویندوز هم بی‌نصبِ اضافه کار می‌کند)."""
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid


class ApiError(Exception):
    pass


class ApiClient:
    def __init__(self, server=None, token=None, scheme='Token', timeout=60):
        self.server = (server or os.environ.get('UP3D_SERVER') or 'http://127.0.0.1:8030').rstrip('/')
        self.token = token or os.environ.get('UP3D_TOKEN', '')
        self.scheme = scheme
        self.timeout = timeout

    def _req(self, method, path, data=None, headers=None, raw=False, timeout=None):
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
            raise ApiError('%s %s ⇐ %s %s' % (method, path, e.code, e.read()[:400].decode('utf-8', 'replace'))) from e
        except urllib.error.URLError as e:
            raise ApiError('سرور در دسترس نیست: %s' % e) from e
        if raw:
            return payload
        return json.loads(payload.decode('utf-8')) if payload else {}

    def get(self, path, **kw):
        return self._req('GET', path, **kw)

    def post(self, path, data=None, **kw):
        return self._req('POST', path, data if data is not None else {}, **kw)

    def download(self, path, dest, timeout=600):
        data = self._req('GET', path, raw=True, timeout=timeout)
        with open(dest, 'wb') as fh:
            fh.write(data)
        return dest

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
