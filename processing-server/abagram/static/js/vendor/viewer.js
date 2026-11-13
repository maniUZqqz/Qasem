/* نمایشگر رسانه — عکس و ویدیو، وانیلا. (کپیِ D:/Exhibition/data-site/web/static/viewer.js — همان ویوئرِ MIRA)

   الگوها از ویوئرهای MIRA (MediaViewer / ImageViewer / VideoPlayer)
   برداشته شده‌اند: زومِ لنگرزده به مکان‌نما، pinch دو انگشتی،
   سوایپ برای بستن، کرومِ خودمحوشونده، کنترل‌های دستیِ ویدیو،
   و حلقه‌ی پیشرفتِ دانلود. آنجا React و framer-motion بود؛ اینجا
   نه فریم‌ورک داریم و نه اجازه‌ی CDN، پس همان رفتار با
   transition و pointer events بازنویسی شده.

   یک نکته‌ی کلیدی که از آنجا آمد: همه‌ی هندلرهای اشاره‌گر فقط روی
   عکس فعال‌اند. pointer capture روی ویدیو کلیک را می‌دزدد و دکمه‌ی
   پخش از کار می‌افتد. */

/* همه‌چیز داخل IIFE. اسکریپت‌های این پنل کلاسیک‌اند و همه در یک
   scope زندگی می‌کنند؛ `fa` و `esc` را app.js از قبل تعریف کرده و
   تعریف دوباره‌شان کل فایل را از پارس می‌اندازد — یعنی نمایشگر
   بی‌صدا اصلاً بار نمی‌شود. تنها چیزی که بیرون می‌دهیم Viewer است. */
(function () {
'use strict';

const ICON = {
  x: 'M6 6l12 12M18 6L6 18',
  prev: 'M15 5l-7 7 7 7',
  next: 'M9 5l7 7-7 7',
  dl: 'M12 3v12m0 0l-4-4m4 4l4-4M5 21h14',
  full: 'M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3m13 5h3a2 2 0 0 0 2-2v-3',
  b5: 'M11 17l-5-5 5-5M18 17l-5-5 5-5',
  f5: 'M13 17l5-5-5-5M6 17l5-5-5-5',
  vol: 'M11 5L6 9H3v6h3l5 4V5zM16 9a4 4 0 0 1 0 6',
  mute: 'M11 5L6 9H3v6h3l5 4V5zM17 9l4 6M21 9l-4 6',
};
const svg = (d, fill) => '<svg viewBox="0 0 24 24"' + (fill ? ' fill="currentColor" stroke="none"' : '') +
  '><path d="' + d + '"/></svg>';
const PLAY = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="currentColor" stroke="none"/></svg>';
const PAUSE = '<svg viewBox="0 0 24 24"><path d="M7 4h4v16H7zM13 4h4v16h-4z" fill="currentColor" stroke="none"/></svg>';

const FA = '۰۱۲۳۴۵۶۷۸۹';
const fa = n => String(n).replace(/[0-9]/g, d => FA[+d]);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const mmss = s => (!Number.isFinite(s) || s < 0) ? '۰:۰۰'
  : fa(Math.floor(s / 60)) + ':' + fa(String(Math.floor(s % 60)).padStart(2, '0'));

const S = {
  root: null, els: {}, items: [], i: 0, dirX: 0,
  lastFocus: null, url: null, ac: null, idle: 0, reduce: false,
};

function shell() {
  if (S.root) return;
  const el = document.createElement('div');
  el.className = 'vw';
  el.hidden = true;
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-modal', 'true');
  el.setAttribute('aria-label', 'نمایشگر رسانه');
  el.innerHTML =
    '<div class="vw-scrim" data-close></div>' +
    '<div class="vw-segs" hidden></div>' +
    '<div class="vw-top">' +
      '<span class="vw-count" hidden></span>' +
      '<div class="vw-title"><b></b><span></span></div>' +
      '<a class="vw-btn dl" download hidden aria-label="ذخیره">' + svg(ICON.dl) + '</a>' +
      '<button class="vw-btn" type="button" data-close aria-label="بستن">' + svg(ICON.x) + '</button>' +
    '</div>' +
    '<div class="vw-stage"></div>' +
    '<button class="vw-btn vw-edge prev" type="button" hidden aria-label="قبلی">' + svg(ICON.prev) + '</button>' +
    '<button class="vw-btn vw-edge next" type="button" hidden aria-label="بعدی">' + svg(ICON.next) + '</button>' +
    '<div class="vw-bottom">' +
      '<div class="vw-strip" hidden></div>' +
      '<span class="vw-cap"></span>' +
      '<button class="vw-zoom" type="button" hidden>۱۰۰٪</button>' +
    '</div>';
  document.body.appendChild(el);
  S.root = el;
  const q = s => el.querySelector(s);
  S.els = {
    scrim: q('.vw-scrim'), segs: q('.vw-segs'), count: q('.vw-count'),
    name: q('.vw-title b'), sub: q('.vw-title span'), dl: q('.vw-btn.dl'),
    stage: q('.vw-stage'), cap: q('.vw-cap'), zoom: q('.vw-zoom'),
    strip: q('.vw-strip'), prev: q('.vw-edge.prev'), next: q('.vw-edge.next'),
  };
  S.reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  el.addEventListener('click', e => { if (e.target.closest('[data-close]')) close(); });
  // چرخ روی کلِ صحنه، نه فقط روی خودِ تصویر: با تصویرِ نامه‌ای، مکان‌نما اغلب
  // در حاشیه‌ی خالی است و شنونده‌ی روی <img> هیچ‌وقت صدا زده نمی‌شد.
  S.els.stage.addEventListener('wheel', (e) => {
    const it = S.items[S.i];
    if (!imgEl || (it && it.kind === 'video')) return;
    e.preventDefault();
    const r = imgEl.getBoundingClientRect();
    zoomAt(T.s * (e.deltaY < 0 ? 1.18 : 1 / 1.18),
           e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2));
  }, { passive: false });
  S.els.prev.addEventListener('click', () => go(-1));
  S.els.next.addEventListener('click', () => go(1));
  S.els.zoom.addEventListener('click', () => resetZoom());
  el.addEventListener('pointermove', poke);
  el.addEventListener('pointerdown', poke);
  document.addEventListener('keydown', onKey, true);
}

/* کروم بعد از بی‌حرکتی محو می‌شود ولی هر حرکتی برش می‌گرداند.
   ۲۶۰۰ms همان عددی است که در MediaViewer جواب داده بود. */
function poke() {
  if (!S.root) return;
  S.root.classList.remove('hide-ui');
  clearTimeout(S.idle);
  S.idle = setTimeout(() => S.root && S.root.classList.add('hide-ui'), 2600);
}

function onKey(e) {
  if (!S.root || S.root.hidden) return;
  // ترکیب‌های مرورگر و ورودیِ IME دست‌نخورده بمانند
  if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
  const vid = S.els.stage.querySelector('video');
  const k = e.key;

  if (k === 'Escape') {
    if (document.fullscreenElement) return;   // اول از تمام‌صفحه بیرون
    e.preventDefault(); close(); return;
  }
  // راست‌چین: فلشِ راست یعنی «قبلی». روی ویدیو فلش‌ها مالِ پخش‌کننده‌اند
  // و ناوبری با Shift انجام می‌شود — همان قرارداد MediaViewer.
  const navKey = (k === 'ArrowRight') ? -1 : (k === 'ArrowLeft') ? 1 : 0;
  if (navKey && (!vid || e.shiftKey)) { e.preventDefault(); go(navKey); return; }
  if (!vid && (k === '+' || k === '=')) { e.preventDefault(); zoomBy(1.4); return; }
  if (!vid && k === '-') { e.preventDefault(); zoomBy(1 / 1.4); return; }
  if (!vid && k === '0') { e.preventDefault(); resetZoom(); return; }
  if (vid) videoKey(e, vid);
  poke();
}

function trap(e) {
  if (e.key !== 'Tab' || !S.root || S.root.hidden) return;
  const f = [...S.root.querySelectorAll(
    'button:not([disabled]):not([hidden]), a[href], [tabindex="0"], video')]
    .filter(x => x.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

function open(items, index) {
  shell();
  S.items = items;
  S.i = clamp(index || 0, 0, items.length - 1);
  S.dirX = 0;
  S.lastFocus = document.activeElement;

  const many = items.length > 1;
  S.els.count.hidden = !many;
  S.els.prev.hidden = !many;
  S.els.next.hidden = !many;
  const segged = many && items.length <= 12;   // بیش از این، سگمنت‌ها به خط‌های موییِ بی‌معنا می‌رسند
  S.els.segs.hidden = !segged;
  S.els.segs.innerHTML = segged ? items.map(() => '<div class="vw-seg"><i></i></div>').join('') : ''

  S.root.hidden = false;
  document.body.style.overflow = 'hidden';
  document.addEventListener('keydown', trap, true);
  requestAnimationFrame(() => S.root.classList.add('in'));
  render();
  poke();
  S.root.querySelector('[data-close].vw-btn').focus();
}

function close() {
  if (!S.root || S.root.hidden) return;
  S.root.classList.remove('in');
  abort();
  clearTimeout(S.idle);
  document.removeEventListener('keydown', trap, true);
  const done = () => {
    S.root.hidden = true;
    S.els.stage.innerHTML = '';
    document.body.style.overflow = '';
    if (S.lastFocus && S.lastFocus.focus) S.lastFocus.focus();
  };
  // خروج کوتاه‌تر از ورود؛ با --vw-out در CSS یکی است
  setTimeout(done, S.reduce ? 0 : 160);
}

function abort() {
  if (S.ac) { S.ac.abort(); S.ac = null; }
  if (S.url) { URL.revokeObjectURL(S.url); S.url = null; }
}

function go(step) {
  if (S.items.length < 2) return;
  S.dirX = step;
  S.i = (S.i + step + S.items.length) % S.items.length;
  render();
  poke();
}

function chrome() {
  const it = S.items[S.i];
  const n = S.items.length;
  S.els.count.textContent = fa(S.i + 1) + ' / ' + fa(n);
  S.els.name.textContent = it.title || '';
  S.els.sub.textContent = it.sub || '';
  S.els.cap.textContent = it.caption || '';
  if (!S.els.segs.hidden) {
    [...S.els.segs.children].forEach((s, k) => {
      s.className = 'vw-seg' + (k < S.i ? ' done' : k === S.i ? ' now' : '');
    });
  }
  S.els.zoom.hidden = true;
  S.els.dl.hidden = true;
}

async function render() {
  abort();
  chrome();
  const it = S.items[S.i];
  const stage = S.els.stage;
  stage.style.setProperty('--vw-dx', (S.dirX ? -S.dirX * 40 : 0) + 'px');

  // عکسی که همین‌جا در دست است (آواتار) نباید حتی یک فریم تاخیر بگیرد
  if (it.src) { showImage(it.src, it); return; }

  const panel = document.createElement('div');
  panel.className = 'vw-panel vw-swap';
  panel.innerHTML =
    '<svg class="vw-ring" viewBox="0 0 80 80">' +
      '<circle class="bg" cx="40" cy="40" r="34"/>' +
      '<circle class="fg" cx="40" cy="40" r="34"/></svg>' +
    '<div class="vw-pct">…</div>' +
    '<div class="vw-sub">در حال گرفتن رسانه</div>';
  stage.replaceChildren(panel);

  const ring = panel.querySelector('.fg');
  const C = 2 * Math.PI * 34;
  ring.style.strokeDasharray = C;
  ring.style.strokeDashoffset = C;
  const pct = panel.querySelector('.vw-pct');
  const sub = panel.querySelector('.vw-sub');

  try {
    const blob = await download(it.url, (got, total) => {
      // جداکننده‌ی اعشار فارسی «٫» است نه نقطه؛ نقطه کنار ارقام
      // فارسی مثل یک نویسه‌ی بیگانه می‌نشیند
      const mb = b => fa((b / 1048576).toFixed(1)).replace('.', '٫');
      if (total) {
        const r = got / total;
        ring.style.strokeDashoffset = C * (1 - r);
        pct.textContent = fa(Math.round(r * 100)) + '٪';
      } else {
        pct.textContent = mb(got) + ' م‌ب';
      }
      sub.textContent = total ? mb(got) + ' از ' + mb(total) + ' مگابایت' : 'در حال دریافت';
    });
    if (!blob) return;                       // لغو شده
    S.url = URL.createObjectURL(blob);
    const ext = (blob.type || '').startsWith('video') ? 'mp4' : 'jpg';
    S.els.dl.hidden = false;
    S.els.dl.href = S.url;
    S.els.dl.setAttribute('download', 'aine.' + ext);
    if ((blob.type || '').startsWith('video')) showVideo(S.url, it);
    else showImage(S.url, it);
  } catch (err) {
    if (err && err.name === 'AbortError') return;
    fail(String(err && err.message || err));
  }
}

/* دانلودِ تکه‌تکه با گزارش پیشرفت. استوریِ ویدیو چند مگابایت است و
   «چرخِ بی‌پایان» به کاربر نمی‌گوید کِی تمام می‌شود. */
async function download(url, onProgress) {
  S.ac = new AbortController();
  const res = await fetch(url, { credentials: 'same-origin', signal: S.ac.signal });
  if (!res.ok) {
    let why = 'رسانه گرفته نشد (' + fa(res.status) + ')';
    try {
      const j = await res.json();
      const d = j && j.detail;
      if (d && (d.error || d.tried)) why = [d.error, (d.tried || []).join(' · ')].filter(Boolean).join(' — ');
    } catch (_) { /* بدنه‌ی غیرJSON */ }
    throw new Error(why);
  }
  const total = +(res.headers.get('content-length') || 0);
  const type = res.headers.get('content-type') || '';
  if (!res.body) return new Blob([await res.arrayBuffer()], { type });

  const chunks = [];
  let got = 0, last = 0;
  const reader = res.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    // گزارش را throttle می‌کنیم؛ هر chunk یعنی ده‌ها رندر بی‌فایده
    const now = performance.now();
    if (now - last > 120) { last = now; onProgress(got, total); }
  }
  onProgress(got, total);
  return new Blob(chunks, { type });
}

function fail(msg) {
  const p = document.createElement('div');
  p.className = 'vw-panel vw-swap';
  p.innerHTML = '<div class="vw-sub" style="color:#ffb4ad">' + msg + '</div>';
  const b = document.createElement('button');
  b.className = 'vw-zoom';
  b.type = 'button';
  b.textContent = 'تلاش دوباره';
  b.addEventListener('click', render);
  p.appendChild(b);
  S.els.stage.replaceChildren(p);
}

/* ------------------------------------------------------------ عکس */

const T = { s: 1, x: 0, y: 0 };          // scale و جابه‌جایی
const MAXZ = 5;
let imgEl = null;

function applyT(dragY) {
  if (!imgEl) return;
  const ty = T.y + (dragY || 0);
  imgEl.style.transform = 'translate(' + T.x + 'px,' + ty + 'px) scale(' + T.s + ')';
  S.root.dataset.zoom = T.s > 1 ? '1' : '0';
  S.els.zoom.hidden = T.s === 1;
  S.els.zoom.textContent = fa(Math.round(T.s * 100)) + '٪';
}

function resetZoom() { T.s = 1; T.x = 0; T.y = 0; applyT(); }

/* زومِ لنگرزده: نقطه‌ای که زیر مکان‌نماست باید سرِ جایش بماند.
   x' = cx - k(cx - x) با k = مقیاسِ جدید/قدیم. بدون این، تصویر
   زیر انگشت «فرار می‌کند». */
function zoomAt(ns, cx, cy) {
  const prev = T.s;
  T.s = clamp(ns, 1, MAXZ);
  const k = T.s / prev;
  if (T.s === 1) { T.x = 0; T.y = 0; }
  else {
    T.x = cx - k * (cx - T.x);
    T.y = cy - k * (cy - T.y);
    const lim = (T.s - 1) * 320;
    T.x = clamp(T.x, -lim, lim);
    T.y = clamp(T.y, -lim, lim);
  }
  applyT();
}

function zoomBy(f) {
  const r = imgEl && imgEl.getBoundingClientRect();
  if (!r) return;
  zoomAt(T.s * f, 0, 0);
}

function showImage(src, it) {
  const img = document.createElement('img');
  img.className = 'vw-media vw-swap';
  img.alt = it.title || 'رسانه';
  img.src = src;
  img.draggable = false;
  S.els.stage.replaceChildren(img);
  imgEl = img;
  resetZoom();
  bindImage(img);
  if (it.src) {                            // آواتار: ذخیره‌ی مستقیم
    S.els.dl.hidden = false;
    S.els.dl.href = src;
    S.els.dl.setAttribute('download', 'avatar.jpg');
  }
}

function bindImage(img) {
  const ptr = new Map();
  let pinch = null, pan = null, dragY = 0;

  img.addEventListener('dblclick', e => {
    const r = img.getBoundingClientRect();
    if (T.s > 1) resetZoom();
    else zoomAt(2.5, e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2));
  });

  img.addEventListener('pointerdown', e => {
    img.setPointerCapture(e.pointerId);
    ptr.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (ptr.size === 2) {
      const [a, b] = [...ptr.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), s: T.s };
      pan = null;
    } else if (ptr.size === 1) {
      pan = { x: e.clientX, y: e.clientY, tx: T.x, ty: T.y };
      S.root.dataset.drag = '1';
    }
  });

  img.addEventListener('pointermove', e => {
    if (!ptr.has(e.pointerId)) return;
    ptr.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (ptr.size === 2 && pinch) {
      const [a, b] = [...ptr.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinch.d > 0) zoomAt(pinch.s * (d / pinch.d), 0, 0);
      return;
    }
    if (!pan) return;
    const dx = e.clientX - pan.x, dy = e.clientY - pan.y;
    if (T.s > 1) {
      const lim = (T.s - 1) * 320;
      T.x = clamp(pan.tx + dx, -lim, lim);
      T.y = clamp(pan.ty + dy, -lim, lim);
      applyT();
    } else if (dy > 0 && Math.abs(dx) < 90) {
      // کشیدن به پایین = بستن، با محوشدنِ تدریجی که می‌گوید دارد بسته می‌شود
      dragY = dy;
      applyT(dragY);
      S.els.scrim.style.opacity = String(clamp(1 - dy / 400, .35, 1));
    }
  });

  const up = e => {
    ptr.delete(e.pointerId);
    if (ptr.size < 2) pinch = null;
    if (ptr.size === 0) {
      const moved = pan ? { dx: e.clientX - pan.x, dy: e.clientY - pan.y } : { dx: 0, dy: 0 };
      pan = null;
      S.root.dataset.drag = '0';
      S.els.scrim.style.opacity = '';
      if (T.s === 1) {
        if (dragY > 110) { dragY = 0; close(); return; }
        // راست‌چین: کشیدن به چپ یعنی «بعدی»
        if (Math.abs(moved.dx) > 64 && Math.abs(moved.dy) < 80) go(moved.dx < 0 ? 1 : -1);
      }
      dragY = 0;
      applyT();
    }
  };
  img.addEventListener('pointerup', up);
  img.addEventListener('pointercancel', up);
}

/* ----------------------------------------------------------- ویدیو */

let vidIdle = 0;

function flash(box, text) {
  const f = document.createElement('div');
  f.className = 'vw-flash';
  f.textContent = text;
  box.appendChild(f);
  setTimeout(() => f.remove(), 560);
}

function showVideo(src, it) {
  imgEl = null;
  const box = document.createElement('div');
  box.className = 'vw-player vw-swap';
  box.innerHTML =
    '<video playsinline preload="auto"></video>' +
    '<div class="vw-spin" hidden></div>' +
    '<button class="vw-big" type="button" aria-label="پخش">' + PLAY + '</button>' +
    '<div class="vw-ctl">' +
      // نوار روی ردیف خودش: در قابِ باریکِ استوری، کنار دکمه‌ها
      // به چند ده پیکسل جمع می‌شد و عملاً غیرقابل‌کشیدن بود
      '<div class="vw-bar"><i class="track"></i><i class="buf"></i><i class="fill"></i>' +
        '<b></b><span class="vw-tip" hidden></span></div>' +
      '<div class="vw-row">' +
        '<button class="vw-btn play" type="button" aria-label="پخش">' + PLAY + '</button>' +
        '<button class="vw-btn b5" type="button" aria-label="۵ ثانیه عقب">' + svg(ICON.b5) + '</button>' +
        '<button class="vw-btn f5" type="button" aria-label="۵ ثانیه جلو">' + svg(ICON.f5) + '</button>' +
        '<span class="vw-time">۰:۰۰ / ۰:۰۰</span>' +
        '<span class="vw-gap"></span>' +
        '<button class="vw-btn mute" type="button" aria-label="بی‌صدا">' + svg(ICON.vol) + '</button>' +
        '<button class="vw-btn rate" type="button" aria-label="سرعت پخش" ' +
          'style="font:600 12px/1 Vazirmatn;width:auto;padding:0 10px">۱×</button>' +
        '<button class="vw-btn fs" type="button" aria-label="تمام‌صفحه">' + svg(ICON.full) + '</button>' +
      '</div>' +
    '</div>';
  S.els.stage.replaceChildren(box);

  const v = box.querySelector('video');
  const q = s => box.querySelector(s);
  const spin = q('.vw-spin'), big = q('.vw-big'), play = q('.vw-btn.play');
  const time = q('.vw-time'), bar = q('.vw-bar'), fill = q('.fill'), buf = q('.buf');
  const knob = q('.vw-bar b'), tip = q('.vw-tip');
  const mute = q('.vw-btn.mute'), rate = q('.vw-btn.rate');
  v.src = src;
  if (it.poster) v.poster = it.poster;

  const toggle = () => {
    if (v.paused) { v.play().catch(() => {}); flash(box, 'پخش'); }
    else { v.pause(); flash(box, 'مکث'); }
  };
  const seek = d => {
    v.currentTime = clamp(v.currentTime + d, 0, v.duration || 0);
    flash(box, (d > 0 ? '+' : '−') + fa(Math.abs(d)) + ' ثانیه');
  };
  const paint = () => {
    const dur = Number.isFinite(v.duration) ? v.duration : 0;
    const r = dur ? v.currentTime / dur : 0;
    fill.style.width = (r * 100) + '%';
    knob.style.insetInlineStart = (r * 100) + '%';
    time.textContent = mmss(v.currentTime) + ' / ' + mmss(dur);
  };

  big.addEventListener('click', toggle);
  play.addEventListener('click', toggle);
  q('.b5').addEventListener('click', () => seek(-5));
  q('.f5').addEventListener('click', () => seek(5));
  v.addEventListener('click', toggle);
  v.addEventListener('play', () => {
    box.classList.add('playing');
    play.innerHTML = PAUSE; play.setAttribute('aria-label', 'مکث');
  });
  v.addEventListener('pause', () => {
    box.classList.remove('playing');
    play.innerHTML = PLAY; play.setAttribute('aria-label', 'پخش');
  });
  v.addEventListener('waiting', () => { spin.hidden = false; });
  v.addEventListener('playing', () => { spin.hidden = true; });
  v.addEventListener('timeupdate', () => {
    if (!bar.classList.contains('dragging')) paint();
  });
  v.addEventListener('loadedmetadata', paint);
  v.addEventListener('progress', () => {
    if (!v.buffered.length || !v.duration) return;
    buf.style.width = (v.buffered.end(v.buffered.length - 1) / v.duration * 100) + '%';
  });

  mute.addEventListener('click', () => {
    v.muted = !v.muted;
    mute.innerHTML = svg(v.muted ? ICON.mute : ICON.vol);
    flash(box, v.muted ? 'بی‌صدا' : 'باصدا');
  });

  const SPEEDS = [1, 1.25, 1.5, 2, 0.5];
  let si = 0;
  rate.addEventListener('click', () => {
    si = (si + 1) % SPEEDS.length;
    v.playbackRate = SPEEDS[si];
    rate.textContent = fa(String(SPEEDS[si]).replace('.', '٫')) + '×';
  });

  const fsToggle = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (box.requestFullscreen) box.requestFullscreen();
  };
  q('.fs').addEventListener('click', fsToggle);

  // نوار جست‌وجو با pointer capture تا کشیدن بیرونِ نوار هم دنبال شود.
  // نوار ذاتاً چپ‌به‌راست است حتی داخل صفحه‌ی راست‌چین.
  const ratio = e => {
    const r = bar.getBoundingClientRect();
    return clamp((e.clientX - r.left) / r.width, 0, 1);
  };
  bar.addEventListener('pointerdown', e => {
    if (e.button) return;
    bar.setPointerCapture(e.pointerId);
    bar.classList.add('dragging');
    v.currentTime = ratio(e) * (v.duration || 0);
    paint();
  });
  bar.addEventListener('pointermove', e => {
    const r = ratio(e);
    tip.hidden = false;
    tip.textContent = mmss(r * (v.duration || 0));
    tip.style.insetInlineStart = (r * 100) + '%';
    if (!bar.classList.contains('dragging')) return;
    v.currentTime = r * (v.duration || 0);
    paint();
  });
  bar.addEventListener('pointerleave', () => { tip.hidden = true; });
  const stopDrag = e => {
    bar.classList.remove('dragging');
    if (bar.hasPointerCapture && bar.hasPointerCapture(e.pointerId)) {
      bar.releasePointerCapture(e.pointerId);
    }
  };
  bar.addEventListener('pointerup', stopDrag);
  bar.addEventListener('pointercancel', stopDrag);

  // کنترل‌ها هنگام پخش و بی‌حرکتی محو می‌شوند، مثل هر پخش‌کننده‌ی جدی
  const wake = () => {
    box.classList.remove('idle');
    clearTimeout(vidIdle);
    vidIdle = setTimeout(() => box.classList.add('idle'), 2400);
  };
  box.addEventListener('pointermove', wake);
  wake();
  v.play().catch(() => {});   // اگر مرورگر autoplay ندهد، مکث می‌ماند

  S.videoOps = { toggle, seek, v, box, mute, fsToggle };
}

function videoKey(e, v) {
  const o = S.videoOps;
  if (!o || o.v !== v) return;
  const k = e.key;
  if (k === ' ' || k === 'k' || k === 'K') { e.preventDefault(); o.toggle(); }
  else if (k === 'ArrowLeft') { e.preventDefault(); o.seek(-5); }
  else if (k === 'ArrowRight') { e.preventDefault(); o.seek(5); }
  else if (k === 'm' || k === 'M') { e.preventDefault(); o.mute.click(); }
  else if (k === 'f' || k === 'F') { e.preventDefault(); o.fsToggle(); }
}

/* ------------------------------------------------------ رابط عمومی */

window.Viewer = {
  open,
  close,
  image: (src, title, sub) => open([{ kind: 'image', src, title, sub }], 0),
};

/* واگذاری رویداد: بخش‌های نتیجه با innerHTML بازسازی می‌شوند و شنونده‌ی
   مستقیم با هر رندر از بین می‌رود. هر شبکه‌ی تصویر با data-gal شناخته
   می‌شود و فهرستش را app.js در Viewer.galleries می‌گذارد. */
window.Viewer.galleries = new Map();

document.addEventListener('click', e => {
  const cell = e.target.closest('[data-gi]');
  if (!cell) return;
  const host = cell.closest('[data-gal]');
  const list = host && window.Viewer.galleries.get(host.dataset.gal);
  if (!list || !list.length) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;   // باز کردن در تبِ جدید دستِ کاربر بماند
  e.preventDefault();
  open(list, +cell.dataset.gi || 0);
});

document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const t = e.target.closest('[data-gi]');
  if (!t) return;
  e.preventDefault();
  t.click();
});

})();
