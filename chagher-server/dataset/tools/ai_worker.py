#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""کارگرِ هوش مصنوعیِ چغر — روی سرورِ خودتان که آی‌پیِ ثابت ندارد اجرا می‌شود.

این برنامه هیچ پورتی باز نمی‌کند و نیازی به آی‌پیِ ثابت یا پورت‌فورواردینگ
ندارد. **خودش** به سایتِ چغر وصل می‌شود و سه کار می‌کند:

    ۱) هر چند ثانیه می‌گوید «من روشنم» (heartbeat) — سایت از همین می‌فهمد که
       می‌تواند کار به شما بسپارد؛ وگرنه سراغِ سرویسِ ابری می‌رود و کاربر
       معطل نمی‌ماند.
    ۲) می‌پرسد «کاری داری؟» و اگر بود برمی‌دارد.
    ۳) کار را به مدلِ محلیِ خودتان می‌دهد (هر سروری که درگاهِ سازگار با OpenAI
       دارد: Ollama، LM Studio، vLLM، llama.cpp) و جواب را برمی‌گرداند.

اجرا:
    python ai_worker.py --site https://chagher.ir --key <کلیدِ مشترک> \
                        --model qwen2.5:14b --local http://127.0.0.1:11434/v1

کلیدِ مشترک را در جنگو ادمین → «تنظیمات API هوش مصنوعی» → ارائه‌دهندهٔ نوعِ
«سرورِ خودم بدونِ آی‌پی» → فیلدِ «کلید API» می‌گذارید؛ همان را این‌جا بدهید.

برای اجرای دائمی (لینوکس):
    sudo cp ai_worker.py /usr/local/bin/
    sudo tee /etc/systemd/system/chagher-ai-worker.service >/dev/null <<'EOF'
    [Unit]
    Description=Chagher AI worker
    After=network.target
    [Service]
    ExecStart=/usr/bin/python3 /usr/local/bin/ai_worker.py --site https://chagher.ir \
        --key KEY --model MODEL --local http://127.0.0.1:11434/v1
    Restart=always
    RestartSec=5
    [Install]
    WantedBy=multi-user.target
    EOF
    sudo systemctl enable --now chagher-ai-worker
"""
import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request

UA = 'ChagherAIWorker/1.0'


def post(url, key, payload=None, timeout=30):
    body = json.dumps(payload or {}).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST', headers={
        'Content-Type': 'application/json',
        'X-Worker-Key': key,
        'User-Agent': UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', 'replace')
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try:
            return e.code, json.loads(raw) if raw.strip() else {}
        except Exception:
            return e.code, {'raw': raw[:200]}
    except Exception as exc:
        return 0, {'error': str(exc)}


def ask_local_model(local_url, model, messages, max_tokens, timeout):
    """کار را به مدلِ محلی می‌دهد (درگاهِ سازگار با OpenAI)."""
    payload = {'model': model, 'messages': messages}
    if max_tokens:
        payload['max_tokens'] = int(max_tokens)
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(local_url.rstrip('/') + '/chat/completions',
                                 data=body, method='POST',
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer local',
                                          'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode('utf-8', 'replace'))
    text = (data.get('choices') or [{}])[0].get('message', {}).get('content') or ''
    usage = data.get('usage') or {}
    return text.strip(), {
        'prompt_tokens': usage.get('prompt_tokens', 0),
        'completion_tokens': usage.get('completion_tokens', 0),
    }


def main():
    ap = argparse.ArgumentParser(description='کارگرِ هوش مصنوعیِ چغر')
    ap.add_argument('--site', required=True, help='مثلاً https://chagher.ir')
    ap.add_argument('--key', required=True, help='کلیدِ مشترک از جنگو ادمین')
    ap.add_argument('--local', default='http://127.0.0.1:11434/v1',
                    help='آدرسِ مدلِ محلیِ سازگار با OpenAI')
    ap.add_argument('--model', default='qwen2.5:14b', help='نامِ مدلِ محلی')
    ap.add_argument('--name', default=socket.gethostname(), help='نامِ این کارگر')
    ap.add_argument('--poll', type=float, default=2.0, help='فاصلهٔ پرسیدن (ثانیه)')
    ap.add_argument('--model-timeout', type=int, default=300,
                    help='مهلتِ مدلِ محلی (ثانیه)')
    args = ap.parse_args()

    base = args.site.rstrip('/') + '/api/ai-bridge'
    print('کارگرِ «%s» روشن شد. سایت: %s' % (args.name, args.site), flush=True)

    last_beat = 0.0
    while True:
        try:
            # ۱) هر ۲۰ ثانیه «من روشنم»
            if time.time() - last_beat > 20:
                code, data = post(base + '/heartbeat/', args.key, {'worker': args.name})
                if code == 401:
                    print('✗ کلیدِ مشترک درست نیست — در جنگو ادمین چک کنید.', flush=True)
                    time.sleep(30)
                    continue
                if code == 200:
                    last_beat = time.time()
                    queued = data.get('queued_jobs', 0)
                    if queued:
                        print('در صف: %s کار' % queued, flush=True)
                else:
                    print('هشدار: heartbeat جواب نداد (کد %s)' % code, flush=True)

            # ۲) کاری هست؟
            code, job = post(base + '/claim/', args.key, {'worker': args.name})
            if code == 204 or not job:
                time.sleep(args.poll)
                continue
            if code == 401:
                time.sleep(30)
                continue
            if code != 200:
                print('هشدار: claim کد %s' % code, flush=True)
                time.sleep(args.poll)
                continue

            job_id = job.get('job_id')
            model = job.get('model_hint') or args.model
            print('کارِ #%s برداشته شد (مدل %s)' % (job_id, model), flush=True)

            # ۳) اجرا و تحویل
            try:
                text, usage = ask_local_model(
                    args.local, model, job.get('messages') or [],
                    job.get('max_tokens'), args.model_timeout)
            except Exception as exc:
                print('✗ مدلِ محلی خطا داد: %s' % exc, flush=True)
                post(base + '/%s/fail/' % job_id, args.key, {'error': str(exc)[:400]})
                continue

            if not text:
                post(base + '/%s/fail/' % job_id, args.key, {'error': 'جوابِ خالی'})
                continue

            code, res = post(base + '/%s/result/' % job_id, args.key,
                             {'text': text, 'usage': usage}, timeout=60)
            if code == 200 and res.get('accepted'):
                print('✓ کارِ #%s تحویل شد (%s نویسه)' % (job_id, len(text)), flush=True)
            elif code == 409:
                # سایت دیگر منتظر نبود؛ این کار حساب نمی‌شود (جلوگیری از دو هزینه)
                print('… کارِ #%s دیر شد و دور ریخته شد' % job_id, flush=True)
            else:
                print('هشدار: تحویلِ #%s کد %s — %s' % (job_id, code, res), flush=True)

        except KeyboardInterrupt:
            print('خاموش شد.', flush=True)
            return 0
        except Exception as exc:
            print('خطای غیرمنتظره: %s' % exc, flush=True)
            time.sleep(5)


if __name__ == '__main__':
    sys.exit(main())
