// ویرایشگرِ عکس — «فوتوشاپِ وب».
// هر ویرایش یک «نسخهٔ ویرایش» (JSON) است؛ سرور آن را روی نسخهٔ پیش‌نمایش اجرا می‌کند و عکسِ اصلی دست نمی‌خورد.
// همین JSON را هوشِ مصنوعی هم می‌سازد (/api/docs/{id}/ai-edit) — صفحه و هوشِ مصنوعی یک زبان دارند.
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const rnd = (v, d = 4) => Math.round(v * 10 ** d) / 10 ** d;
const fa = n => Number(n).toLocaleString('fa-IR');
const clone = o => JSON.parse(JSON.stringify(o));
const store = (k, v) => { try { localStorage.setItem(k, v); } catch { /* حالتِ خصوصی */ } };
const load = k => { try { return localStorage.getItem(k); } catch { return null; } };

// ───────────── وضعیت ─────────────
let tools = null, health = null;
const P = {};                                  // کلید ⇒ تعریفِ لغزنده
let docs = [], doc = null;
let recipe = { adjust: {} };
let mode = 'normal';                           // normal | crop | heal | mask
let activeTab = 'adjust';
let bgView = '';                               // '' | '#000000' | '#ffffff' | 'checker'
let zoom1 = false;
let apiKey = load('photoKey') || '';
let lastUrl = null, originalUrl = null, showingBefore = false;
let renderInfo = null;
let presetState = null;                        // { base, index, key } — فیلترِ بعدی جای قبلی را می‌گیرد
let lookThumbs = {};
let cropAspect = null;                         // نسبتِ پیکسلیِ عرض به ارتفاع؛ null ⇒ آزاد
let healSize = 1.5, brushSize = 2, brushMode = 'add';
let maskCv = null, tintCv = null, maskDirty = false;
let hover = null, drag = null;
let lastHist = null;
const stage = $('#stage'), view = $('#view'), overlay = $('#overlay');

// ───────────── سرور ─────────────
async function api(path, opts = {}, retried = false) {
  const headers = new Headers(opts.headers || {});
  if (apiKey) headers.set('X-Api-Key', apiKey);
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401 && !retried) {
    const k = prompt('این سرور کلیدِ API می‌خواهد:');
    if (k) { apiKey = k.trim(); store('photoKey', apiKey); return api(path, opts, true); }
  }
  if (!res.ok) {
    let msg = '';
    try { msg = (await res.clone().json()).error; } catch { /* بدنهٔ غیرِ JSON */ }
    throw new Error(msg || `خطای ${res.status}`);
  }
  return res;
}
const withKey = u => apiKey ? u + (u.includes('?') ? '&' : '?') + 'key=' + encodeURIComponent(apiKey) : u;
const post = (o, method = 'POST') => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(o) });

let toastTimer = null;
function toast(msg, bad = false) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast' + (bad ? ' bad' : ''); t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, bad ? 7000 : 3500);
}
function busy(text) { $('#busy').hidden = !text; $('#busyText').textContent = text || ''; }

// ───────────── شروع ─────────────
init();

async function init() {
  bindUI();
  try {
    health = await (await api('/api/health')).json();
    tools = await (await api('/api/tools')).json();
  } catch (e) {
    toast('سرور در دسترس نیست: ' + e.message, true);
    return;
  }
  for (const p of tools.params) P[p.key] = p;
  buildGroups();
  buildLooks();
  showHealth();
  await loadLibrary();
  // پیوندِ مستقیم: #doc=<id>&tab=crop
  const hash = new URLSearchParams(location.hash.slice(1));
  const want = hash.get('doc') || load('photoLast');
  if (want && docs.some(d => d.id === want)) await openDoc(want);
  else if (docs[0]) await openDoc(docs[0].id);
  if (hash.get('tab') && $(`#tab-${hash.get('tab')}`)) setTab(hash.get('tab'));
}

function showHealth() {
  const chips = [];
  const ai = health.ai, bg = health.background.ai;
  chips.push([ai.configured ? 'ok' : 'warn', ai.configured ? 'هوشِ مصنوعی وصل' : 'هوشِ مصنوعی: فقط خودکار',
    ai.configured ? `${ai.baseUrl} — ${ai.models}` : 'کلیدِ API در appsettings.json (Photo:Ai:ApiKey) نیست؛ دکمهٔ هوشِ مصنوعی همان خودکارِ رایگان را اجرا می‌کند']);
  chips.push([bg.canRun ? 'ok' : 'warn', bg.canRun ? 'پس‌زمینه: سبک + هوشِ مصنوعی' : 'پس‌زمینه: روشِ سبک', bg.reason || 'BiRefNet آماده است']);
  if (health.memory?.freeMB) chips.push(['', `حافظهٔ آزاد ${fa(Math.round(health.memory.freeMB / 1024 * 10) / 10)}GB`, '']);
  $('#chips').innerHTML = '';
  for (const [cls, text, title] of chips) {
    const s = document.createElement('span');
    s.className = 'chip ' + cls; s.textContent = text; s.title = title;
    $('#chips').append(s);
  }
  if (!bg.canRun) {
    $('#bgAiNote').hidden = false;
    $('#bgAiNote').textContent = 'هوشِ مصنوعیِ پس‌زمینه این‌جا اجرا نمی‌شود: ' + bg.reason +
      '. روشِ سبک برای کالا روی زمینهٔ ساده (سفید، رنگی، استودیویی) خیلی خوب است؛ برای عکسِ شلوغ همین برنامه را روی سرورِ پرحافظه اجرا کنید.';
  }
  $('#aiState').textContent = ai.configured
    ? `سرویس: ${ai.baseUrl} — مدل‌ها: ${ai.models} — دورِ نگاه: ${fa(ai.maxRounds)}`
    : 'کلیدِ API تنظیم نشده (appsettings.json ⇐ Photo:Ai:ApiKey؛ مثلاً کلیدِ رایگانِ OpenRouter). بی کلید، این دکمه همان «خودکارِ» رایگان و بی‌اینترنت را اجرا می‌کند.';
  $('#upscale [data-u="2"]').disabled = $('#upscale [data-u="4"]').disabled = !health.upscale.installed;
}

// ───────────── کتابخانه ─────────────
async function loadLibrary() {
  docs = await (await api('/api/docs')).json();
  renderLibrary();
}

function renderLibrary() {
  $('#libCount').textContent = docs.length ? fa(docs.length) : '';
  const box = $('#lib');
  box.innerHTML = '';
  for (const d of docs) {
    const el = document.createElement('div');
    el.className = 'thumb' + (doc && d.id === doc.id ? ' on' : '');
    el.title = `${d.name} — ${d.width}×${d.height}`;
    el.innerHTML = '<img loading="lazy" alt=""><span class="name"></span><button class="del" title="پاک کردن">✕</button>';
    el.querySelector('img').src = withKey(`/api/docs/${d.id}/thumb`);
    el.querySelector('.name').textContent = d.name;
    el.onclick = () => openDoc(d.id);
    el.querySelector('.del').onclick = async e => {
      e.stopPropagation();
      if (!confirm(`«${d.name}» پاک شود؟ (فایلِ اصلی و همهٔ ویرایش‌هایش)`)) return;
      try {
        await api(`/api/docs/${d.id}`, { method: 'DELETE' });
        if (doc?.id === d.id) closeDoc();
        await loadLibrary();
      } catch (err) { toast(err.message, true); }
    };
    box.append(el);
  }
}

async function upload(files) {
  let last = null;
  for (const f of files) {
    if (!/^image\//.test(f.type) && !/\.(jpe?g|png|webp|bmp|tiff?)$/i.test(f.name)) { toast(`${f.name}: عکس نیست`, true); continue; }
    busy(`بارگذاریِ ${f.name}…`);
    try {
      const fd = new FormData();
      fd.append('file', f, f.name);
      last = await (await api('/api/docs', { method: 'POST', body: fd })).json();
    } catch (e) { toast(`${f.name}: ${e.message}`, true); }
  }
  busy('');
  await loadLibrary();
  if (last) openDoc(last.id);
}

async function openDoc(id) {
  await flushSave();
  if (maskCv) maskStop();
  let j;
  try { j = await (await api(`/api/docs/${id}`)).json(); } catch (e) { toast(e.message, true); return; }
  doc = j.doc;
  recipe = normalize(j.recipe);
  U.stack = []; U.i = -1; commit(true);
  if (originalUrl) URL.revokeObjectURL(originalUrl);
  originalUrl = null; presetState = null; cropAspect = null;
  for (const u of Object.values(lookThumbs)) URL.revokeObjectURL(u);
  lookThumbs = {};
  store('photoLast', id);
  $('#empty').hidden = true; $('#wrap').hidden = false;
  for (const b of ['#before', '#zoom', '#reset', '#export']) $(b).disabled = false;
  $('#autoNotes').textContent = ''; $('#aiOut').hidden = true;
  $('#bgReport').hidden = true;
  if (doc.mask) showMaskInfo(doc.mask);
  renderLibrary();
  syncUI();
  if (activeTab === 'looks') renderLookThumbs();
  requestRender(true);
}

function closeDoc() {
  doc = null;
  $('#wrap').hidden = true; $('#empty').hidden = false; $('#status').textContent = '';
  for (const b of ['#before', '#zoom', '#reset', '#export', '#undo', '#redo']) $(b).disabled = true;
}

// ───────────── نسخهٔ ویرایش، برگرداندن، ذخیره ─────────────
function normalize(r) { r = clone(r || {}); r.adjust = r.adjust || {}; return r; }
const getAdj = k => (k in recipe.adjust ? recipe.adjust[k] : P[k].default);
function setAdj(k, v) {
  const p = P[k];
  v = clamp(+v, p.min, p.max);
  if (!isFinite(v) || Math.abs(v - p.default) < 1e-9) delete recipe.adjust[k];
  else recipe.adjust[k] = rnd(v);
}

const U = { stack: [], i: -1 };
function commit(reset = false) {
  const s = JSON.stringify(recipe);
  if (reset) { U.stack = [s]; U.i = 0; }
  else {
    if (U.stack[U.i] === s) return;
    U.stack.splice(U.i + 1);
    U.stack.push(s);
    if (U.stack.length > 150) U.stack.shift();
    U.i = U.stack.length - 1;
    saveSoon();
  }
  $('#undo').disabled = U.i <= 0;
  $('#redo').disabled = U.i >= U.stack.length - 1;
}
function undo() { if (U.i > 0) { U.i--; restore(); } }
function redo() { if (U.i < U.stack.length - 1) { U.i++; restore(); } }
function restore() {
  recipe = JSON.parse(U.stack[U.i]);
  $('#undo').disabled = U.i <= 0;
  $('#redo').disabled = U.i >= U.stack.length - 1;
  syncUI(); saveSoon(); requestRender(true);
}

let saveTimer = null;
function saveSoon() { clearTimeout(saveTimer); saveTimer = setTimeout(save, 700); }
async function save() {
  saveTimer = null;
  if (!doc) return;
  try { await api(`/api/docs/${doc.id}/recipe`, post(recipe, 'PUT')); }
  catch (e) { toast('ذخیره نشد: ' + e.message, true); }
}
async function flushSave() { if (saveTimer) { clearTimeout(saveTimer); await save(); } }

// نسخه‌ای که الان نمایش داده می‌شود: در برش بی کادر (تا کلِ عکس دیده شود)، در روتوش و قلمِ ماسک بی هندسه (مختصات = عکسِ اصلی)
function viewRecipe() {
  const r = clone(recipe);
  if (mode === 'crop') {
    const c = r.crop || {};
    r.crop = { angle: c.angle || 0, flipH: !!c.flipH, flipV: !!c.flipV };
    delete r.output;
  }
  if (mode === 'heal' || mode === 'mask') { delete r.crop; delete r.output; delete r.adjust.distortion; }
  if (mode === 'mask') delete r.background;
  if (r.background?.remove && bgView) r.background.color = bgView === 'checker' ? 'transparent' : bgView;
  return r;
}

// ───────────── پیش‌نمایش ─────────────
let rendering = false, pending = null;
function requestRender(full = true) {
  if (!doc) return;
  pending = { full };
  if (!rendering) pump();
}

function previewMax(full) {
  const side = health?.previewSide || 1600;
  const screen = Math.round(Math.max(stage.clientWidth, stage.clientHeight) * (devicePixelRatio || 1));
  const m = zoom1 ? side : Math.min(side, Math.max(480, screen));
  return full ? m : Math.min(m, 800);
}

async function pump() {
  rendering = true;
  while (pending && doc) {
    const { full } = pending;
    pending = null;
    const id = doc.id;
    const slow = setTimeout(() => busy('در حال ساختن…'), 900);
    try {
      const res = await api(`/api/docs/${id}/render?max=${previewMax(full)}`, post(viewRecipe()));
      clearTimeout(slow); busy('');
      const blob = await res.blob();
      if (doc?.id !== id) continue;
      const url = URL.createObjectURL(blob);
      if (!showingBefore) await showImage(url);
      if (lastUrl) URL.revokeObjectURL(lastUrl);
      lastUrl = url;
      renderInfo = { w: +res.headers.get('X-Width'), h: +res.headers.get('X-Height'), ms: +res.headers.get('X-Render-Ms') };
      updateStatus();
      if (full && !pending) drawHistogram();
    } catch (e) {
      clearTimeout(slow); busy('');
      toast(e.message, true);
      break;
    }
  }
  rendering = false;
}

async function showImage(url) {
  view.src = url;
  try { await view.decode(); } catch { /* تصویرِ خراب */ }
  layout();
}

function layout() {
  const nw = view.naturalWidth, nh = view.naturalHeight;
  if (!nw || !doc) return;
  const dpr = devicePixelRatio || 1, pad = 18;
  const s = zoom1 ? 1 / dpr : Math.min((stage.clientWidth - pad * 2) / nw, (stage.clientHeight - pad * 2) / nh, 2);
  const w = Math.max(1, Math.round(nw * s)), h = Math.max(1, Math.round(nh * s));
  const wrap = $('#wrap');
  wrap.style.width = w + 'px'; wrap.style.height = h + 'px';
  overlay.width = Math.round(w * dpr); overlay.height = Math.round(h * dpr);
  drawOverlay();
}

function updateStatus() {
  if (!doc) return;
  const parts = [doc.name, `${fa(doc.width)}×${fa(doc.height)}`];
  if (showingBefore) parts.push('اصل (بی ویرایش)');
  else if (renderInfo) parts.push(`پیش‌نمایش ${fa(renderInfo.w)}×${fa(renderInfo.h)} در ${fa(renderInfo.ms)} میلی‌ثانیه`);
  if (mode === 'crop') parts.push('برش: کادر بکشید');
  if (mode === 'heal') parts.push('روتوش: روی لکه کلیک کنید');
  if (mode === 'mask') parts.push('قلمِ ماسک');
  $('#status').textContent = parts.join(' · ');
}

// قبل / بعد
async function beforeOn() {
  if (!doc || showingBefore) return;
  showingBefore = true;
  drawOverlay();
  try {
    if (!originalUrl) {
      const res = await api(`/api/docs/${doc.id}/original?max=${previewMax(true)}`);
      originalUrl = URL.createObjectURL(await res.blob());
    }
    if (showingBefore) { await showImage(originalUrl); updateStatus(); }
  } catch (e) { toast(e.message, true); }
}
async function beforeOff() {
  if (!showingBefore) return;
  showingBefore = false;
  if (lastUrl) await showImage(lastUrl);
  updateStatus();
}

// ───────────── هیستوگرام ─────────────
const histCv = document.createElement('canvas');
function drawHistogram() {
  if (!view.naturalWidth) return;
  const w = 256, h = Math.max(1, Math.round(256 * view.naturalHeight / view.naturalWidth));
  histCv.width = w; histCv.height = h;
  const g = histCv.getContext('2d', { willReadFrequently: true });
  g.drawImage(view, 0, 0, w, h);
  const d = g.getImageData(0, 0, w, h).data;
  const R = new Float32Array(256), G = new Float32Array(256), B = new Float32Array(256), L = new Float32Array(256);
  let n = 0;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] < 128) continue;
    R[d[i]]++; G[d[i + 1]]++; B[d[i + 2]]++;
    L[Math.round(0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2])]++;
    n++;
  }
  lastHist = { R, G, B, L, n };
  const c = $('#hist'), cg = c.getContext('2d'), W = c.width, H = c.height;
  cg.clearRect(0, 0, W, H);
  let max = 1;
  for (const a of [R, G, B]) for (let i = 2; i < 254; i++) max = Math.max(max, a[i]);
  cg.globalCompositeOperation = 'lighter';
  for (const [a, col] of [[R, 'rgba(230,60,60,.75)'], [G, 'rgba(60,200,80,.75)'], [B, 'rgba(70,110,255,.8)']]) {
    cg.fillStyle = col;
    cg.beginPath(); cg.moveTo(0, H);
    for (let i = 0; i < 256; i++) cg.lineTo(i / 255 * W, H - Math.min(1, a[i] / max) * (H - 4));
    cg.lineTo(W, H); cg.closePath(); cg.fill();
  }
  cg.globalCompositeOperation = 'source-over';
  // سوختگی و سیاهیِ کامل
  const clipS = n ? L[0] / n : 0, clipH = n ? L[255] / n : 0;
  cg.fillStyle = '#fff';
  if (clipS > 0.003) { cg.beginPath(); cg.moveTo(0, 0); cg.lineTo(12, 0); cg.lineTo(0, 12); cg.fill(); }
  if (clipH > 0.003) { cg.beginPath(); cg.moveTo(W, 0); cg.lineTo(W - 12, 0); cg.lineTo(W, 12); cg.fill(); }
  c.title = `هیستوگرام — سیاهِ کامل ${fa(rnd(clipS * 100, 1))}٪، سفیدِ کامل ${fa(rnd(clipH * 100, 1))}٪`;
  drawCurve();
}

// ───────────── لغزنده‌ها ─────────────
function buildGroups() {
  const box = $('#groups');
  box.innerHTML = '';
  for (const g of tools.groups) {
    const det = document.createElement('details');
    det.className = 'grp'; det.dataset.group = g.key; det.title = g.help;
    det.open = g.key === 'light' || g.key === 'color';
    det.innerHTML = '<summary><span class="dot"></span><span class="t"></span><button class="reset" title="همهٔ این گروه به حالتِ اول">بازنشانی</button></summary>';
    $('.t', det).textContent = g.title;
    $('.reset', det).onclick = e => {
      e.preventDefault();
      for (const p of tools.params) if (p.group === g.key) delete recipe.adjust[p.key];
      commit(); syncUI(); requestRender(true);
    };
    if (g.key === 'hsl') buildHsl(det);
    else for (const p of tools.params) if (p.group === g.key) det.append(slider(p));
    box.append(det);
    if (g.key === 'light') box.append(buildCurve());
  }
}

function slider(p, swatch) {
  const row = document.createElement('div');
  row.className = 'sl'; row.dataset.key = p.key;
  row.innerHTML = '<label></label><input type="number"><input type="range">';
  const [label, num, range] = [$('label', row), $('input[type=number]', row), $('input[type=range]', row)];
  label.textContent = p.title + (p.unit ? ` (${p.unit})` : '');
  if (swatch) { const s = document.createElement('span'); s.className = 'swatch'; s.style.background = swatch; label.prepend(s); }
  label.title = p.help + (p.photoshop ? `\nدر فتوشاپ/لایت‌روم: ${p.photoshop}` : '') + '\nدوبار کلیک: بازنشانی';
  for (const el of [num, range]) { el.min = p.min; el.max = p.max; el.step = p.step; }
  if (p.key === 'temperature') range.className = 'temp';
  if (p.key === 'tint') range.className = 'tint';
  if (p.key.endsWith('Hue') && p.group === 'grading') range.className = 'hue';
  range.oninput = () => { setAdj(p.key, range.value); syncSlider(p.key, true); presetTouched(); requestRender(false); };
  range.onchange = () => { commit(); requestRender(true); };
  num.onchange = () => { setAdj(p.key, num.value); syncSlider(p.key); commit(); requestRender(true); };
  const reset = () => { delete recipe.adjust[p.key]; syncSlider(p.key); commit(); requestRender(true); };
  label.ondblclick = reset; range.ondblclick = reset;
  return row;
}

function syncSlider(key, fromRange = false) {
  const row = $(`.sl[data-key="${key}"]`);
  if (!row) return;
  const p = P[key], v = getAdj(key);
  if (!fromRange) $('input[type=range]', row).value = v;
  $('input[type=number]', row).value = rnd(v, p.step < 1 ? 2 : 0);
  $('label', row).classList.toggle('changed', Math.abs(v - p.default) > 1e-9);
}

function buildHsl(det) {
  const tabs = document.createElement('div');
  tabs.className = 'hsl-tabs';
  const body = document.createElement('div');
  const kinds = [['Hue', 'فام'], ['Sat', 'اشباع'], ['Lum', 'روشنی']];
  for (const [k, t] of kinds) {
    const b = document.createElement('button');
    b.textContent = t; b.dataset.k = k;
    b.onclick = e => { e.preventDefault(); showKind(k); };
    tabs.append(b);
  }
  for (const band of tools.hslBands)
    for (const [k] of kinds) {
      const row = slider(P[band.key + k], `hsl(${band.hue},85%,55%)`);
      row.dataset.kind = k;
      body.append(row);
    }
  function showKind(k) {
    for (const b of $$('button', tabs)) b.classList.toggle('on', b.dataset.k === k);
    for (const r of $$('.sl', body)) r.hidden = r.dataset.kind !== k;
  }
  det.append(tabs, body);
  showKind('Sat');
}

// ───────────── منحنی ─────────────
let curveCh = 'rgb';
const CURVE_COLORS = { rgb: '#e8e8e8', red: '#ff5a5a', green: '#4ade80', blue: '#6c8dff' };

function buildCurve() {
  const det = document.createElement('details');
  det.className = 'grp'; det.dataset.group = 'curve';
  det.title = 'منحنیِ تُن (Curves)';
  det.innerHTML = `<summary><span class="dot"></span><span>منحنی (Curves)</span><button class="reset" title="منحنیِ همهٔ کانال‌ها صاف">بازنشانی</button></summary>
    <div class="seg" id="curveCh"><button data-c="rgb" class="on">RGB</button><button data-c="red">قرمز</button><button data-c="green">سبز</button><button data-c="blue">آبی</button></div>
    <div class="curve-box"><canvas class="curve" id="curve" width="512" height="512"></canvas></div>
    <p class="muted small">کلیک: نقطهٔ تازه · کشیدن: جابه‌جا · دوبار کلیک یا کشیدن به بیرون: حذف</p>`;
  $('.reset', det).onclick = e => { e.preventDefault(); delete recipe.curve; commit(); syncUI(); requestRender(true); };
  for (const b of $$('#curveCh button', det)) b.onclick = e => {
    e.preventDefault();
    curveCh = b.dataset.c;
    for (const x of $$('#curveCh button', det)) x.classList.toggle('on', x === b);
    drawCurve();
  };
  const cv = $('#curve', det);
  const val = e => {
    const r = cv.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width * 255, (1 - (e.clientY - r.top) / r.height) * 255];
  };
  // هنگامِ کشیدن نقطه‌ها این‌جا نگه داشته می‌شوند؛ نقطهٔ بیرون‌کشیده در نسخه نیست تا اثرِ حذفش دیده شود
  let dragI = -1, out = false, pts = null;
  const without = i => pts.filter((_, k) => k !== i);
  cv.addEventListener('pointerdown', e => {
    const [x, y] = val(e);
    pts = curvePoints();
    let best = -1, bd = 12;
    pts.forEach((p, i) => { const d = Math.hypot(p[0] - x, p[1] - y); if (d < bd) { bd = d; best = i; } });
    if (best < 0) {
      const np = [clamp(x, 0, 255), clamp(y, 0, 255)];
      pts.push(np);
      pts.sort((a, b) => a[0] - b[0]);
      best = pts.indexOf(np);
      setCurvePoints(pts);
    }
    dragI = best; out = false;
    cv.setPointerCapture(e.pointerId);
    drawCurve(); requestRender(false);
  });
  cv.addEventListener('pointermove', e => {
    if (dragI < 0) return;
    const [x, y] = val(e);
    const last = pts.length - 1;
    const lo = dragI === 0 ? 0 : pts[dragI - 1][0] + 1, hi = dragI === last ? 255 : pts[dragI + 1][0] - 1;
    out = dragI > 0 && dragI < last && (y < -25 || y > 280 || x < lo - 25 || x > hi + 25);
    pts[dragI] = [clamp(x, lo, hi), clamp(y, 0, 255)];
    setCurvePoints(out ? without(dragI) : pts);
    drawCurve(); requestRender(false);
  });
  const up = () => {
    if (dragI < 0) return;
    setCurvePoints(out ? without(dragI) : pts);
    dragI = -1; out = false; pts = null;
    commit(); drawCurve(); requestRender(true);
  };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', up);
  cv.addEventListener('dblclick', e => {
    const [x, y] = val(e), cur = curvePoints();
    const i = cur.findIndex((p, k) => k > 0 && k < cur.length - 1 && Math.hypot(p[0] - x, p[1] - y) < 12);
    if (i > 0) { cur.splice(i, 1); setCurvePoints(cur); commit(); drawCurve(); requestRender(true); }
  });
  det.addEventListener('toggle', drawCurve);
  return det;
}

function curvePoints(ch = curveCh) { return clone(recipe.curve?.[ch] || [[0, 0], [255, 255]]); }

function setCurvePoints(pts) {
  const p = pts.map(q => [rnd(q[0], 1), rnd(q[1], 1)]).sort((a, b) => a[0] - b[0]);
  const identity = p.length < 2 || p.every(q => Math.abs(q[0] - q[1]) < 0.01);
  recipe.curve = recipe.curve || {};
  if (identity) delete recipe.curve[curveCh]; else recipe.curve[curveCh] = p;
  if (!Object.keys(recipe.curve).length) delete recipe.curve;
  markGroups();
}

// همان منحنیِ نرم و یکنوای سرور (Fritsch–Carlson)
function spline(pts) {
  const p = pts.map(q => [q[0] / 255, q[1] / 255]).sort((a, b) => a[0] - b[0]);
  const n = p.length;
  if (n === 1) return () => p[0][1];
  const d = [], m = new Array(n);
  for (let i = 0; i < n - 1; i++) d.push((p[i + 1][1] - p[i][1]) / Math.max(1e-9, p[i + 1][0] - p[i][0]));
  m[0] = d[0]; m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
    const a = m[i] / d[i], b = m[i + 1] / d[i], h = a * a + b * b;
    if (h > 9) { const t = 3 / Math.sqrt(h); m[i] = t * a * d[i]; m[i + 1] = t * b * d[i]; }
  }
  return x => {
    if (x <= p[0][0]) return p[0][1];
    if (x >= p[n - 1][0]) return p[n - 1][1];
    let k = 0;
    while (k < n - 2 && x > p[k + 1][0]) k++;
    const h = p[k + 1][0] - p[k][0], t = (x - p[k][0]) / h, t2 = t * t, t3 = t2 * t;
    return (2 * t3 - 3 * t2 + 1) * p[k][1] + (t3 - 2 * t2 + t) * h * m[k] + (-2 * t3 + 3 * t2) * p[k + 1][1] + (t3 - t2) * h * m[k + 1];
  };
}

function drawCurve() {
  const cv = $('#curve');
  if (!cv || !cv.closest('details').open) return;
  const g = cv.getContext('2d'), W = cv.width, H = cv.height;
  g.clearRect(0, 0, W, H);
  if (lastHist) {
    const a = lastHist.L;
    let max = 1;
    for (let i = 2; i < 254; i++) max = Math.max(max, a[i]);
    g.fillStyle = 'rgba(255,255,255,.08)';
    g.beginPath(); g.moveTo(0, H);
    for (let i = 0; i < 256; i++) g.lineTo(i / 255 * W, H - Math.min(1, a[i] / max) * H * 0.9);
    g.lineTo(W, H); g.fill();
  }
  g.strokeStyle = 'rgba(255,255,255,.1)'; g.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    g.beginPath(); g.moveTo(i * W / 4, 0); g.lineTo(i * W / 4, H); g.stroke();
    g.beginPath(); g.moveTo(0, i * H / 4); g.lineTo(W, i * H / 4); g.stroke();
  }
  g.strokeStyle = 'rgba(255,255,255,.2)';
  g.beginPath(); g.moveTo(0, H); g.lineTo(W, 0); g.stroke();
  const drawOne = (ch, alpha) => {
    const pts = curvePoints(ch), f = spline(pts);
    g.strokeStyle = CURVE_COLORS[ch]; g.globalAlpha = alpha; g.lineWidth = 2.5;
    g.beginPath();
    for (let i = 0; i <= 128; i++) { const x = i / 128; g.lineTo(x * W, (1 - clamp(f(x), 0, 1)) * H); }
    g.stroke();
    g.globalAlpha = 1;
    return pts;
  };
  for (const ch of ['red', 'green', 'blue', 'rgb']) if (ch !== curveCh && recipe.curve?.[ch]) drawOne(ch, 0.35);
  const pts = drawOne(curveCh, 1);
  g.fillStyle = '#fff';
  for (const p of pts) { g.beginPath(); g.arc(p[0] / 255 * W, (1 - p[1] / 255) * H, 7, 0, Math.PI * 2); g.fill(); }
}

// ───────────── فیلترها ─────────────
function buildLooks() {
  const box = $('#looks');
  box.innerHTML = '';
  const none = { key: '', title: 'بی فیلتر', help: 'برگشت به پیش از فیلتر', recipe: null };
  for (const p of [none, ...tools.presets]) {
    const b = document.createElement('button');
    b.className = 'look'; b.dataset.key = p.key;
    b.innerHTML = '<div class="ph"></div><b></b><span></span>';
    $('b', b).textContent = p.title; $('span', b).textContent = p.help;
    b.onclick = () => applyPreset(p);
    box.append(b);
  }
}

function mergeRecipe(a, b) {
  const r = normalize(a);
  if (!b) return r;
  r.adjust = { ...r.adjust, ...(b.adjust || {}) };
  for (const k of ['curve', 'crop', 'spots', 'background', 'output']) if (b[k]) r[k] = clone(b[k]);
  return r;
}

function applyPreset(p) {
  if (!doc) return;
  const base = presetState && presetState.index === U.i ? presetState.base : clone(recipe);
  recipe = mergeRecipe(base, p.recipe);
  commit();
  presetState = p.key ? { base, index: U.i, key: p.key } : null;
  syncUI(); requestRender(true);
  if (p.recipe?.background?.remove) toast('پس‌زمینه برداشته می‌شود — در زبانهٔ «پس‌زمینه» لبه را روی رنگِ مخالف ببینید.');
}
function presetTouched() { if (presetState) presetState.index = -1; }

async function renderLookThumbs() {
  if (!doc) return;
  const id = doc.id;
  const base = presetState && presetState.index === U.i ? presetState.base : recipe;
  for (const b of $$('#looks .look')) {
    const p = b.dataset.key ? tools.presets.find(x => x.key === b.dataset.key) : null;
    const ph = $('.ph', b);
    const k = b.dataset.key || '_';
    if (!lookThumbs[k]) {
      if (doc?.id !== id || activeTab !== 'looks') return;
      const r = mergeRecipe(base, p?.recipe);
      delete r.output; delete r.crop;
      // پیش‌نمایشِ فیلترِ فروشگاهی بی ساختنِ ماسک (مگر از قبل باشد)
      if (r.background?.remove && !doc.hasMask) delete r.background;
      try {
        const res = await api(`/api/docs/${id}/render?max=220`, post(r));
        lookThumbs[k] = URL.createObjectURL(await res.blob());
      } catch { continue; }
    }
    ph.style.backgroundImage = `url(${lookThumbs[k]})`;
  }
  markLooks();
}
function markLooks() {
  const key = presetState && presetState.index === U.i ? presetState.key : null;
  for (const b of $$('#looks .look')) b.classList.toggle('on', !!key && b.dataset.key === key);
}

// ───────────── برش ─────────────
function cropRect() {
  const c = recipe.crop || {};
  let x = c.x ?? 0, y = c.y ?? 0;
  const w = c.w ?? 1, h = c.h ?? 1;
  if (c.flipH) x = 1 - x - w;           // قرینه بعد از برش است ⇒ کادر هم قرینه نمایش داده می‌شود
  if (c.flipV) y = 1 - y - h;
  return { x, y, w, h };
}
function setCropRect(d) {
  const c = recipe.crop = recipe.crop || {};
  let x = d.x, y = d.y;
  if (c.flipH) x = 1 - x - d.w;
  if (c.flipV) y = 1 - y - d.h;
  Object.assign(c, { x: rnd(clamp(x, 0, 0.99), 5), y: rnd(clamp(y, 0, 0.99), 5), w: rnd(d.w, 5), h: rnd(d.h, 5) });
  cleanCrop();
}
function cleanCrop() {
  const c = recipe.crop;
  if (!c) return;
  const full = (c.x ?? 0) <= 0 && (c.y ?? 0) <= 0 && (c.w ?? 1) >= 1 && (c.h ?? 1) >= 1;
  if (full) { delete c.x; delete c.y; delete c.w; delete c.h; }
  if (!c.angle) delete c.angle;
  if (!c.flipH) delete c.flipH;
  if (!c.flipV) delete c.flipV;
  if (!Object.keys(c).length) delete recipe.crop;
}

// نسبتِ عرض به ارتفاع در مختصاتِ ۰ تا ۱
const aspectNorm = () => cropAspect * (doc?.height || 1) / (doc?.width || 1);

function fitRect(r, anchor, handle) {
  // کادر در عکس بماند و نسبت (اگر هست) حفظ شود
  if (cropAspect) {
    const k = aspectNorm();
    if (handle.length === 2) {
      const availW = handle.includes('w') ? anchor.x : 1 - anchor.x, availH = handle.includes('n') ? anchor.y : 1 - anchor.y;
      let w = r.w, h = r.h;
      if (w / Math.max(h, 1e-6) > k) w = h * k; else h = w / k;
      if (w > availW) { w = availW; h = w / k; }
      if (h > availH) { h = availH; w = h * k; }
      r = { x: handle.includes('w') ? anchor.x - w : anchor.x, y: handle.includes('n') ? anchor.y - h : anchor.y, w, h };
    } else if (handle === 'n' || handle === 's') {
      let h = r.h, w = h * k;
      const cx = anchor.cx, maxW = 2 * Math.min(cx, 1 - cx);
      if (w > maxW) { w = maxW; h = w / k; }
      r = { x: cx - w / 2, y: handle === 'n' ? anchor.y - h : anchor.y, w, h };
    } else if (handle === 'e' || handle === 'w') {
      let w = r.w, h = w / k;
      const cy = anchor.cy, maxH = 2 * Math.min(cy, 1 - cy);
      if (h > maxH) { h = maxH; w = h * k; }
      r = { x: handle === 'w' ? anchor.x - w : anchor.x, y: cy - h / 2, w, h };
    }
  }
  const w = clamp(r.w, 0.02, 1), h = clamp(r.h, 0.02, 1);
  return { x: clamp(r.x, 0, 1 - w), y: clamp(r.y, 0, 1 - h), w, h };
}

function resizeCrop(s, handle, px, py) {
  let x0 = s.x, y0 = s.y, x1 = s.x + s.w, y1 = s.y + s.h;
  px = clamp(px, 0, 1); py = clamp(py, 0, 1);
  if (handle.includes('w')) x0 = px;
  if (handle.includes('e')) x1 = px;
  if (handle.includes('n')) y0 = py;
  if (handle.includes('s')) y1 = py;
  // لنگر: گوشه یا لبهٔ روبه‌رو
  const anchor = {
    x: handle.includes('w') ? s.x + s.w : handle.includes('e') ? s.x : s.x,
    y: handle.includes('n') ? s.y + s.h : handle.includes('s') ? s.y : s.y,
    cx: s.x + s.w / 2, cy: s.y + s.h / 2,
  };
  const r = { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) };
  // از روی لنگر رد شد ⇒ جهتِ دستگیره برعکس
  let hd = handle;
  if (handle.includes('w') && x0 > x1) hd = hd.replace('w', 'e');
  else if (handle.includes('e') && x1 < x0) hd = hd.replace('e', 'w');
  if (handle.includes('n') && y0 > y1) hd = hd.replace('n', 's');
  else if (handle.includes('s') && y1 < y0) hd = hd.replace('s', 'n');
  return fitRect(r, anchor, hd);
}

function setAspect(a) {
  cropAspect = a === 'free' ? null : a === 'orig' ? (doc ? doc.width / doc.height : 1) : +a;
  for (const b of $$('#aspects button'))
    b.classList.toggle('on', b.dataset.a === a || (a !== 'orig' && !!cropAspect && Math.abs(+b.dataset.a - cropAspect) < 0.01));
  if (!cropAspect || !doc) return;
  // بزرگ‌ترین کادرِ این نسبت دورِ مرکزِ کادرِ فعلی
  const cur = cropRect(), k = aspectNorm();
  let w = 1, h = 1 / k;
  if (h > 1) { h = 1; w = k; }
  const cx = cur.x + cur.w / 2, cy = cur.y + cur.h / 2;
  setCropRect({ x: clamp(cx - w / 2, 0, 1 - w), y: clamp(cy - h / 2, 0, 1 - h), w, h });
  commit(); drawOverlay();
}

function drawCrop(g, W, H) {
  const d = cropRect();
  const x = d.x * W, y = d.y * H, w = d.w * W, h = d.h * H;
  g.fillStyle = 'rgba(0,0,0,.55)';
  g.beginPath(); g.rect(0, 0, W, H); g.rect(x, y, w, h); g.fill('evenodd');
  g.strokeStyle = 'rgba(255,255,255,.35)'; g.lineWidth = 1;
  for (let i = 1; i < 3; i++) {
    g.beginPath(); g.moveTo(x + w * i / 3, y); g.lineTo(x + w * i / 3, y + h); g.stroke();
    g.beginPath(); g.moveTo(x, y + h * i / 3); g.lineTo(x + w, y + h * i / 3); g.stroke();
  }
  g.strokeStyle = '#fff'; g.lineWidth = 1.5;
  g.strokeRect(x, y, w, h);
  g.fillStyle = '#fff';
  for (const [hx, hy] of Object.values(cropHandles(d, W, H))) g.fillRect(hx - 5, hy - 5, 10, 10);
}
function cropHandles(d, W, H) {
  const x = d.x * W, y = d.y * H, w = d.w * W, h = d.h * H;
  return { nw: [x, y], n: [x + w / 2, y], ne: [x + w, y], e: [x + w, y + h / 2], se: [x + w, y + h], s: [x + w / 2, y + h], sw: [x, y + h], w: [x, y + h / 2] };
}

function cropDown(p) {
  const d = cropRect();
  const hs = cropHandles(d, p.W, p.H);
  const hit = Object.entries(hs).find(([, [hx, hy]]) => Math.hypot(hx - p.px, hy - p.py) < 14);
  if (hit) drag = { type: 'resize', handle: hit[0], start: d };
  else if (p.x > d.x && p.x < d.x + d.w && p.y > d.y && p.y < d.y + d.h) drag = { type: 'move', start: d, p0: p };
  else drag = { type: 'resize', handle: 'se', start: { x: p.x, y: p.y, w: 0, h: 0 }, fresh: true, p0: p };
}
function cropMove(p) {
  // کلیکِ بی‌کشیدن بیرونِ کادر، کادر را خراب نکند
  if (drag.fresh && Math.hypot(p.px - drag.p0.px, p.py - drag.p0.py) < 6) return;
  if (drag.type === 'move') {
    const s = drag.start;
    setCropRect({ x: clamp(s.x + p.x - drag.p0.x, 0, 1 - s.w), y: clamp(s.y + p.y - drag.p0.y, 0, 1 - s.h), w: s.w, h: s.h });
  } else {
    let handle = drag.handle;
    if (drag.fresh) handle = (p.y < drag.start.y ? 'n' : 's') + (p.x < drag.start.x ? 'w' : 'e');
    setCropRect(resizeCrop(drag.start, handle, p.x, p.y));
  }
  drawOverlay();
}

// ───────────── روتوش (ترمیمِ لکه) ─────────────
function drawSpots(g, W, H) {
  const m = Math.min(W, H);
  for (const s of recipe.spots || []) {
    g.beginPath(); g.arc(s.x * W, s.y * H, s.r * m, 0, Math.PI * 2);
    g.strokeStyle = 'rgba(0,0,0,.7)'; g.lineWidth = 3; g.stroke();
    g.strokeStyle = '#fff'; g.lineWidth = 1.2; g.stroke();
  }
  if (hover) {
    g.beginPath(); g.arc(hover.px, hover.py, healSize / 100 * m, 0, Math.PI * 2);
    g.strokeStyle = 'rgba(79,140,255,.95)'; g.lineWidth = 1.5; g.stroke();
  }
}
function healDown(p, e) {
  const m = Math.min(p.W, p.H);
  if (e.button === 2) {
    const spots = recipe.spots || [];
    const i = spots.findIndex(s => Math.hypot((s.x - p.x) * p.W, (s.y - p.y) * p.H) < s.r * m + 4);
    if (i >= 0) { spots.splice(i, 1); if (!spots.length) delete recipe.spots; commit(); syncHeal(); requestRender(true); }
    return;
  }
  (recipe.spots = recipe.spots || []).push({ x: rnd(p.x, 5), y: rnd(p.y, 5), r: rnd(healSize / 100, 5) });
  commit(); syncHeal(); drawOverlay(); requestRender(true);
}
function syncHeal() {
  const n = recipe.spots?.length || 0;
  $('#spotCount').textContent = n ? `${fa(n)} لکه` : 'هنوز لکه‌ای نیست';
  $('#spotUndo').disabled = $('#spotClear').disabled = !n;
}

// ───────────── پس‌زمینه ─────────────
const BG_DEFAULT = { remove: true, method: 'auto', color: '#ffffff', cleanup: -1, shadow: 0 };
let bgMemo = { ...BG_DEFAULT };
const bgNow = () => recipe.background || { ...bgMemo, remove: false };

function setBg(patch, render = true) {
  const b = { ...bgMemo, ...(recipe.background || {}), ...patch };
  bgMemo = { ...b, remove: true };
  if (b.remove) recipe.background = b; else delete recipe.background;
  commit(); syncBg();
  if (render) requestRender(true);
}

async function prepareBackground(force = false) {
  if (!doc) return false;
  const method = $('#bgMethod').value;
  busy(method === 'ai' ? 'ساختنِ ماسک با هوشِ مصنوعی — روی CPU یکی دو دقیقه…' : 'ساختنِ ماسک…');
  try {
    const j = await (await api(`/api/docs/${doc.id}/background?method=${method}&force=${force ? 1 : 0}`, { method: 'POST' })).json();
    doc.hasMask = true; doc.mask = j.mask;
    showBgReport(j);
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  } finally { busy(''); }
}

const METHOD_NAME = { quick: 'سبک (بی مدل)', ai: 'هوشِ مصنوعی (BiRefNet)', upload: 'دستی (قلم)', file: 'شفافیتِ خودِ فایل' };
function showMaskInfo(m) {
  const box = $('#bgReport');
  box.hidden = false;
  box.innerHTML = '';
  box.append(line(`ماسک: ${METHOD_NAME[m.method] || m.method}` + (m.confidence && m.method !== 'upload' && m.method !== 'file' ? ` — اطمینان ${fa(Math.round(m.confidence * 100))}٪` : '')));
  if (m.note) box.append(line(m.note, 'muted'));
}
function showBgReport(j) {
  showMaskInfo(j.mask);
  const e = j.edge, box = $('#bgReport');
  const b = document.createElement('b');
  b.className = e.clean ? 'ok' : 'warn';
  b.textContent = `لبه: نمرهٔ ${fa(Math.round(e.score))} از ۱۰۰ — هاله ${fa(e.haloPercent)}٪`;
  box.append(document.createElement('br'), b);
  box.append(line(`تمیزکاریِ خودکار: ${fa(e.cleanup)} (امتحان‌شده: ${e.tried.map(t => `${fa(t.cleanup)}⇐${fa(t.halo)}٪`).join('، ')}) — ${fa(j.seconds)} ثانیه`, 'muted'));
  if (!e.clean) box.append(line('لبه هنوز ته‌ماندهٔ زمینه دارد: «روی سیاه/سفید» ببینید و با قلمِ ماسک اصلاح کنید.', 'warn'));
}
function line(text, cls) { const d = document.createElement('div'); d.textContent = text; if (cls) d.className = cls; return d; }

function updateChecker() {
  $('#wrap').classList.toggle('checker', !!recipe.background?.remove && (bgView === 'checker' || (!bgView && recipe.background.color === 'transparent')));
}
function syncBg() {
  updateChecker();
  const b = bgNow();
  $('#bgOn').checked = !!recipe.background?.remove;
  $('#bgMethod').value = b.method || 'auto';
  for (const s of $$('#bgColors button')) s.classList.toggle('on', s.dataset.c === b.color);
  const auto = (b.cleanup ?? -1) < 0;
  $('#bgCleanAuto').checked = auto;
  $('#bgCleanRow').hidden = auto;
  $('#bgClean').value = $('#bgCleanNum').value = auto ? 50 : b.cleanup;
  $('#bgShadow').value = $('#bgShadowNum').value = b.shadow || 0;
}

// قلمِ ماسک: ماسکِ ذخیره‌شده در بوم؛ قرمز = پاک‌شده
async function maskStart() {
  if (!doc) return;
  let res;
  try { res = await api(`/api/docs/${doc.id}/mask`); }
  catch {
    if (!await prepareBackground(false)) return;
    res = await api(`/api/docs/${doc.id}/mask`);
  }
  const bmp = await createImageBitmap(await res.blob());
  const k = Math.min(1, 2400 / Math.max(bmp.width, bmp.height));
  const w = Math.round(bmp.width * k), h = Math.round(bmp.height * k);
  maskCv = document.createElement('canvas'); maskCv.width = w; maskCv.height = h;
  const mg = maskCv.getContext('2d', { willReadFrequently: true });
  mg.drawImage(bmp, 0, 0, w, h);
  tintCv = document.createElement('canvas'); tintCv.width = w; tintCv.height = h;
  const tg = tintCv.getContext('2d');
  const src = mg.getImageData(0, 0, w, h).data, t = tg.createImageData(w, h);
  for (let i = 0; i < src.length; i += 4) { t.data[i] = 255; t.data[i + 1] = 45; t.data[i + 2] = 45; t.data[i + 3] = 255 - src[i]; }
  tg.putImageData(t, 0, 0);
  maskDirty = false;
  $('#maskEdit').disabled = true; $('#maskSave').disabled = false; $('#maskCancel').disabled = false;
  setMode('mask');
}
function maskStop() {
  maskCv = tintCv = null; maskDirty = false;
  $('#maskEdit').disabled = false; $('#maskSave').disabled = true; $('#maskCancel').disabled = true;
  if (mode === 'mask') setMode(modeForTab(activeTab));
}
async function maskSave() {
  if (!maskCv) return;
  const blob = await new Promise(r => maskCv.toBlob(r, 'image/png'));
  busy('ذخیرهٔ ماسک…');
  try {
    const j = await (await api(`/api/docs/${doc.id}/mask`, { method: 'PUT', headers: { 'Content-Type': 'image/png' }, body: blob })).json();
    doc.hasMask = true; doc.mask = j.mask;
    showMaskInfo(j.mask);
    maskStop();
    setBg({ remove: true, method: 'auto' });   // auto ⇒ ماسکِ دستی نگه داشته می‌شود
    $('#bgMethod').value = 'auto';
  } catch (e) { toast(e.message, true); } finally { busy(''); }
}
function paint(a, b) {
  const w = maskCv.width, h = maskCv.height, r = brushSize / 100 * Math.min(w, h);
  for (const [ctx, style, op] of [
    [maskCv.getContext('2d'), brushMode === 'add' ? '#fff' : '#000', 'source-over'],
    [tintCv.getContext('2d'), 'rgb(255,45,45)', brushMode === 'add' ? 'destination-out' : 'source-over'],
  ]) {
    ctx.save();
    ctx.globalCompositeOperation = op; ctx.strokeStyle = style; ctx.lineCap = 'round'; ctx.lineWidth = r * 2;
    ctx.beginPath(); ctx.moveTo(a.x * w, a.y * h); ctx.lineTo(b.x * w + 0.01, b.y * h); ctx.stroke();
    ctx.restore();
  }
  maskDirty = true;
  drawOverlay();
}
function drawMask(g, W, H) {
  if (tintCv) { g.globalAlpha = 0.5; g.drawImage(tintCv, 0, 0, W, H); g.globalAlpha = 1; }
  if (hover) {
    g.beginPath(); g.arc(hover.px, hover.py, brushSize / 100 * Math.min(W, H), 0, Math.PI * 2);
    g.strokeStyle = brushMode === 'add' ? '#fff' : '#ff6b6b'; g.lineWidth = 1.5; g.stroke();
  }
}

// ───────────── خروجی ─────────────
const OUT_DEFAULT = { format: 'jpeg', quality: 90, longEdge: 0, square: false, padding: 0.06, upscale: 1, sharpen: 0 };
const outNow = () => ({ ...OUT_DEFAULT, ...(recipe.output || {}) });
function setOut(patch, render) {
  const o = { ...outNow(), ...patch };
  const same = Object.keys(OUT_DEFAULT).every(k => o[k] === OUT_DEFAULT[k]);
  if (same) delete recipe.output; else recipe.output = o;
  commit(); syncOut();
  if (render) requestRender(true);
}
function syncOut() {
  const o = outNow();
  for (const b of $$('#fmt button')) b.classList.toggle('on', b.dataset.f === o.format);
  $('#qualRow').hidden = o.format === 'png';
  $('#qual').value = $('#qualNum').value = o.quality;
  for (const b of $$('#longEdge button')) b.classList.toggle('on', +b.dataset.l === o.longEdge);
  $('#square').checked = o.square;
  $('#padRow').hidden = !o.square;
  $('#pad').value = $('#padNum').value = Math.round(o.padding * 100);
  for (const b of $$('#upscale button')) b.classList.toggle('on', +b.dataset.u === o.upscale);
  $('#upNote').hidden = o.upscale <= 1;
  $('#osharp').value = $('#osharpNum').value = o.sharpen;
  if (!doc) return;
  // اندازهٔ تقریبیِ خروجی
  const c = recipe.crop || {};
  let w = doc.width * (c.w ?? 1), h = doc.height * (c.h ?? 1);
  if (o.upscale > 1) { const k = Math.min(o.upscale, 4096 / Math.max(w, h)); w *= Math.max(1, k); h *= Math.max(1, k); }
  if (o.square) { const s = o.longEdge || Math.round(Math.max(w, h)); w = h = s; }
  else if (o.longEdge) { const k = o.longEdge / Math.max(w, h); w *= k; h *= k; }
  const fmt = recipe.background?.color === 'transparent' && o.format === 'jpeg' ? 'PNG (شفاف)' : o.format.toUpperCase();
  $('#outInfo').textContent = `خروجی ≈ ${fa(Math.round(w))}×${fa(Math.round(h))} ${fmt}`;
}

async function doExport() {
  if (!doc) return;
  await flushSave();
  busy(recipe.output?.upscale > 1 ? 'ساختنِ خروجی با بزرگ‌نمایی — ممکن است طول بکشد…' : 'ساختنِ خروجی در اندازهٔ اصلی…');
  try {
    const res = await api(`/api/docs/${doc.id}/export`, post(recipe));
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)"?/i.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : doc.name + '-edited.jpg';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    toast(`خروجی آماده شد: ${name} (${fa(Math.round(blob.size / 1024))} کیلوبایت)`);
  } catch (e) { toast(e.message, true); } finally { busy(''); }
}

// ───────────── خودکار و هوشِ مصنوعی ─────────────
async function runAuto() {
  if (!doc) return;
  busy('اندازه‌گیری…');
  try {
    const j = await (await api(`/api/docs/${doc.id}/auto`, { method: 'POST' })).json();
    recipe.adjust = { ...recipe.adjust, ...(j.recipe.adjust || {}) };
    commit(); syncUI(); requestRender(true);
    $('#autoNotes').textContent = j.notes.join(' ');
  } catch (e) { toast(e.message, true); } finally { busy(''); }
}

async function runAi() {
  if (!doc) return;
  await flushSave();
  const goal = $('#goal').value.trim();
  busy(health.ai.configured ? 'هوشِ مصنوعی دارد عکس را می‌بیند…' : 'تنظیمِ خودکار…');
  $('#aiRun').disabled = true;
  try {
    const j = await (await api(`/api/docs/${doc.id}/ai-edit`, post({ goal, recipe }))).json();
    recipe = normalize(j.recipe);
    commit(); syncUI(); requestRender(true);
    const box = $('#aiOut');
    box.hidden = false; box.innerHTML = '';
    box.append(line(j.notes));
    if (j.usedAi) {
      const models = [...new Set(j.steps.map(s => s.model))].join('، ');
      box.append(line(`مدل: ${models} — ${fa(j.steps.length)} دور — توکن: ${fa(j.promptTokens)} ورودی + ${fa(j.completionTokens)} خروجی — ${fa(rnd(j.steps.reduce((a, s) => a + s.seconds, 0), 1))} ثانیه`, 'muted'));
      for (const s of j.steps) if (s.notes) box.append(line(`دورِ ${fa(s.round)}${s.done ? ' (تأیید)' : ''}: ${s.notes}`, 'muted'));
    } else if (j.error) box.append(line('هوشِ مصنوعی استفاده نشد: ' + j.error, 'warn'));
  } catch (e) { toast(e.message, true); } finally { busy(''); $('#aiRun').disabled = false; }
}

// ───────────── لایهٔ رویِ عکس ─────────────
function drawOverlay() {
  const g = overlay.getContext('2d'), dpr = devicePixelRatio || 1;
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, overlay.width, overlay.height);
  if (showingBefore || !doc) return;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = overlay.width / dpr, H = overlay.height / dpr;
  if (mode === 'crop') drawCrop(g, W, H);
  else if (mode === 'heal') drawSpots(g, W, H);
  else if (mode === 'mask') drawMask(g, W, H);
}

function pos(e) {
  const r = overlay.getBoundingClientRect();
  const px = e.clientX - r.left, py = e.clientY - r.top;
  return { x: px / r.width, y: py / r.height, px, py, W: r.width, H: r.height };
}

overlay.addEventListener('pointerdown', e => {
  if (mode === 'normal' || showingBefore) return;
  const p = pos(e);
  overlay.setPointerCapture(e.pointerId);
  if (mode === 'crop') cropDown(p);
  else if (mode === 'heal') healDown(p, e);
  else if (mode === 'mask' && maskCv) { drag = { type: 'paint', last: p }; paint(p, p); }
});
overlay.addEventListener('pointermove', e => {
  const p = pos(e);
  hover = p;
  if (drag?.type === 'paint') { paint(drag.last, p); drag.last = p; return; }
  if (drag && mode === 'crop') { cropMove(p); return; }
  if (mode === 'heal' || mode === 'mask') drawOverlay();
});
const pointerEnd = () => {
  if (!drag) return;
  const t = drag.type;
  drag = null;
  if (mode === 'crop' && t !== 'paint') { commit(); syncOut(); }
};
overlay.addEventListener('pointerup', pointerEnd);
overlay.addEventListener('pointercancel', pointerEnd);
overlay.addEventListener('pointerleave', () => { hover = null; if (mode === 'heal' || mode === 'mask') drawOverlay(); });
overlay.addEventListener('contextmenu', e => { if (mode !== 'normal') e.preventDefault(); });

// ───────────── زبانه‌ها و حالت‌ها ─────────────
const modeForTab = t => (t === 'crop' ? 'crop' : t === 'heal' ? 'heal' : t === 'bg' && maskCv ? 'mask' : 'normal');

function setTab(t) {
  if (maskCv && t !== 'bg') {
    if (maskDirty && confirm('ماسکِ اصلاح‌شده ذخیره شود؟')) { maskSave(); }
    else maskStop();
  }
  activeTab = t;
  for (const b of $$('#tabs button')) b.classList.toggle('on', b.dataset.tab === t);
  for (const s of $$('.tab')) s.hidden = s.id !== 'tab-' + t;
  setMode(modeForTab(t));
  if (t === 'looks') renderLookThumbs();
  if (t === 'out') syncOut();
}

function setMode(m) {
  if (m === mode) { drawOverlay(); return; }
  mode = m;
  stage.classList.remove('mode-crop', 'mode-heal', 'mode-mask');
  if (m !== 'normal') stage.classList.add('mode-' + m);
  overlay.style.pointerEvents = m === 'normal' ? 'none' : 'auto';
  drag = null; hover = null;
  updateStatus(); drawOverlay();
  requestRender(true);
}

function markGroups() {
  for (const det of $$('#groups details.grp')) {
    const g = det.dataset.group;
    const changed = g === 'curve' ? !!recipe.curve : tools.params.some(p => p.group === g && Math.abs(getAdj(p.key) - p.default) > 1e-9);
    det.classList.toggle('changed', changed);
  }
}

function syncUI() {
  if (!tools) return;
  for (const p of tools.params) syncSlider(p.key);
  markGroups();
  drawCurve();
  const c = recipe.crop || {};
  $('#angle').value = $('#angleNum').value = c.angle || 0;
  $('#flipH').classList.toggle('primary', !!c.flipH);
  $('#flipV').classList.toggle('primary', !!c.flipV);
  syncHeal(); syncBg(); syncOut(); markLooks();
  drawOverlay();
}

// ───────────── اتصالِ دکمه‌ها ─────────────
function bindUI() {
  for (const inp of ['#open', '#open2']) $(inp).onchange = e => { upload([...e.target.files]); e.target.value = ''; };
  $('#undo').onclick = undo;
  $('#redo').onclick = redo;
  const before = $('#before');
  before.onpointerdown = beforeOn;
  before.onpointerup = before.onpointerleave = beforeOff;
  $('#zoom').onclick = () => {
    zoom1 = !zoom1;
    $('#zoom').textContent = zoom1 ? 'جا شدن' : '۱:۱';
    layout(); requestRender(true);
  };
  $('#reset').onclick = () => {
    if (!confirm('همهٔ تنظیم‌ها (نور، رنگ، برش، لکه‌ها، پس‌زمینه، خروجی) پاک شود؟')) return;
    recipe = { adjust: {} }; presetState = null;
    commit(); syncUI(); requestRender(true);
  };
  $('#export').onclick = $('#export2').onclick = doExport;
  $('#auto').onclick = runAuto;
  for (const b of $$('#tabs button')) b.onclick = () => setTab(b.dataset.tab);

  // برش
  for (const b of $$('#aspects button')) b.onclick = () => setAspect(b.dataset.a);
  const setAngle = (v, final) => {
    const c = recipe.crop = recipe.crop || {};
    c.angle = rnd(clamp(+v || 0, -45, 45), 2);
    $('#angle').value = $('#angleNum').value = c.angle;
    cleanCrop();
    if (final) commit();
    requestRender(final);
  };
  $('#angle').oninput = e => setAngle(e.target.value, false);
  $('#angle').onchange = e => setAngle(e.target.value, true);
  $('#angleNum').onchange = e => setAngle(e.target.value, true);
  $('#angle').ondblclick = () => setAngle(0, true);
  for (const [id, k] of [['#flipH', 'flipH'], ['#flipV', 'flipV']]) $(id).onclick = () => {
    const c = recipe.crop = recipe.crop || {};
    c[k] = !c[k];     // همان بخشِ بریده‌شده، فقط آینه‌ای
    cleanCrop(); commit(); syncUI(); requestRender(true);
  };
  $('#rot90').onclick = () => { if (cropAspect) setAspect(String(rnd(1 / cropAspect, 4))); else toast('اول یک نسبت انتخاب کنید.'); };
  $('#cropReset').onclick = () => {
    if (recipe.crop) { delete recipe.crop.x; delete recipe.crop.y; delete recipe.crop.w; delete recipe.crop.h; }
    cleanCrop(); commit(); syncUI(); requestRender(true);
  };

  // روتوش
  const setHeal = v => { healSize = clamp(+v || 1.5, 0.3, 8); $('#healSize').value = $('#healSizeNum').value = healSize; drawOverlay(); };
  $('#healSize').oninput = e => setHeal(e.target.value);
  $('#healSizeNum').onchange = e => setHeal(e.target.value);
  setHeal(healSize);
  $('#spotUndo').onclick = () => { recipe.spots?.pop(); if (!recipe.spots?.length) delete recipe.spots; commit(); syncHeal(); drawOverlay(); requestRender(true); };
  $('#spotClear').onclick = () => { delete recipe.spots; commit(); syncHeal(); drawOverlay(); requestRender(true); };

  // پس‌زمینه
  $('#bgOn').onchange = async e => {
    if (e.target.checked && doc && !doc.hasMask && !await prepareBackground(false)) { e.target.checked = false; return; }
    setBg({ remove: e.target.checked });
  };
  $('#bgMethod').onchange = async e => {
    const method = e.target.value;
    if (recipe.background?.remove) { if (await prepareBackground(true)) setBg({ method }); }
    else bgMemo.method = method;
  };
  $('#bgMake').onclick = async () => { if (await prepareBackground(false)) setBg({ remove: true, method: $('#bgMethod').value }); };
  $('#bgRedo').onclick = async () => { if (await prepareBackground(true)) setBg({ remove: true, method: $('#bgMethod').value }); };
  for (const s of $$('#bgColors button')) s.onclick = () => setBg({ color: s.dataset.c });
  $('#bgCustom').oninput = e => setBg({ color: e.target.value });
  for (const b of $$('#bgView button')) b.onclick = () => {
    bgView = b.dataset.v;
    for (const x of $$('#bgView button')) x.classList.toggle('on', x === b);
    updateChecker();
    if (bgView && !recipe.background?.remove) toast('اول «حذفِ پس‌زمینه» را روشن کنید.');
    requestRender(true);
  };
  $('#bgCleanAuto').onchange = e => setBg({ cleanup: e.target.checked ? -1 : +$('#bgClean').value });
  const cleanSet = (v, final) => {
    const b = { ...(recipe.background || bgMemo), cleanup: clamp(+v, 0, 100) };
    if (recipe.background) recipe.background = b;
    $('#bgCleanNum').value = b.cleanup;
    if (final) commit();
    requestRender(final);
  };
  $('#bgClean').oninput = e => cleanSet(e.target.value, false);
  $('#bgClean').onchange = e => cleanSet(e.target.value, true);
  $('#bgCleanNum').onchange = e => { $('#bgClean').value = e.target.value; cleanSet(e.target.value, true); };
  const shadowSet = (v, final) => {
    if (recipe.background) recipe.background.shadow = clamp(+v, 0, 100);
    bgMemo.shadow = clamp(+v, 0, 100);
    $('#bgShadowNum').value = bgMemo.shadow;
    if (final) commit();
    requestRender(final);
  };
  $('#bgShadow').oninput = e => shadowSet(e.target.value, false);
  $('#bgShadow').onchange = e => shadowSet(e.target.value, true);
  $('#bgShadowNum').onchange = e => { $('#bgShadow').value = e.target.value; shadowSet(e.target.value, true); };
  for (const b of $$('#brushMode button')) b.onclick = () => { brushMode = b.dataset.m; for (const x of $$('#brushMode button')) x.classList.toggle('on', x === b); };
  const setBrush = v => { brushSize = clamp(+v || 2, 0.3, 10); $('#brush').value = $('#brushNum').value = brushSize; drawOverlay(); };
  $('#brush').oninput = e => setBrush(e.target.value);
  $('#brushNum').onchange = e => setBrush(e.target.value);
  setBrush(brushSize);
  $('#maskEdit').onclick = maskStart;
  $('#maskSave').onclick = maskSave;
  $('#maskCancel').onclick = maskStop;

  // خروجی
  $('#storePreset').onclick = () => { const p = tools.presets.find(x => x.key === 'store'); if (p) applyPreset(p); };
  for (const b of $$('#fmt button')) b.onclick = () => setOut({ format: b.dataset.f }, false);
  $('#qual').oninput = e => { $('#qualNum').value = e.target.value; };
  $('#qual').onchange = e => setOut({ quality: +e.target.value }, false);
  $('#qualNum').onchange = e => setOut({ quality: clamp(+e.target.value, 30, 100) }, false);
  for (const b of $$('#longEdge button')) b.onclick = () => setOut({ longEdge: +b.dataset.l }, false);
  $('#square').onchange = e => setOut({ square: e.target.checked }, true);
  $('#pad').oninput = e => { $('#padNum').value = e.target.value; };
  $('#pad').onchange = e => setOut({ padding: +e.target.value / 100 }, true);
  $('#padNum').onchange = e => setOut({ padding: clamp(+e.target.value, 0, 40) / 100 }, true);
  for (const b of $$('#upscale button')) b.onclick = () => setOut({ upscale: +b.dataset.u }, false);
  $('#osharp').oninput = e => { $('#osharpNum').value = e.target.value; };
  $('#osharp').onchange = e => setOut({ sharpen: +e.target.value }, true);
  $('#osharpNum').onchange = e => setOut({ sharpen: clamp(+e.target.value, 0, 100) }, true);

  // هوشِ مصنوعی
  for (const b of $$('#goalChips button')) b.onclick = () => { $('#goal').value = b.textContent; };
  $('#aiRun').onclick = runAi;

  // کشیدن و رها کردن، چسباندن
  let depth = 0;
  window.addEventListener('dragenter', e => { if (e.dataTransfer?.types?.includes('Files')) { depth++; document.body.classList.add('dragging'); } });
  window.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; document.body.classList.remove('dragging'); } });
  window.addEventListener('dragover', e => e.preventDefault());
  window.addEventListener('drop', e => {
    e.preventDefault(); depth = 0; document.body.classList.remove('dragging');
    if (e.dataTransfer?.files?.length) upload([...e.dataTransfer.files]);
  });
  window.addEventListener('paste', e => {
    const files = [...(e.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'));
    if (files.length) upload(files);
  });

  // صفحه‌کلید (با e.code تا روی صفحه‌کلیدِ فارسی هم کار کند)
  document.addEventListener('keydown', e => {
    if (e.target.matches('input, textarea, select')) return;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.code === 'KeyZ') { e.preventDefault(); e.shiftKey ? redo() : undo(); }
    else if (mod && e.code === 'KeyY') { e.preventDefault(); redo(); }
    else if (e.code === 'Backslash' && !e.repeat) beforeOn();
    else if (e.code === 'Escape' && activeTab !== 'adjust') setTab('adjust');
  });
  document.addEventListener('keyup', e => { if (e.code === 'Backslash') beforeOff(); });
  window.addEventListener('resize', () => layout());
  window.addEventListener('beforeunload', () => { if (saveTimer) save(); });
  overlay.style.pointerEvents = 'none';
}

