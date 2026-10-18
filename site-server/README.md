# UpMarket — آپ‌مارکت

**UpMarket (آپ‌مارکت)** — کارمند فروش و مارکتینگ هوش مصنوعی برای فروشگاه‌های آنلاین.

- 🚀 اجرا: دابل‌کلیک روی `start.bat` — بک‌اند، داشبورد و سایت عمومی را با هم بالا می‌آورد.
  ComfyUI خودکار پیدا می‌شود؛ مسیر دستی لازم نیست.
- 🤖 بدون GPU: در `backend/.env` مقدار `AI_API_BASE_URL` را بگذار تا متن و بینایی از API
  بیایند — آن‌وقت Ollama و ComfyUI اصلاً اجرا نمی‌شوند.
- 🗺️ رودمپ و مرجع کامل توسعه: [ROADMAP.md](ROADMAP.md)
- 🌙 چک‌لیست تست: [test.md](test.md)
- 🏗️ معماری — سیستم، AI و خط ویدیو در یک فایل: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 🗄️ نقشه‌ی دیتابیس (تولیدشده از مدل‌ها): [docs/DATABASE.md](docs/DATABASE.md)
- 📡 مرجع API (همان چیزی که واقعاً ساخته شده): [docs/API.md](docs/API.md)
- ✅ تست کامل بدون مدل‌ها: [docs/VERIFICATION.md](docs/VERIFICATION.md)
- ⚙️ بک‌اند (Django + Celery + Ollama + ComfyUI): [backend/README.md](backend/README.md)
- 🖥️ فرانت‌اند (React + Vite + TS): [frontend/README.md](frontend/README.md)

## Self-check خودکار

`start.bat` قبل از بالا آوردن سرویس‌ها، کل برنامه را با **مدل‌های شبیه‌سازی‌شده**
اجرا می‌کند — از لاگین تا انتشار، شامل تولید ویدیو. حدود یک دقیقه، بدون نیاز به
GPU، Ollama یا ComfyUI:

```
[OK]   AI pipelines - analysis, market, captions, poster, script, video, chat
[OK]   API end-to-end - login, catalog, content, chat, orders, campaigns, publish
```

`[FAIL]` یعنی مشکل از **کد** است نه مدل‌ها. رد کردن: `start.bat /notest`.
تست‌های دستی و عمیق‌تر: [docs/VERIFICATION.md](docs/VERIFICATION.md).
