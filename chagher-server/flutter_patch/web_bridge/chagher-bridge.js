/* ──────────────────────────────────────────────────────────────────────────
   پلِ اپِ فلاتر ← صفحه‌های جنگو  (CHAGHER-BRIDGE v2)

   تغییرهای v2 (از روی گزارشِ مالک):
     ۱) **مسیر را حدس نمی‌زند.** v1 آدرسِ `/chagher/...` را ثابت نوشته بود؛ وقتی
        جنگو روی ریشهٔ دامنه نشست، همه‌چیز ۴۰۴ شد و دکمه «کار نکرد». حالا پایهٔ
        API را خودش پیدا می‌کند و بعد **آدرسِ مطلقِ** هر صفحه را از سرور می‌گیرد.
     ۲) **جای دکمه روی گوشی** بالاتر آمد تا روی نوارِ پایینِ اپ نیفتد.
     ۳) **روی دسکتاپ پنجرهٔ وسطِ صفحه** است، نه شیتِ چسبیده به پایین.
     ۴) **از جنگو ادمین خاموش می‌شود**: اگر `app_bridge` در پاسخِ سرور false باشد،
        دکمه ساخته نمی‌شود (و با خاموشیِ کلِ قابلیت، چیزی هم نشان داده نمی‌شود).

   اگر کاربر وارد نشده باشد، سرور جواب ندهد، یا مدیر خاموش کرده باشد، این پل
   **هیچ چیزی روی صفحه نمی‌گذارد**.

   جابه‌جاییِ دکمه: BTN_SIDE و BTN_BOTTOM_MOBILE در همین بالا.
   ────────────────────────────────────────────────────────────────────────── */
(() => {
  'use strict';

  if (window.__chagherBridge) return;
  window.__chagherBridge = true;

  const BTN_SIDE = 'left';            // 'left' یا 'right'
  const BTN_BOTTOM_MOBILE = 96;       // px — بالاتر از نوارِ پایینِ اپ
  const BTN_BOTTOM_DESKTOP = 22;
  const BRAND = '#126F85';

  // پایه‌های احتمالیِ API، به ترتیبِ آزمایش. اولی حالتِ فعلی (ریشهٔ دامنه) است.
  const API_BASES = ['/api/', '/chagher/api/'];

  const LABELS = {
    manual_program: 'برنامهٔ دستی (بدونِ هوش مصنوعی)',
    equipment_scan: 'اسکنِ دستگاه‌های باشگاه',
    exercise_library: 'کتابخانهٔ حرکت‌ها',
    athlete_profile: 'حسابِ من',
    panel: 'پنلِ ابزارها',
  };
  const ICONS = {
    manual_program: '✎', equipment_scan: '⌾', exercise_library: '☰',
    athlete_profile: '☺', panel: '⊞',
  };
  const ORDER = ['manual_program', 'equipment_scan', 'exercise_library', 'athlete_profile'];

  let apiBase = null;
  let ssoUrl = null;

  // ───────────────────────────── توکنِ کاربر ─────────────────────────────
  function findToken() {
    let keys = [];
    try {
      keys = Object.keys(window.localStorage || {});
    } catch (e) {
      return null;
    }
    const candidates = keys.filter((k) =>
      /token/i.test(k) && !/(balance|amount|required|remaining|package|price)/i.test(k));
    candidates.sort((a, b) => (/auth/i.test(b) ? 1 : 0) - (/auth/i.test(a) ? 1 : 0));
    for (const key of candidates) {
      let value = '';
      try {
        value = window.localStorage.getItem(key) || '';
      } catch (e) {
        continue;
      }
      value = value.trim().replace(/^"(.*)"$/, '$1').trim();
      if (/^[A-Za-z0-9._-]{20,80}$/.test(value)) return value;
    }
    return null;
  }

  // ─────────── پیداکردنِ پایهٔ API و گرفتنِ قابلیت‌ها (بی‌حدس) ───────────
  async function discover(token) {
    for (const base of API_BASES) {
      try {
        const res = await fetch(base + 'me/features/', {
          headers: { Authorization: 'Token ' + token },
          credentials: 'same-origin',
        });
        if (res.ok) {
          apiBase = base;
          return await res.json();
        }
        if (res.status === 401) return null;      // توکنِ کهنه — مسیر درست بود
      } catch (e) {
        /* پایهٔ بعدی */
      }
    }
    return null;
  }

  // ─────────────────────── ورودِ یک‌باره و رفتن به صفحه ───────────────────────
  async function openPage(absoluteUrl) {
    const token = findToken();
    if (!token || !ssoUrl) {
      window.location.href = absoluteUrl;        // صفحه خودش فرمِ ورود را می‌دهد
      return;
    }
    try {
      await fetch(ssoUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ token: token, next: new URL(absoluteUrl).pathname }),
      });
    } catch (e) {
      /* اگر نشد، صفحه فرمِ ورود را نشان می‌دهد */
    }
    window.location.href = absoluteUrl;
  }

  // ───────────────────────────────── ظاهر ─────────────────────────────────
  function styleOnce() {
    if (document.getElementById('chagher-bridge-style')) return;
    const css = `
      .chb-fab{position:fixed;bottom:calc(${BTN_BOTTOM_MOBILE}px + env(safe-area-inset-bottom));
        ${BTN_SIDE}:14px;z-index:2147483000;width:46px;height:46px;border:0;
        border-radius:50%;background:${BRAND};color:#fff;font-size:21px;line-height:46px;
        text-align:center;box-shadow:0 4px 14px rgba(0,0,0,.28);opacity:.78;cursor:pointer;
        transition:opacity .2s,transform .2s;padding:0;font-family:inherit}
      .chb-fab:hover,.chb-fab:focus{opacity:1;transform:scale(1.06)}
      @media (min-width:768px){
        .chb-fab{bottom:${BTN_BOTTOM_DESKTOP}px;width:52px;height:52px;line-height:52px;font-size:23px}
      }
      /* موبایل: شیتِ پایین — دسترسیِ راحتِ انگشت */
      .chb-back{position:fixed;inset:0;background:rgba(10,20,30,.5);z-index:2147483001;
        display:flex;align-items:flex-end;justify-content:center;padding:0}
      .chb-sheet{width:100%;max-width:520px;background:#fff;border-radius:18px 18px 0 0;
        padding:14px 14px calc(16px + env(safe-area-inset-bottom));
        font-family:inherit;direction:rtl;box-shadow:0 -6px 24px rgba(0,0,0,.2);
        max-height:85vh;overflow:auto}
      /* دسکتاپ: پنجرهٔ وسطِ صفحه */
      @media (min-width:768px){
        .chb-back{align-items:center;padding:24px}
        .chb-sheet{border-radius:18px;max-width:440px;padding:18px;
          box-shadow:0 18px 50px rgba(0,0,0,.28)}
      }
      .chb-sheet h3{margin:2px 0 2px;font-size:16px;color:#163F75}
      .chb-sheet p{margin:0 0 12px;font-size:12px;color:#6b7686;line-height:1.8}
      .chb-item{display:flex;align-items:center;gap:10px;width:100%;text-align:right;
        padding:12px;margin-bottom:8px;border:1px solid #e3e6ee;border-radius:12px;
        background:#fff;font:inherit;font-size:14px;color:#1f2733;cursor:pointer}
      .chb-item:hover{background:#f6f9fd;border-color:#cfe0ea}
      .chb-item:active{background:#f0f4fa}
      .chb-item .chb-ic{width:32px;height:32px;border-radius:9px;background:#eef4f8;
        color:${BRAND};font-size:16px;line-height:32px;text-align:center;flex:0 0 32px}
      .chb-close{width:100%;padding:11px;border:0;border-radius:12px;background:#eef2f9;
        font:inherit;font-size:14px;color:#55606f;cursor:pointer}`;
    const tag = document.createElement('style');
    tag.id = 'chagher-bridge-style';
    tag.textContent = css;
    document.head.appendChild(tag);
  }

  function openSheet(features) {
    styleOnce();
    const back = document.createElement('div');
    back.className = 'chb-back';
    const sheet = document.createElement('div');
    sheet.className = 'chb-sheet';
    sheet.innerHTML = '<h3>ابزارهای چغر</h3>'
      + '<p>با همین حساب باز می‌شود؛ لازم نیست دوباره وارد شوی.</p>';

    const urls = features.urls || {};
    let count = 0;
    for (const key of ORDER) {
      if (!features[key] || !urls[key]) continue;
      count += 1;
      const btn = document.createElement('button');
      btn.className = 'chb-item';
      btn.type = 'button';
      btn.innerHTML = '<span class="chb-ic">' + (ICONS[key] || '•') + '</span><span>'
        + LABELS[key] + '</span>';
      btn.addEventListener('click', () => openPage(urls[key]));
      sheet.appendChild(btn);
    }
    if (!count && urls.panel) {
      const btn = document.createElement('button');
      btn.className = 'chb-item';
      btn.type = 'button';
      btn.innerHTML = '<span class="chb-ic">⊞</span><span>' + LABELS.panel + '</span>';
      btn.addEventListener('click', () => openPage(urls.panel));
      sheet.appendChild(btn);
    }

    const close = document.createElement('button');
    close.className = 'chb-close';
    close.type = 'button';
    close.textContent = 'بستن';
    close.addEventListener('click', () => back.remove());
    sheet.appendChild(close);

    back.appendChild(sheet);
    back.addEventListener('click', (e) => {
      if (e.target === back) back.remove();
    });
    document.addEventListener('keydown', function esc(e) {
      if (e.key === 'Escape') { back.remove(); document.removeEventListener('keydown', esc); }
    });
    document.body.appendChild(back);
  }

  function showFab(features) {
    styleOnce();
    if (document.querySelector('.chb-fab')) return;
    const fab = document.createElement('button');
    fab.className = 'chb-fab';
    fab.type = 'button';
    fab.title = 'ابزارهای چغر';
    fab.setAttribute('aria-label', 'ابزارهای چغر');
    fab.textContent = '⊞';
    fab.addEventListener('click', () => openSheet(features));
    document.body.appendChild(fab);
  }

  function removeFab() {
    const fab = document.querySelector('.chb-fab');
    if (fab) fab.remove();
  }

  // ───────────────────────────────── راه‌اندازی ─────────────────────────────────
  async function boot() {
    const token = findToken();
    if (!token) return;
    const features = await discover(token);
    if (!features) return;
    // کلیدِ جنگو ادمین: خاموش ⇒ دکمه نباشد
    if (features.app_bridge === false) { removeFab(); return; }
    ssoUrl = (features.urls || {}).sso || null;
    showFab(features);
  }

  /** توکن بعد از ورودِ کاربر در حافظه می‌نشیند؛ پس چند بار سر می‌زنیم. */
  function watch() {
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      if (document.querySelector('.chb-fab') || tries > 20) {
        clearInterval(timer);
        return;
      }
      if (findToken()) boot();
    }, 3000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { boot(); watch(); });
  } else {
    boot();
    watch();
  }
})();
