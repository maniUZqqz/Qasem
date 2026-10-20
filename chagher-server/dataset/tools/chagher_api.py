# -*- coding: utf-8 -*-
"""API چغر برای فرستادنِ دیتاستِ حرکت‌ها به بک‌اندِ اصلی (FastAPI).

کارِ این برنامه دو چیز است:
  ۱) دیتاست را روی همین کامپیوتر به‌صورتِ API سرو می‌کند (برای آزمایش و فرانت).
  ۲) با یک دکمه/یک درخواست، همهٔ حرکت‌ها + گیف و عکس را به بک‌اندِ جنگوی چغر آپلود می‌کند.

راه‌اندازی:
    pip install fastapi uvicorn httpx
    python chagher_api.py                 →  http://127.0.0.1:8800

در مرورگر http://127.0.0.1:8800 را باز کنید، آدرسِ بک‌اند و توکنِ مدیر را بگذارید و «شروع آپلود» را بزنید.
یا بدونِ مرورگر:
    curl -X POST "http://127.0.0.1:8800/push" -H "Content-Type: application/json" \
         -d '{"target":"http://SERVER:8000/chagher","token":"<توکن مدیر>"}'

تنظیماتِ پیش‌فرض در config.json ذخیره می‌شود تا دفعهٔ بعد دوباره وارد نکنید.
نکته: آپلود قابلِ ادامه است — چیزی که قبلاً رفته دوباره فرستاده نمی‌شود.
"""
import asyncio
import io
import json
import os
import time
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(HERE, 'chagher-exercises.json')
MEDIA_DIR = os.path.join(HERE, 'media_hq')          # گیف/عکسِ باکیفیت
CONFIG = os.path.join(HERE, 'config.json')

app = FastAPI(title='Chagher Exercise Dataset API', version='1.0')

_data = None
_job = {'running': False, 'phase': '', 'done': 0, 'total': 0, 'created': 0, 'updated': 0,
        'media': 0, 'errors': [], 'started': None, 'finished': None}


def dataset():
    global _data
    if _data is None:
        with io.open(DATASET, encoding='utf-8') as f:
            _data = json.load(f)
    return _data


def load_config():
    if os.path.exists(CONFIG):
        try:
            return json.load(io.open(CONFIG, encoding='utf-8'))
        except Exception:
            pass
    return {'target': '', 'token': ''}


def save_config(cfg):
    json.dump(cfg, io.open(CONFIG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


# ───────────────────────── سرو کردنِ محلیِ دیتاست ─────────────────────────

@app.get('/exercises')
def list_exercises(search: str = '', equipment: str = '', body_part: str = '',
                   page: int = 1, page_size: int = 50):
    rows = dataset()['exercises']
    if search:
        s = search.lower()
        rows = [r for r in rows if s in (r['name'] or '').lower() or s in (r.get('name_fa') or '')]
    if equipment:
        rows = [r for r in rows if (r.get('equipment') or '').lower() == equipment.lower()
                or (r.get('equipment_fa') or '') == equipment]
    if body_part:
        rows = [r for r in rows if (r.get('body_part') or '').lower() == body_part.lower()
                or (r.get('body_part_fa') or '') == body_part]
    total = len(rows)
    page = max(1, page)
    page_size = min(200, max(1, page_size))
    return {'count': total, 'page': page, 'page_size': page_size,
            'results': rows[(page - 1) * page_size: page * page_size]}


@app.get('/exercises/{ex_id}')
def get_exercise(ex_id: str):
    for r in dataset()['exercises']:
        if r['id'] == ex_id:
            return r
    raise HTTPException(404, 'حرکت پیدا نشد')


@app.get('/media/gif/{ex_id}.gif')
def get_gif(ex_id: str):
    p = os.path.join(MEDIA_DIR, 'gif', ex_id + '.gif')
    if not os.path.exists(p):
        raise HTTPException(404, 'گیف پیدا نشد')
    return FileResponse(p, media_type='image/gif')


@app.get('/media/thumb/{ex_id}.jpg')
def get_thumb(ex_id: str):
    p = os.path.join(MEDIA_DIR, 'thumb', ex_id + '.jpg')
    if not os.path.exists(p):
        raise HTTPException(404, 'عکس پیدا نشد')
    return FileResponse(p, media_type='image/jpeg')


# ───────────────────────────── آپلود به بک‌اند ─────────────────────────────

class PushRequest(BaseModel):
    target: str                      # مثال: http://185.239.3.189:8000/chagher
    token: str                       # توکنِ کاربرِ مدیر (DRF Token)
    batch_size: int = 50
    with_media: bool = True
    only_missing: bool = True        # فقط آنچه هنوز روی سرور نیست
    limit: int = 0                   # ۰ = همه (برای آزمایش مثلاً ۵)


async def push_job(req: PushRequest):
    _job.update({'running': True, 'phase': 'آماده‌سازی', 'done': 0, 'created': 0,
                 'updated': 0, 'media': 0, 'errors': [], 'started': time.time(),
                 'finished': None})
    base = req.target.rstrip('/')
    headers = {'Authorization': f'Token {req.token}'}
    rows = dataset()['exercises']
    if req.limit:
        rows = rows[:req.limit]
    _job['total'] = len(rows)

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            have, have_media = set(), set()
            if req.only_missing:
                r = await client.get(f'{base}/api/exercise-library/status/', headers=headers)
                if r.status_code == 200:
                    j = r.json()
                    have = set(j.get('ids') or [])
                    have_media = set(j.get('ids_with_gif') or [])
                elif r.status_code in (401, 403):
                    raise RuntimeError('توکن پذیرفته نشد (۴۰۱/۴۰۳). توکنِ کاربرِ مدیر لازم است.')

            # ۱) داده‌ها
            _job['phase'] = 'فرستادنِ داده‌ها'
            todo = [r for r in rows if r['id'] not in have] if req.only_missing else rows
            for i in range(0, len(todo), req.batch_size):
                chunk = todo[i:i + req.batch_size]
                payload = {'exercises': [{
                    'external_id': r['id'],
                    'name': r['name'], 'name_fa': r.get('name_fa') or '',
                    'category': r.get('category') or '', 'category_fa': r.get('category_fa') or '',
                    'body_part': r.get('body_part') or '', 'body_part_fa': r.get('body_part_fa') or '',
                    'equipment': r.get('equipment') or '', 'equipment_fa': r.get('equipment_fa') or '',
                    'target': r.get('target') or '', 'target_fa': r.get('target_fa') or '',
                    'muscle_group': r.get('muscle_group') or '',
                    'muscle_group_fa': r.get('muscle_group_fa') or '',
                    'secondary_muscles': r.get('secondary_muscles') or [],
                    'secondary_muscles_fa': r.get('secondary_muscles_fa') or [],
                    'instructions_en': r.get('instructions_en') or '',
                    'instructions_fa': r.get('instructions_fa') or '',
                    'steps_en': r.get('instruction_steps_en') or [],
                    'steps_fa': r.get('instruction_steps_fa') or [],
                    'source': 'chagher-dataset', 'brand': r.get('brand') or 'چغر',
                    'attribution': r.get('media_attribution') or '',
                } for r in chunk]}
                resp = await client.post(f'{base}/api/exercise-library/import/',
                                         json=payload, headers=headers)
                if resp.status_code != 200:
                    _job['errors'].append(f'داده {i}: {resp.status_code} {resp.text[:200]}')
                else:
                    j = resp.json()
                    _job['created'] += j.get('created', 0)
                    _job['updated'] += j.get('updated', 0)
                    _job['errors'] += (j.get('errors') or [])[:5]
                _job['done'] = min(len(rows), i + len(chunk))

            # ۲) مدیا
            if req.with_media:
                _job['phase'] = 'آپلودِ گیف و عکس'
                _job['done'] = 0
                media_todo = [r for r in rows if not (req.only_missing and r['id'] in have_media)]
                _job['total'] = len(media_todo)
                for n, r in enumerate(media_todo, 1):
                    gif = os.path.join(MEDIA_DIR, 'gif', r['id'] + '.gif')
                    thumb = os.path.join(MEDIA_DIR, 'thumb', r['id'] + '.jpg')
                    files = {}
                    if os.path.exists(gif):
                        files['gif'] = (r['id'] + '.gif', open(gif, 'rb'), 'image/gif')
                    if os.path.exists(thumb):
                        files['thumb'] = (r['id'] + '.jpg', open(thumb, 'rb'), 'image/jpeg')
                    if not files:
                        continue
                    try:
                        resp = await client.post(
                            f'{base}/api/exercise-library/{r["id"]}/media/',
                            files=files, headers=headers)
                        if resp.status_code == 200:
                            _job['media'] += 1
                        else:
                            _job['errors'].append(f'مدیا {r["id"]}: {resp.status_code}')
                    finally:
                        for f in files.values():
                            try:
                                f[1].close()
                            except Exception:
                                pass
                    _job['done'] = n
    except Exception as e:
        _job['errors'].append(str(e)[:300])
    finally:
        _job['phase'] = 'تمام شد'
        _job['running'] = False
        _job['finished'] = time.time()


@app.post('/push')
async def push(req: PushRequest):
    if _job['running']:
        raise HTTPException(409, 'یک آپلود همین حالا در حالِ اجراست')
    save_config({'target': req.target, 'token': req.token})
    asyncio.create_task(push_job(req))
    return {'ok': True, 'message': 'آپلود شروع شد — وضعیت را از /status ببینید'}


@app.get('/status')
def status():
    j = dict(_job)
    if j['started']:
        j['seconds'] = int((j['finished'] or time.time()) - j['started'])
    return JSONResponse(j)


@app.get('/', response_class=HTMLResponse)
def home():
    cfg = load_config()
    total = len(dataset()['exercises'])
    gifs = len(os.listdir(os.path.join(MEDIA_DIR, 'gif'))) if os.path.isdir(os.path.join(MEDIA_DIR, 'gif')) else 0
    return f"""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">
<title>آپلودِ دیتاستِ چغر</title>
<style>
 body{{font-family:Tahoma,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;color:#222}}
 h1{{font-size:20px}} label{{display:block;margin:12px 0 4px;font-size:14px}}
 input{{width:100%;padding:9px;border:1px solid #ccc;border-radius:8px;font-size:14px}}
 button{{margin-top:16px;padding:10px 18px;border:0;border-radius:8px;background:#1565c0;color:#fff;font-size:15px;cursor:pointer}}
 pre{{background:#f5f5f5;padding:12px;border-radius:8px;white-space:pre-wrap;font-size:13px}}
 .muted{{color:#666;font-size:13px}}
</style>
<h1>آپلودِ دیتاستِ حرکت‌ها به بک‌اندِ چغر</h1>
<p class="muted">{total} حرکت · {gifs} گیفِ باکیفیت آماده است.</p>
<label>آدرسِ بک‌اند (تا /chagher)</label>
<input id="t" value="{cfg.get('target','')}" placeholder="http://185.239.3.189:8000/chagher">
<label>توکنِ مدیر</label>
<input id="k" value="{cfg.get('token','')}" placeholder="توکنِ DRF کاربرِ مدیر">
<label><input type="checkbox" id="m" checked style="width:auto"> گیف و عکس هم فرستاده شود</label>
<button onclick="go()">شروع آپلود</button>
<button onclick="go(5)" style="background:#555">آزمایشِ ۵ تایی</button>
<pre id="o">آماده.</pre>
<script>
async function go(limit){{
  const body={{target:document.getElementById('t').value,token:document.getElementById('k').value,
               with_media:document.getElementById('m').checked,limit:limit||0}};
  const r=await fetch('/push',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
  document.getElementById('o').textContent=JSON.stringify(await r.json(),null,1);
  poll();
}}
async function poll(){{
  const r=await fetch('/status'); const j=await r.json();
  document.getElementById('o').textContent =
    `مرحله: ${{j.phase}}\\nپیشرفت: ${{j.done}}/${{j.total}}\\nساخته‌شده: ${{j.created}} · به‌روزشده: ${{j.updated}} · مدیا: ${{j.media}}\\n` +
    (j.seconds?`زمان: ${{j.seconds}} ثانیه\\n`:'') + (j.errors.length?`خطاها:\\n- ${{j.errors.slice(0,8).join('\\n- ')}}`:'');
  if(j.running) setTimeout(poll,1500);
}}
poll();
</script></html>"""


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8800)
