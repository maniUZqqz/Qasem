// ویرایشگرِ ویدیو — «پریمیرِ وب».
// هر ویرایش یک «نسخهٔ ویرایش» (JSON) است؛ سرور آن را به زنجیرهٔ فیلترهای FFmpeg تبدیل می‌کند و فایلِ اصلی دست نمی‌خورد.
// همین JSON را هوشِ مصنوعی هم می‌سازد (/api/videos/{id}/ai-edit).
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const rnd = (v, d = 3) => Math.round(v * 10 ** d) / 10 ** d;
const fa = n => Number(n).toLocaleString('fa-IR');
const clone = o => JSON.parse(JSON.stringify(o));
const store = (k, v) => { try { localStorage.setItem(k, v); } catch { /* حالتِ خصوصی */ } };
const load = k => { try { return localStorage.getItem(k); } catch { return null; } };
const PREVIEW_DUR = 6, STRIP = 12;

// ───────────── وضعیت ─────────────
let tools = null, health = null;
const P = {};
let docs = [], doc = null;
let recipe = { adjust: {} };
let curT = 0;                              // زمانِ فعلی روی فایلِ اصلی (ثانیه)
let activeTab = 'color';
let apiKey = load('videoKey') || '';
let lastUrl = null, showingBefore = false, frameInfo = null;
let presetState = null, lookThumbs = {}, lookThumbsT = -1;
let selection = null, selectedCut = -1, pauses = null, pauseDbTouched = false;
let playJob = null, exportJob = null;
let stats = null;
let curveCh = 'rgb';

// ───────────── سرور ─────────────
async function api(path, opts = {}, retried = false) {
  const headers = new Headers(opts.headers || {});
  if (apiKey) headers.set('X-Api-Key', apiKey);
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401 && !retried) {
    const k = prompt('این سرور کلیدِ API می‌خواهد:');
    if (k) { apiKey = k.trim(); store('videoKey', apiKey); return api(path, opts, true); }
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

// ۷۵٫۲ ⇒ «۱:۱۵٫۲»؛ ورودی: «75.2» یا «1:15.2»
function fmtT(t, latin = false) {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60), s = t - m * 60;
  const txt = `${m}:${s < 10 ? '0' : ''}${s.toFixed(latin ? 2 : 1)}`;
  return latin ? txt : txt.replace(/\d/g, d => '۰۱۲۳۴۵۶۷۸۹'[d]).replace('.', '٫');
}
function parseT(s) {
  s = String(s).trim().replace(/[۰-۹]/g, d => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)).replace('٫', '.');
  if (!s) return NaN;
  return s.split(':').reduce((acc, p) => acc * 60 + parseFloat(p), 0);
}

// ───────────── شروع ─────────────
init();

async function init() {
  bindUI();
  try {
    health = await (await api('/api/health')).json();
    tools = await (await api('/api/tools')).json();
  } catch (e) { toast('سرور در دسترس نیست: ' + e.message, true); return; }
  for (const p of tools.params) P[p.key] = p;
  buildGroups();
  buildPresets();
  showHealth();
  await loadLuts();
  await loadLibrary();
  const hash = new URLSearchParams(location.hash.slice(1));
  const want = hash.get('video') || load('videoLast');
  if (want && docs.some(d => d.id === want)) await openDoc(want);
  else if (docs[0]) await openDoc(docs[0].id);
  if (hash.get('tab') && $(`#tab-${hash.get('tab')}`)) setTab(hash.get('tab'));
}

function showHealth() {
  const chips = [];
  chips.push([health.ffmpeg.available ? 'ok' : 'bad', health.ffmpeg.available ? 'FFmpeg آماده' : 'FFmpeg نیست!', health.ffmpeg.version || 'tools\\Install-FFmpeg.ps1']);
  chips.push([health.ai.configured ? 'ok' : 'warn', health.ai.configured ? 'هوشِ مصنوعی وصل' : 'هوشِ مصنوعی: فقط خودکار', health.ai.configured ? `${health.ai.baseUrl} — ${health.ai.models}` : 'کلیدِ API در appsettings.json (Video:Ai:ApiKey) نیست']);
  const gb = health.disk.freeMB / 1024;
  chips.push([gb < 3 ? 'warn' : '', `دیسک ${fa(rnd(gb, 1))}GB آزاد`, 'خروجی‌ها و پیش‌نمایش‌ها در data\\videos']);
  $('#chips').innerHTML = '';
  for (const [cls, text, title] of chips) {
    const s = document.createElement('span');
    s.className = 'chip ' + cls; s.textContent = text; s.title = title;
    $('#chips').append(s);
  }
  if (!health.ffmpeg.available) toast('FFmpeg پیدا نشد — tools\\Install-FFmpeg.ps1 را اجرا کنید.', true);
  $('#aiState').textContent = health.ai.configured
    ? `سرویس: ${health.ai.baseUrl} — مدل‌ها: ${health.ai.models} — دورِ نگاه: ${fa(health.ai.maxRounds)}`
    : 'کلیدِ API تنظیم نشده (appsettings.json ⇐ Video:Ai:ApiKey؛ مثلاً کلیدِ رایگانِ OpenRouter). بی کلید، این دکمه همان «خودکارِ» رایگان را اجرا می‌کند.';
}

// ───────────── کتابخانه ─────────────
async function loadLibrary() {
  docs = await (await api('/api/videos')).json();
  renderLibrary();
}

function renderLibrary() {
  $('#libCount').textContent = docs.length ? fa(docs.length) : '';
  const box = $('#lib');
  box.innerHTML = '';
  for (const d of docs) {
    const el = document.createElement('div');
    el.className = 'thumb' + (doc && d.id === doc.id ? ' on' : '');
    el.title = `${d.name} — ${d.media.width ? d.media.width + '×' + d.media.height + ' · ' : ''}${fmtT(d.media.duration)}`;
    el.innerHTML = (d.media.hasVideo ? '<img loading="lazy" alt="">' : '<div class="ico">🎵</div>') +
      '<span class="dur"></span><span class="name"></span><button class="del" title="پاک کردن">✕</button>';
    if (d.media.hasVideo) el.querySelector('img').src = withKey(`/api/videos/${d.id}/thumb`);
    el.querySelector('.name').textContent = d.name;
    el.querySelector('.dur').textContent = fmtT(d.media.duration);
    el.onclick = () => openDoc(d.id);
    el.querySelector('.del').onclick = async e => {
      e.stopPropagation();
      if (!confirm(`«${d.name}» پاک شود؟ (فایلِ اصلی، ویرایش‌ها و خروجی‌هایش)`)) return;
      try {
        await api(`/api/videos/${d.id}`, { method: 'DELETE' });
        if (doc?.id === d.id) closeDoc();
        await loadLibrary();
      } catch (err) { toast(err.message, true); }
    };
    box.append(el);
  }
}

// بارگذاریِ جریانی (بدنهٔ خام) با درصد
function uploadFile(f) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/videos?name=' + encodeURIComponent(f.name));
    if (apiKey) xhr.setRequestHeader('X-Api-Key', apiKey);
    xhr.upload.onprogress = e => { if (e.lengthComputable) busy(`بارگذاریِ ${f.name}: ${fa(Math.round(e.loaded / e.total * 100))}٪`); };
    xhr.onload = () => {
      let j = null;
      try { j = JSON.parse(xhr.responseText); } catch { /* */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(j); else reject(new Error(j?.error || `خطای ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error('اتصال قطع شد'));
    xhr.send(f);
  });
}

async function upload(files) {
  let last = null;
  for (const f of files) {
    if (!/^(video|audio)\//.test(f.type) && !/\.(mp4|mov|m4v|mkv|webm|avi|3gp|mts|m2ts|mp3|wav|m4a|aac|ogg|opus|flac)$/i.test(f.name)) { toast(`${f.name}: ویدیو یا صدا نیست`, true); continue; }
    try {
      busy(`بارگذاریِ ${f.name}…`);
      last = await uploadFile(f);
    } catch (e) { toast(`${f.name}: ${e.message}`, true); }
  }
  busy('');
  await loadLibrary();
  if (last) openDoc(last.id);
}

async function openDoc(id) {
  await flushSave();
  stopPlay();
  let j;
  try { j = await (await api(`/api/videos/${id}`)).json(); } catch (e) { toast(e.message, true); return; }
  doc = j.video;
  recipe = normalize(j.recipe);
  U.stack = []; U.i = -1; commit(true);
  presetState = null; lookThumbs = {}; lookThumbsT = -1; selection = null; selectedCut = -1; pauses = null; stats = null; pauseDbTouched = false;
  curT = Math.min(trimS() + 0.5, doc.media.duration / 2);
  store('videoLast', id);
  $('#empty').hidden = true;
  const hasV = doc.media.hasVideo;
  $('#frame').hidden = !hasV; $('#audioOnly').hidden = hasV;
  for (const b of ['#before', '#reset', '#export']) $(b).disabled = false;
  $('#before').disabled = !hasV;
  $('#autoNotes').textContent = ''; $('#aiOut').hidden = true; $('#pauseInfo').hidden = true; $('#applyPauses').disabled = true;
  $('#audioInfo').textContent = '«سنجشِ صدا» بلندی (LUFS)، کفِ نویز، وزوزِ برق و مکث‌ها را اندازه می‌گیرد.';
  // نوارِ فریم‌ها و موجِ صدا
  const strip = $('#strip');
  strip.innerHTML = '';
  if (hasV) for (let i = 0; i < STRIP; i++) { const im = document.createElement('img'); im.loading = 'lazy'; im.src = withKey(`/api/videos/${id}/strip/${i}`); strip.append(im); }
  const wave = $('#wave');
  wave.hidden = !doc.media.hasAudio;
  if (doc.media.hasAudio) wave.src = withKey(`/api/videos/${id}/waveform`);
  renderLibrary();
  syncUI();
  drawTimeline();
  requestFrame(true);
  loadJobs();
  if (activeTab === 'looks') renderLookThumbs();
}

function closeDoc() {
  stopPlay();
  doc = null;
  $('#frame').hidden = true; $('#audioOnly').hidden = true; $('#empty').hidden = false; $('#status').textContent = '';
  $('#strip').innerHTML = ''; $('#wave').hidden = true;
  for (const b of ['#before', '#reset', '#export', '#undo', '#redo']) $(b).disabled = true;
  drawTimeline();
}

// ───────────── نسخه، برگرداندن، ذخیره ─────────────
function normalize(r) { r = clone(r || {}); r.adjust = r.adjust || {}; return r; }
const getAdj = k => (k in recipe.adjust ? recipe.adjust[k] : P[k].default);
function setAdj(k, v) {
  const p = P[k];
  v = clamp(+v, p.min, p.max);
  if (!isFinite(v) || Math.abs(v - p.default) < 1e-9) delete recipe.adjust[k];
  else recipe.adjust[k] = rnd(v, 4);
}
const D = () => doc?.media.duration || 0;
const trimS = () => recipe.trim?.start || 0;
const trimE = () => (recipe.trim?.end > 0 ? Math.min(recipe.trim.end, D()) : D());
const speed = () => recipe.time?.speed || 1;

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
  syncUI(); saveSoon(); drawTimeline(); requestFrame(true);
}
let saveTimer = null;
function saveSoon() { clearTimeout(saveTimer); saveTimer = setTimeout(save, 700); }
async function save() {
  saveTimer = null;
  if (!doc) return;
  try { await api(`/api/videos/${doc.id}/recipe`, post(recipe, 'PUT')); } catch (e) { toast('ذخیره نشد: ' + e.message, true); }
}
async function flushSave() { if (saveTimer) { clearTimeout(saveTimer); await save(); } }

// نمایشِ قاب در زبانهٔ «قاب»: کلِ تصویر + کادرِ قاب (تا مرکزش را بشود جابه‌جا کرد)
const framing = () => activeTab === 'frame' && recipe.frame && recipe.frame.aspect !== 'original' && recipe.frame.fit === 'crop';
function viewRecipe() {
  const r = clone(recipe);
  if (framing()) delete r.frame;
  return r;
}

// ───────────── فریم ─────────────
let rendering = false, pending = null;
function requestFrame(full = true) {
  if (!doc || !doc.media.hasVideo) { updateStatus(); return; }
  pending = { full };
  if (!rendering) pump();
}
function frameMax(full) {
  const v = $('#viewer');
  const m = Math.round(Math.max(v.clientWidth, v.clientHeight) * (devicePixelRatio || 1));
  return full ? clamp(m, 480, 1600) : Math.min(560, m);
}
async function pump() {
  rendering = true;
  while (pending && doc) {
    const { full } = pending;
    pending = null;
    const id = doc.id;
    const slow = setTimeout(() => busy('در حال ساختن…'), 1200);
    try {
      const url = `/api/videos/${id}/frame?t=${curT.toFixed(3)}&max=${frameMax(full)}${showingBefore ? '&original=1' : ''}`;
      const res = await api(url, post(viewRecipe()));
      clearTimeout(slow); busy('');
      const blob = await res.blob();
      if (doc?.id !== id) continue;
      const u = URL.createObjectURL(blob);
      const img = $('#frame');
      img.src = u;
      try { await img.decode(); } catch { /* */ }
      if (lastUrl) URL.revokeObjectURL(lastUrl);
      lastUrl = u;
      frameInfo = { w: +res.headers.get('X-Width'), h: +res.headers.get('X-Height'), ms: +res.headers.get('X-Render-Ms') };
      updateStatus();
      drawOverlay();
      if (full && !pending) drawScope();
    } catch (e) {
      clearTimeout(slow); busy('');
      toast(e.message, true);
      break;
    }
  }
  rendering = false;
}

function updateStatus() {
  showTime();
  if (!doc) return;
  const m = doc.media;
  const parts = [doc.name];
  if (m.hasVideo) parts.push(`${fa(m.width)}×${fa(m.height)} · ${fa(rnd(m.fps, 2))} فریم`);
  if (showingBefore) parts.push('اصل (بی ویرایش)');
  else if (frameInfo) parts.push(`فریم در ${fa(frameInfo.ms)} میلی‌ثانیه`);
  if (framing()) parts.push('کادرِ قاب: کلیک کنید');
  $('#status').textContent = parts.join(' · ');
}
function showTime() {
  $('#time').textContent = doc ? `${fmtT(curT)} / ${fmtT(D())}` : '';
}

// لایهٔ رویِ فریم برای کادرِ قاب
function drawOverlay() {
  let ov = $('#ov');
  if (!framing() || $('#frame').hidden) { if (ov) ov.remove(); $('#viewer').classList.remove('focus-pick'); return; }
  const img = $('#frame'), vr = $('#viewer').getBoundingClientRect(), ir = img.getBoundingClientRect();
  if (!ov) {
    ov = document.createElement('canvas'); ov.id = 'ov';
    ov.style.cssText = 'position:absolute;pointer-events:none';
    $('#viewer').append(ov);
  }
  $('#viewer').classList.add('focus-pick');
  Object.assign(ov.style, { left: (ir.left - vr.left) + 'px', top: (ir.top - vr.top) + 'px', width: ir.width + 'px', height: ir.height + 'px' });
  const dpr = devicePixelRatio || 1;
  ov.width = Math.round(ir.width * dpr); ov.height = Math.round(ir.height * dpr);
  const g = ov.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = ir.width, H = ir.height;
  const r = frameRect(W, H);
  g.fillStyle = 'rgba(0,0,0,.6)';
  g.beginPath(); g.rect(0, 0, W, H); g.rect(r.x, r.y, r.w, r.h); g.fill('evenodd');
  g.strokeStyle = '#fff'; g.lineWidth = 1.5; g.strokeRect(r.x, r.y, r.w, r.h);
}
function aspectOf(a) { const [w, h] = String(a).split(':').map(Number); return w > 0 && h > 0 ? w / h : null; }
function frameRect(W, H) {
  const a = aspectOf(recipe.frame.aspect);
  const cw = Math.min(W, H * a), ch = Math.min(H, W / a);
  return { x: (W - cw) * (recipe.frame.focusX ?? 0.5), y: (H - ch) * (recipe.frame.focusY ?? 0.5), w: cw, h: ch };
}

// قبل / بعد
function beforeOn() { if (!doc || showingBefore) return; showingBefore = true; requestFrame(true); }
function beforeOff() { if (!showingBefore) return; showingBefore = false; requestFrame(true); }

// ───────────── خطِ زمان ─────────────
function tlGeom() {
  const c = $('#tlc'), r = c.getBoundingClientRect();
  return { c, W: r.width, H: r.height, left: r.left };
}
function drawTimeline() {
  const { c, W, H } = tlGeom();
  const dpr = devicePixelRatio || 1;
  c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  if (!doc) return;
  const d = D(), X = t => t / d * W;
  // بیرونِ بُرش
  g.fillStyle = 'rgba(0,0,0,.66)';
  g.fillRect(0, 0, X(trimS()), H);
  g.fillRect(X(trimE()), 0, W - X(trimE()), H);
  // بازه‌های حذف‌شده
  (recipe.cuts || []).forEach((c2, i) => {
    const x0 = X(c2.start), x1 = X(c2.end);
    g.fillStyle = i === selectedCut ? 'rgba(248,113,113,.7)' : 'rgba(248,113,113,.42)';
    g.fillRect(x0, 0, Math.max(1, x1 - x0), H);
    g.strokeStyle = 'rgba(0,0,0,.35)';
    for (let x = x0 - H; x < x1; x += 7) { g.beginPath(); g.moveTo(Math.max(x, x0), x < x0 ? (x0 - x) : 0); g.lineTo(Math.min(x + H, x1), x + H > x1 ? H - (x + H - x1) : H); g.stroke(); }
  });
  // مکث‌های پیدا‌شده (هنوز حذف نشده)
  if (pauses) {
    g.fillStyle = 'rgba(79,140,255,.28)';
    for (const p of pauses.cuts) g.fillRect(X(p.start), H - 10, Math.max(1, X(p.end) - X(p.start)), 10);
  }
  if (selection) {
    const a = Math.min(selection.a, selection.b), b = Math.max(selection.a, selection.b);
    g.fillStyle = 'rgba(79,140,255,.35)'; g.fillRect(X(a), 0, X(b) - X(a), H);
    g.strokeStyle = '#4f8cff'; g.strokeRect(X(a) + 0.5, 0.5, X(b) - X(a) - 1, H - 1);
  }
  // دستگیره‌های بُرش
  g.fillStyle = '#facc15';
  for (const [t, dir] of [[trimS(), 1], [trimE(), -1]]) {
    const x = X(t);
    g.fillRect(x - (dir > 0 ? 0 : 3), 0, 3, H);
    g.beginPath(); g.moveTo(x, 0); g.lineTo(x + 9 * dir, 0); g.lineTo(x, 12); g.fill();
  }
  // نشانگرِ زمان
  const px = X(curT);
  g.fillStyle = '#fff';
  g.fillRect(px - 1, 0, 2, H);
  g.beginPath(); g.moveTo(px - 6, 0); g.lineTo(px + 6, 0); g.lineTo(px, 8); g.fill();
}

let tlDrag = null;
function tlPointer(e) {
  const { W, left } = tlGeom();
  const x = clamp(e.clientX - left, 0, W);
  return { x, t: x / W * D() };
}
function bindTimeline() {
  const c = $('#tlc');
  c.addEventListener('pointerdown', e => {
    if (!doc) return;
    c.setPointerCapture(e.pointerId);
    const p = tlPointer(e), { W } = tlGeom();
    const xs = trimS() / D() * W, xe = trimE() / D() * W;
    if (Math.abs(p.x - xs) < 9) tlDrag = { kind: 'in' };
    else if (Math.abs(p.x - xe) < 9) tlDrag = { kind: 'out' };
    else if (e.shiftKey) { tlDrag = { kind: 'sel' }; selection = { a: p.t, b: p.t }; }
    else {
      const i = (recipe.cuts || []).findIndex(k => p.t >= k.start && p.t <= k.end);
      selectedCut = i;
      if (i < 0) selection = null;
      tlDrag = { kind: 'scrub' };
      stopPlay();
      curT = p.t;
      requestFrame(false);
    }
    $('#delCut').disabled = selectedCut < 0;
    $('#cutSel').disabled = !selection || Math.abs(selection.b - selection.a) < 0.05;
    renderCuts();
    drawTimeline();
  });
  c.addEventListener('pointermove', e => {
    if (!tlDrag) return;
    const p = tlPointer(e);
    if (tlDrag.kind === 'in') { setTrim(Math.min(p.t, trimE() - 0.1), null); curT = trimS(); requestFrame(false); }
    else if (tlDrag.kind === 'out') { setTrim(null, Math.max(p.t, trimS() + 0.1)); curT = trimE() - 0.04; requestFrame(false); }
    else if (tlDrag.kind === 'sel') { selection.b = p.t; $('#cutSel').disabled = Math.abs(selection.b - selection.a) < 0.05; }
    else { curT = p.t; requestFrame(false); }
    drawTimeline(); showTime();
  });
  const end = () => {
    if (!tlDrag) return;
    const k = tlDrag.kind;
    tlDrag = null;
    if (k === 'in' || k === 'out') { commit(); syncTime(); }
    requestFrame(true);
  };
  c.addEventListener('pointerup', end);
  c.addEventListener('pointercancel', end);
}
function setTrim(s, e) {
  const start = s ?? trimS(), endT = e ?? trimE();
  const t = { start: rnd(clamp(start, 0, D() - 0.1)), end: endT >= D() - 0.01 ? 0 : rnd(clamp(endT, start + 0.1, D())) };
  if (t.start <= 0 && t.end <= 0) delete recipe.trim; else recipe.trim = t;
}
function addCut(a, b) {
  const cuts = [...(recipe.cuts || []), { start: rnd(Math.min(a, b)), end: rnd(Math.max(a, b)) }].sort((x, y) => x.start - y.start);
  const merged = [];
  for (const c of cuts) {
    if (merged.length && c.start <= merged[merged.length - 1].end + 0.001) merged[merged.length - 1].end = Math.max(merged[merged.length - 1].end, c.end);
    else merged.push({ ...c });
  }
  recipe.cuts = merged;
}

// ───────────── پخشِ پیش‌نمایش (MP4ِ کوچک از سرور) ─────────────
async function pollJob(id, onProgress) {
  for (;;) {
    const j = await (await api(`/api/jobs/${id}`)).json();
    if (onProgress) onProgress(j);
    if (['done', 'failed', 'cancelled'].includes(j.state)) return j;
    await new Promise(r => setTimeout(r, 350));
  }
}
async function togglePlay() {
  if (!doc) return;
  if (playJob || !$('#player').hidden) { stopPlay(); return; }
  await flushSave();
  const start = clamp(curT, trimS(), Math.max(trimS(), trimE() - 0.2));
  const btn = $('#play');
  btn.textContent = '… ساختن';
  try {
    const job = await (await api(`/api/videos/${doc.id}/preview?start=${start.toFixed(3)}&dur=${PREVIEW_DUR}`, post(recipe))).json();
    playJob = job.id;
    const j = await pollJob(job.id, x => { if (playJob === job.id) btn.textContent = `… ${fa(Math.round(x.progress * 100))}٪`; });
    if (playJob !== job.id) return;
    if (j.state !== 'done') { if (j.state === 'failed') toast(j.error || 'پیش‌نمایش ساخته نشد', true); stopPlay(); return; }
    const v = $('#player');
    v.src = withKey(`/api/jobs/${job.id}/file`);
    v.hidden = false; $('#frame').hidden = true;
    const ov = $('#ov'); if (ov) ov.remove();
    btn.textContent = '■ توقف';
    playJob = null;
    v.onended = () => stopPlay();
    v.ontimeupdate = () => { curT = Math.min(trimE(), start + v.currentTime * speed()); drawTimeline(); showTime(); };
    await v.play();
  } catch (e) { toast(e.message, true); stopPlay(); }
}
function stopPlay() {
  if (playJob) { api(`/api/jobs/${playJob}`, { method: 'DELETE' }).catch(() => { }); playJob = null; }
  const v = $('#player');
  if (!v.hidden) {
    v.pause(); v.removeAttribute('src'); v.load(); v.hidden = true;
    if (doc?.media.hasVideo) $('#frame').hidden = false;
    requestFrame(true);
  }
  $('#play').textContent = '▶ پخش';
}

// ───────────── اسکوپ‌ها (مثلِ Lumetri Scopes) ─────────────
let scopeKind = 'hist';
const scopeCv = document.createElement('canvas');
function drawScope() {
  const img = $('#frame'), c = $('#scope'), g = c.getContext('2d'), W = c.width, H = c.height;
  g.clearRect(0, 0, W, H);
  if (!img.naturalWidth || img.hidden) return;
  const w = 256, h = Math.max(1, Math.round(256 * img.naturalHeight / img.naturalWidth));
  scopeCv.width = w; scopeCv.height = h;
  const sg = scopeCv.getContext('2d', { willReadFrequently: true });
  sg.drawImage(img, 0, 0, w, h);
  const d = sg.getImageData(0, 0, w, h).data;
  if (scopeKind === 'hist') {
    const R = new Float32Array(256), G = new Float32Array(256), B = new Float32Array(256);
    for (let i = 0; i < d.length; i += 4) { R[d[i]]++; G[d[i + 1]]++; B[d[i + 2]]++; }
    let max = 1;
    for (const a of [R, G, B]) for (let i = 2; i < 254; i++) max = Math.max(max, a[i]);
    g.globalCompositeOperation = 'lighter';
    for (const [a, col] of [[R, 'rgba(230,60,60,.75)'], [G, 'rgba(60,200,80,.75)'], [B, 'rgba(70,110,255,.8)']]) {
      g.fillStyle = col; g.beginPath(); g.moveTo(0, H);
      for (let i = 0; i < 256; i++) g.lineTo(i / 255 * W, H - Math.min(1, a[i] / max) * (H - 4));
      g.lineTo(W, H); g.fill();
    }
    g.globalCompositeOperation = 'source-over';
    return;
  }
  const out = g.createImageData(W, H), o = out.data;
  const plot = (x, y, r, gg, b) => {
    x |= 0; y |= 0;
    if (x < 0 || y < 0 || x >= W || y >= H) return;
    const k = (y * W + x) * 4;
    o[k] = Math.min(255, o[k] + r); o[k + 1] = Math.min(255, o[k + 1] + gg); o[k + 2] = Math.min(255, o[k + 2] + b); o[k + 3] = 255;
  };
  if (scopeKind === 'wave') {
    // موج‌نما: هر ستونِ تصویر ⇒ ستونی از روشنایی‌ها (۰ پایین، ۱۰۰ IRE بالا)
    for (let y = 0; y < h; y++)
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4, l = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
        plot(x / w * W, (1 - l / 255) * (H - 1), 18, 40, 18);
      }
  } else {
    // برداری‌نما: فام و اشباع (Cb/Cr) در مختصاتِ قطبی
    const cx = W / 2, cy = H / 2, rad = H / 2 - 4;
    for (let i = 0; i < d.length; i += 4) {
      const r = d[i] / 255, gg = d[i + 1] / 255, b = d[i + 2] / 255;
      const yv = 0.2126 * r + 0.7152 * gg + 0.0722 * b;
      const cb = (b - yv) / 1.8556, cr = (r - yv) / 1.5748;
      plot(cx + cb * rad * 1.8, cy - cr * rad * 1.8, 30, 34, 30);
    }
  }
  g.putImageData(out, 0, 0);
  g.strokeStyle = 'rgba(255,255,255,.15)';
  if (scopeKind === 'wave') for (const p of [0, 0.25, 0.5, 0.75, 1]) { g.beginPath(); g.moveTo(0, p * (H - 1)); g.lineTo(W, p * (H - 1)); g.stroke(); }
  else {
    const cx = W / 2, cy = H / 2, rad = H / 2 - 4;
    g.beginPath(); g.arc(cx, cy, rad * 0.8, 0, Math.PI * 2); g.stroke();
    // خطِ رنگِ پوست (~۱۲۳ درجه)
    g.strokeStyle = 'rgba(250,200,120,.45)';
    g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.cos(-123 * Math.PI / 180 + Math.PI) * rad, cy + Math.sin(-123 * Math.PI / 180 + Math.PI) * rad); g.stroke();
  }
}

// ───────────── لغزنده‌ها ─────────────
function buildGroups() {
  const box = $('#groups');
  box.innerHTML = '';
  for (const g of tools.groups) {
    if (g.key === 'audio') continue;
    box.append(groupEl(g));
    if (g.key === 'light') box.append(buildCurve());
  }
  const ag = tools.groups.find(g => g.key === 'audio');
  $('#audioGroup').innerHTML = '';
  for (const p of tools.params) if (p.group === 'audio') $('#audioGroup').append(slider(p));
  if (ag) $('#audioGroup').title = ag.help;
}
function groupEl(g) {
  const det = document.createElement('details');
  det.className = 'grp'; det.dataset.group = g.key; det.title = g.help;
  det.open = g.key === 'light' || g.key === 'color';
  det.innerHTML = '<summary><span class="dot"></span><span class="t"></span><button class="reset" title="همهٔ این گروه به حالتِ اول">بازنشانی</button></summary>';
  $('.t', det).textContent = g.title;
  $('.reset', det).onclick = e => {
    e.preventDefault();
    for (const p of tools.params) if (p.group === g.key) delete recipe.adjust[p.key];
    commit(); syncUI(); requestFrame(true);
  };
  if (g.key === 'hsl') buildHsl(det);
  else for (const p of tools.params) if (p.group === g.key) det.append(slider(p));
  return det;
}
function slider(p, swatch) {
  const row = document.createElement('div');
  row.className = 'sl'; row.dataset.key = p.key;
  row.innerHTML = '<label></label><input type="number"><input type="range">';
  const [label, num, range] = [$('label', row), $('input[type=number]', row), $('input[type=range]', row)];
  label.textContent = p.title + (p.unit ? ` (${p.unit})` : '');
  if (swatch) { const s = document.createElement('span'); s.className = 'swatch'; s.style.background = swatch; label.prepend(s); }
  label.title = p.help + (p.premiere ? `\nدر پریمیر: ${p.premiere}` : '') + '\nدوبار کلیک: بازنشانی';
  for (const el of [num, range]) { el.min = p.min; el.max = p.max; el.step = p.step; }
  if (p.key === 'temperature') range.className = 'temp';
  if (p.key === 'tint') range.className = 'tint';
  if (p.key.endsWith('Hue') && p.group === 'grading') range.className = 'hue';
  const audio = p.group === 'audio';
  range.oninput = () => { setAdj(p.key, range.value); syncSlider(p.key, true); if (presetState) presetState.index = -1; if (!audio) requestFrame(false); };
  range.onchange = () => { commit(); if (!audio) requestFrame(true); };
  num.onchange = () => { setAdj(p.key, num.value); syncSlider(p.key); commit(); if (!audio) requestFrame(true); };
  const reset = () => { delete recipe.adjust[p.key]; syncSlider(p.key); commit(); if (!audio) requestFrame(true); };
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
  const tabs = document.createElement('div'); tabs.className = 'hsl-tabs';
  const body = document.createElement('div');
  const kinds = [['Hue', 'فام'], ['Sat', 'اشباع'], ['Lum', 'روشنی']];
  for (const [k, t] of kinds) {
    const b = document.createElement('button');
    b.textContent = t; b.dataset.k = k;
    b.onclick = e => { e.preventDefault(); show(k); };
    tabs.append(b);
  }
  for (const band of tools.hslBands)
    for (const [k] of kinds) { const row = slider(P[band.key + k], `hsl(${band.hue},85%,55%)`); row.dataset.kind = k; body.append(row); }
  function show(k) {
    for (const b of $$('button', tabs)) b.classList.toggle('on', b.dataset.k === k);
    for (const r of $$('.sl', body)) r.hidden = r.dataset.kind !== k;
  }
  det.append(tabs, body);
  show('Sat');
}

// ───────────── منحنی (همان ویرایشگرِ عکس) ─────────────
const CURVE_COLORS = { rgb: '#e8e8e8', red: '#ff5a5a', green: '#4ade80', blue: '#6c8dff' };
function buildCurve() {
  const det = document.createElement('details');
  det.className = 'grp'; det.dataset.group = 'curve';
  det.innerHTML = `<summary><span class="dot"></span><span>منحنی (RGB Curves)</span><button class="reset" title="منحنیِ همهٔ کانال‌ها صاف">بازنشانی</button></summary>
    <div class="seg" id="curveCh"><button data-c="rgb" class="on">RGB</button><button data-c="red">قرمز</button><button data-c="green">سبز</button><button data-c="blue">آبی</button></div>
    <canvas class="curve" id="curve" width="512" height="512"></canvas>
    <p class="muted small">کلیک: نقطهٔ تازه · کشیدن: جابه‌جا · دوبار کلیک یا کشیدن به بیرون: حذف</p>`;
  $('.reset', det).onclick = e => { e.preventDefault(); delete recipe.curve; commit(); syncUI(); requestFrame(true); };
  for (const b of $$('#curveCh button', det)) b.onclick = e => {
    e.preventDefault(); curveCh = b.dataset.c;
    for (const x of $$('#curveCh button', det)) x.classList.toggle('on', x === b);
    drawCurve();
  };
  const cv = $('#curve', det);
  const val = e => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) / r.width * 255, (1 - (e.clientY - r.top) / r.height) * 255]; };
  let dragI = -1, out = false, pts = null;
  const without = i => pts.filter((_, k) => k !== i);
  cv.addEventListener('pointerdown', e => {
    const [x, y] = val(e);
    pts = curvePoints();
    let best = -1, bd = 12;
    pts.forEach((p, i) => { const d = Math.hypot(p[0] - x, p[1] - y); if (d < bd) { bd = d; best = i; } });
    if (best < 0) { const np = [clamp(x, 0, 255), clamp(y, 0, 255)]; pts.push(np); pts.sort((a, b) => a[0] - b[0]); best = pts.indexOf(np); setCurvePoints(pts); }
    dragI = best; out = false;
    cv.setPointerCapture(e.pointerId);
    drawCurve(); requestFrame(false);
  });
  cv.addEventListener('pointermove', e => {
    if (dragI < 0) return;
    const [x, y] = val(e), last = pts.length - 1;
    const lo = dragI === 0 ? 0 : pts[dragI - 1][0] + 1, hi = dragI === last ? 255 : pts[dragI + 1][0] - 1;
    out = dragI > 0 && dragI < last && (y < -25 || y > 280 || x < lo - 25 || x > hi + 25);
    pts[dragI] = [clamp(x, lo, hi), clamp(y, 0, 255)];
    setCurvePoints(out ? without(dragI) : pts);
    drawCurve(); requestFrame(false);
  });
  const up = () => {
    if (dragI < 0) return;
    setCurvePoints(out ? without(dragI) : pts);
    dragI = -1; out = false; pts = null;
    commit(); drawCurve(); requestFrame(true);
  };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', up);
  cv.addEventListener('dblclick', e => {
    const [x, y] = val(e), cur = curvePoints();
    const i = cur.findIndex((p, k) => k > 0 && k < cur.length - 1 && Math.hypot(p[0] - x, p[1] - y) < 12);
    if (i > 0) { cur.splice(i, 1); setCurvePoints(cur); commit(); drawCurve(); requestFrame(true); }
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
  g.strokeStyle = 'rgba(255,255,255,.1)'; g.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    g.beginPath(); g.moveTo(i * W / 4, 0); g.lineTo(i * W / 4, H); g.stroke();
    g.beginPath(); g.moveTo(0, i * H / 4); g.lineTo(W, i * H / 4); g.stroke();
  }
  g.strokeStyle = 'rgba(255,255,255,.2)'; g.beginPath(); g.moveTo(0, H); g.lineTo(W, 0); g.stroke();
  const one = (ch, alpha) => {
    const pts = curvePoints(ch), f = spline(pts);
    g.strokeStyle = CURVE_COLORS[ch]; g.globalAlpha = alpha; g.lineWidth = 2.5;
    g.beginPath();
    for (let i = 0; i <= 128; i++) { const x = i / 128; g.lineTo(x * W, (1 - clamp(f(x), 0, 1)) * H); }
    g.stroke(); g.globalAlpha = 1;
    return pts;
  };
  for (const ch of ['red', 'green', 'blue', 'rgb']) if (ch !== curveCh && recipe.curve?.[ch]) one(ch, 0.35);
  g.fillStyle = '#fff';
  for (const p of one(curveCh, 1)) { g.beginPath(); g.arc(p[0] / 255 * W, (1 - p[1] / 255) * H, 7, 0, Math.PI * 2); g.fill(); }
}

// ───────────── پریست‌ها ─────────────
function mergeRecipe(a, b) {
  const r = normalize(a);
  if (!b) return r;
  r.adjust = { ...r.adjust, ...(b.adjust || {}) };
  for (const k of ['trim', 'cuts', 'time', 'curve', 'lut', 'crop', 'frame', 'stabilize', 'audio', 'output']) if (b[k]) r[k] = clone(b[k]);
  return r;
}
function buildPresets() {
  const looks = $('#looks');
  looks.innerHTML = '';
  const none = { key: '', title: 'بی پریست', help: 'برگشت به پیش از پریستِ رنگ', recipe: null, kind: 'look' };
  for (const p of [none, ...tools.presets.filter(p => p.kind === 'look')]) {
    const b = document.createElement('button');
    b.className = 'look'; b.dataset.key = p.key;
    b.innerHTML = '<div class="ph"></div><b></b><span></span>';
    $('b', b).textContent = p.title; $('span', b).textContent = p.help;
    b.onclick = () => applyPreset(p);
    looks.append(b);
  }
  for (const [box, kinds] of [['#audioPresets', ['audio']], ['#outPresets', ['output']], ['#outPresets2', ['output']]]) {
    $(box).innerHTML = '';
    for (const p of tools.presets.filter(p => kinds.includes(p.kind))) {
      const b = document.createElement('button');
      b.className = 'card';
      b.innerHTML = '<b></b><span></span>';
      $('b', b).textContent = p.title; $('span', b).textContent = p.help;
      b.onclick = () => applyPreset(p);
      $(box).append(b);
    }
  }
}
function applyPreset(p) {
  if (!doc) return;
  if (p.kind === 'look' || !p.key) {
    const base = presetState && presetState.index === U.i ? presetState.base : clone(recipe);
    recipe = mergeRecipe(base, p.recipe);
    commit();
    presetState = p.key ? { base, index: U.i, key: p.key } : null;
  } else {
    recipe = mergeRecipe(recipe, p.recipe);
    commit();
    toast(`«${p.title}» اعمال شد.`);
  }
  syncUI(); drawTimeline(); requestFrame(true);
}
async function renderLookThumbs() {
  if (!doc?.media.hasVideo) return;
  const id = doc.id;
  if (Math.abs(lookThumbsT - curT) > 0.01) { for (const u of Object.values(lookThumbs)) URL.revokeObjectURL(u); lookThumbs = {}; lookThumbsT = curT; }
  const base = presetState && presetState.index === U.i ? presetState.base : recipe;
  for (const b of $$('#looks .look')) {
    const p = b.dataset.key ? tools.presets.find(x => x.key === b.dataset.key) : null;
    const k = b.dataset.key || '_';
    if (!lookThumbs[k]) {
      if (doc?.id !== id || activeTab !== 'looks') return;
      const r = mergeRecipe(base, p?.recipe);
      delete r.frame;
      try {
        const res = await api(`/api/videos/${id}/frame?t=${curT.toFixed(3)}&max=240`, post(r));
        lookThumbs[k] = URL.createObjectURL(await res.blob());
      } catch { continue; }
    }
    $('.ph', b).style.backgroundImage = `url(${lookThumbs[k]})`;
  }
  markLooks();
}
function markLooks() {
  const key = presetState && presetState.index === U.i ? presetState.key : null;
  for (const b of $$('#looks .look')) b.classList.toggle('on', !!key && b.dataset.key === key);
}

// ───────────── LUT ─────────────
async function loadLuts() {
  try {
    const luts = await (await api('/api/luts')).json();
    const sel = $('#lutFile'), cur = sel.value;
    sel.innerHTML = '<option value="">— بی LUT —</option>' + luts.map(l => `<option></option>`).join('');
    luts.forEach((l, i) => { sel.options[i + 1].value = l; sel.options[i + 1].textContent = l; });
    sel.value = cur;
  } catch { /* */ }
}
function setLut(patch) {
  const l = { file: recipe.lut?.file || '', mode: recipe.lut?.mode || 'look', amount: recipe.lut?.amount ?? 100, ...patch };
  if (!l.file || l.amount <= 0) delete recipe.lut; else recipe.lut = l;
  commit(); syncLut(); requestFrame(true);
}
function syncLut() {
  const l = recipe.lut;
  $('#lutFile').value = l?.file || '';
  for (const b of $$('#lutMode button')) b.classList.toggle('on', b.dataset.m === (l?.mode || 'look'));
  $('#lutAmount').value = $('#lutAmountNum').value = l?.amount ?? 100;
  $('#lutBox').classList.toggle('changed', !!l);
}

// ───────────── قاب ─────────────
function setFrame(patch) {
  const f = { aspect: 'original', fit: 'crop', focusX: 0.5, focusY: 0.5, ...(recipe.frame || {}), ...patch };
  if (f.aspect === 'original') delete recipe.frame; else recipe.frame = f;
  commit(); syncFrame(); requestFrame(true);
}
function syncFrame() {
  const f = recipe.frame || { aspect: 'original', fit: 'crop', focusX: 0.5, focusY: 0.5 };
  for (const b of $$('#aspect button')) b.classList.toggle('on', b.dataset.a === f.aspect);
  for (const b of $$('#fit button')) b.classList.toggle('on', b.dataset.f === f.fit);
  $('#fitRow').hidden = f.aspect === 'original';
  $('#focusRows').hidden = f.aspect === 'original' || f.fit !== 'crop';
  $('#focusX').value = $('#focusXNum').value = Math.round((f.focusX ?? 0.5) * 100);
  $('#focusY').value = $('#focusYNum').value = Math.round((f.focusY ?? 0.5) * 100);
  const c = recipe.crop || {};
  const L = (c.x || 0) * 100, T = (c.y || 0) * 100, R = (1 - (c.x || 0) - (c.w ?? 1)) * 100, B = (1 - (c.y || 0) - (c.h ?? 1)) * 100;
  for (const [id, v] of [['cropL', L], ['cropR', R], ['cropT', T], ['cropB', B]]) $('#' + id).value = $('#' + id + 'Num').value = rnd(Math.max(0, v), 1);
  $('#angle').value = $('#angleNum').value = c.angle || 0;
  $('#flipH').classList.toggle('primary', !!c.flipH);
  $('#flipV').classList.toggle('primary', !!c.flipV);
  $('#stabOn').checked = !!recipe.stabilize;
  $('#stabRow').hidden = !recipe.stabilize;
  $('#stab').value = $('#stabNum').value = recipe.stabilize?.amount ?? 50;
  drawOverlay();
}
function setCropEdges() {
  const L = clamp(+$('#cropL').value, 0, 45) / 100, R = clamp(+$('#cropR').value, 0, 45) / 100;
  const T = clamp(+$('#cropT').value, 0, 45) / 100, B = clamp(+$('#cropB').value, 0, 45) / 100;
  const c = { ...(recipe.crop || {}) };
  c.x = rnd(L, 4); c.y = rnd(T, 4); c.w = rnd(Math.max(0.05, 1 - L - R), 4); c.h = rnd(Math.max(0.05, 1 - T - B), 4);
  recipe.crop = c;
  cleanCrop();
}
function cleanCrop() {
  const c = recipe.crop;
  if (!c) return;
  if ((c.x || 0) <= 0 && (c.y || 0) <= 0 && (c.w ?? 1) >= 1 && (c.h ?? 1) >= 1) { delete c.x; delete c.y; delete c.w; delete c.h; }
  if (!c.angle) delete c.angle;
  if (!c.flipH) delete c.flipH;
  if (!c.flipV) delete c.flipV;
  if (!Object.keys(c).length) delete recipe.crop;
}

// ───────────── زمان ─────────────
function keepRanges() {
  const s = trimS(), e = trimE(), keep = [];
  let cur = s;
  for (const c of recipe.cuts || []) {
    if (c.end <= s || c.start >= e) continue;
    if (c.start > cur) keep.push([cur, c.start]);
    cur = Math.max(cur, c.end);
  }
  if (e > cur) keep.push([cur, e]);
  return keep;
}
const outDur = () => keepRanges().reduce((a, k) => a + k[1] - k[0], 0) / speed();
function syncTime() {
  $('#trimStart').value = fmtT(trimS(), true);
  $('#trimEnd').value = fmtT(trimE(), true);
  const sp = speed();
  $('#speed').value = $('#speedNum').value = sp;
  for (const b of $$('#speedChips button')) b.classList.toggle('on', Math.abs(+b.dataset.v - sp) < 0.001);
  $('#smooth').checked = !!recipe.time?.smooth;
  $('#smooth').disabled = sp >= 1;
  $('#fadeIn').value = $('#fadeInNum').value = recipe.time?.fadeIn || 0;
  $('#fadeOut').value = $('#fadeOutNum').value = recipe.time?.fadeOut || 0;
  if (doc) {
    const cutT = (recipe.cuts || []).reduce((a, c) => a + Math.max(0, Math.min(c.end, trimE()) - Math.max(c.start, trimS())), 0);
    const parts = [];
    if (cutT > 0) parts.push(`${fa(rnd(cutT, 1))} ثانیه حذف`);
    if (sp !== 1) parts.push(`سرعتِ ${fa(sp)}×`);
    $('#durInfo').textContent = `مدتِ اصلی ${fmtT(D())} ⇐ خروجی ${fmtT(outDur())}` + (parts.length ? ` (${parts.join('، ')})` : '');
  }
  renderCuts();
}
function setTime(patch) {
  const t = { speed: 1, smooth: false, fadeIn: 0, fadeOut: 0, ...(recipe.time || {}), ...patch };
  if (t.speed >= 1) t.smooth = false;
  if (t.speed === 1 && !t.fadeIn && !t.fadeOut) delete recipe.time; else recipe.time = t;
}
function renderCuts() {
  const box = $('#cutList');
  box.innerHTML = '';
  const cuts = recipe.cuts || [];
  if (!cuts.length) { box.innerHTML = '<span class="muted small">هنوز بازه‌ای حذف نشده. روی خطِ زمان Shift + کشیدن، یا «یافتنِ مکث‌ها».</span>'; return; }
  cuts.forEach((c, i) => {
    const el = document.createElement('div');
    el.className = 'cut' + (i === selectedCut ? ' on' : '');
    el.innerHTML = '<span></span><button title="رفتن به این‌جا">⌖</button><button title="برگرداندن">✕</button>';
    $('span', el).textContent = `${fmtT(c.start, true)} → ${fmtT(c.end, true)}  (${(c.end - c.start).toFixed(2)}s)`;
    const [go, del] = $$('button', el);
    go.onclick = () => { selectedCut = i; curT = c.start; $('#delCut').disabled = false; drawTimeline(); renderCuts(); requestFrame(true); };
    del.onclick = () => { recipe.cuts.splice(i, 1); if (!recipe.cuts.length) delete recipe.cuts; selectedCut = -1; commit(); syncTime(); drawTimeline(); };
    box.append(el);
  });
}
async function findPauses() {
  if (!doc?.media.hasAudio) { toast('این فایل صدا ندارد.', true); return; }
  busy('یافتنِ مکث‌ها…');
  try {
    // آستانه را اگر کاربر دست نزده، سرور از کفِ نویزِ همین فایل می‌گذارد
    const min = +$('#pauseMin').value;
    const q = pauseDbTouched ? `db=${$('#pauseDb').value}&min=${min}` : `min=${min}`;
    pauses = await (await api(`/api/videos/${doc.id}/pauses?${q}`, { method: 'POST' })).json();
    $('#pauseDb').value = $('#pauseDbNum').value = pauses.threshold;
    const box = $('#pauseInfo');
    box.hidden = false;
    box.textContent = pauses.cuts.length
      ? `${fa(pauses.cuts.length)} مکث پیدا شد (آستانهٔ ${fa(pauses.threshold)} dB${pauseDbTouched ? '' : '، خودکار از کفِ نویز'}) ⇐ ${fa(rnd(pauses.saved, 1))} ثانیه کوتاه‌تر (نوارِ آبی زیرِ خطِ زمان). «حذفِ همه» را بزنید.`
      : 'مکثِ بلندی پیدا نشد (آستانه را بالاتر یا کوتاه‌ترین مکث را کمتر کنید).';
    $('#applyPauses').disabled = !pauses.cuts.length;
    drawTimeline();
  } catch (e) { toast(e.message, true); } finally { busy(''); }
}

// ───────────── صدا ─────────────
function setAudio(patch) {
  const a = { mute: false, normalize: 0, hum: 0, ...(recipe.audio || {}), ...patch };
  if (!a.mute && !a.normalize && !a.hum) delete recipe.audio; else recipe.audio = a;
  commit(); syncAudio();
}
function syncAudio() {
  const a = recipe.audio || {};
  for (const b of $$('#norm button')) b.classList.toggle('on', +b.dataset.n === (a.normalize || 0));
  for (const b of $$('#hum button')) b.classList.toggle('on', +b.dataset.h === (a.hum || 0));
  $('#mute').checked = !!a.mute;
}
async function measure() {
  if (!doc) return;
  busy('سنجشِ تصویر و صدا…');
  try {
    const j = await (await api(`/api/videos/${doc.id}/analyze`)).json();
    stats = j.stats;
    showStats();
  } catch (e) { toast(e.message, true); } finally { busy(''); }
}
function showStats() {
  if (!stats) return;
  const s = stats, box = $('#audioInfo');
  const num = v => (typeof v === 'number' && isFinite(v) ? v : NaN);
  if (!s.hasAudio) { box.textContent = 'این فایل صدا ندارد.'; return; }
  const L = num(s.loudness), nf = num(s.noiseFloor);
  box.innerHTML = '';
  const line = (t, cls) => { const d = document.createElement('div'); d.textContent = t; if (cls) d.className = cls; box.append(d); };
  line(`بلندی: ${isFinite(L) ? fa(rnd(L, 1)) + ' LUFS' : '—'} (وب ‎−۱۴، پادکست ‎−۱۶، تلویزیون ‎−۲۳) · قله ${fa(rnd(num(s.truePeak), 1))} dBTP · محدودهٔ بلندی ${fa(rnd(num(s.loudnessRange), 1))} LU`,
    isFinite(L) && Math.abs(L + 14) > 3 ? 'warn' : '');
  line(`کفِ نویز: ${isFinite(nf) ? fa(rnd(nf, 1)) + ' dBFS' : '—'}${s.noiseSteady ? ' (نویزِ یکنواخت — کاهشِ نویز کمک می‌کند)' : ''}`, isFinite(nf) && nf > -55 ? 'warn' : '');
  line(s.hum ? `وزوزِ برقِ ${fa(s.hum)} هرتز پیدا شد` : 'وزوزِ برق: ندارد', s.hum ? 'warn' : '');
  line(`سکوت: ${fa(Math.round(num(s.silenceShare) || 0))}٪ از زمان در ${fa(s.silences?.length || 0)} مکث`);
}
async function runAuto(audioOnly) {
  if (!doc) return;
  busy('سنجش و تنظیمِ خودکار…');
  try {
    const j = await (await api(`/api/videos/${doc.id}/auto`, { method: 'POST' })).json();
    const a = j.recipe;
    for (const [k, v] of Object.entries(a.adjust || {})) if (!audioOnly || P[k]?.group === 'audio') recipe.adjust[k] = v;
    if (a.audio) recipe.audio = { ...(recipe.audio || {}), ...a.audio };
    commit(); syncUI(); requestFrame(true);
    $('#autoNotes').textContent = j.notes.join(' ');
    if (audioOnly) toast(j.notes.filter(n => /صدا|بلندی|نویز|وزوز|یکدست/.test(n)).join(' ') || 'صدا تنظیم شد.');
    measure();
  } catch (e) { toast(e.message, true); } finally { busy(''); }
}

// ───────────── خروجی ─────────────
const OUT_DEFAULT = { format: 'mp4', codec: 'h264', size: 0, fps: 0, quality: 'standard', broadcastSafe: false };
const outNow = () => ({ ...OUT_DEFAULT, ...(recipe.output || {}) });
function setOut(patch) {
  const o = { ...outNow(), ...patch };
  if (Object.keys(OUT_DEFAULT).every(k => o[k] === OUT_DEFAULT[k])) delete recipe.output; else recipe.output = o;
  commit(); syncOut();
}
function syncOut() {
  const o = outNow();
  for (const b of $$('#fmt button')) b.classList.toggle('on', b.dataset.f === o.format);
  for (const b of $$('#codec button')) b.classList.toggle('on', b.dataset.c === o.codec);
  for (const b of $$('#size button')) b.classList.toggle('on', +b.dataset.s === o.size);
  for (const b of $$('#fps button')) b.classList.toggle('on', +b.dataset.f === o.fps);
  for (const b of $$('#qual button')) b.classList.toggle('on', b.dataset.q === o.quality);
  const audioOut = o.format === 'mp3' || o.format === 'wav';
  $('#codecRow').hidden = o.format !== 'mp4';
  $('#sizeRow').hidden = $('#fpsRow').hidden = audioOut;
  $('#safeRow').hidden = !(o.format === 'mp4' || o.format === 'webm');
  $('#safe').checked = !!o.broadcastSafe;
  if (!doc) return;
  const m = doc.media;
  let info = `مدت ${fmtT(outDur())}`;
  if (!audioOut && m.hasVideo) {
    let w = m.width * (recipe.crop?.w ?? 1), h = m.height * (recipe.crop?.h ?? 1);
    const a = recipe.frame ? aspectOf(recipe.frame.aspect) : null;
    if (a) { if (recipe.frame.fit === 'crop') { const cw = Math.min(w, h * a), ch = Math.min(h, w / a); w = cw; h = ch; } else { const W = Math.max(w, h * a), H = Math.max(h, w / a); w = W; h = H; } }
    const s = o.size || (o.format === 'gif' ? 360 : 0);
    if (s) { const k = s / Math.min(w, h); w *= k; h *= k; }
    info += ` · ${fa(Math.round(w / 2) * 2)}×${fa(Math.round(h / 2) * 2)}`;
  }
  info += ` · ${o.format.toUpperCase()}${o.format === 'mp4' ? ' ' + (o.codec === 'h265' ? 'H.265' : 'H.264') : ''}`;
  if (recipe.audio?.normalize) info += ` · صدا ${fa(recipe.audio.normalize)} LUFS`;
  if (recipe.stabilize) info += ' · با تثبیت (دو پاس)';
  $('#outInfo').textContent = info;
}
async function doExport() {
  if (!doc) return;
  setTab('out');
  await flushSave();
  try {
    const job = await (await api(`/api/videos/${doc.id}/export`, post(recipe))).json();
    exportJob = job.id;
    const box = $('#jobBox');
    box.hidden = false;
    $('#export2').disabled = true;
    const j = await pollJob(job.id, x => {
      $('#jobBar').style.width = Math.round(x.progress * 100) + '%';
      $('#jobText').textContent = `${x.stage} ${fa(Math.round(x.progress * 100))}٪`;
    });
    if (j.state === 'done') {
      toast(`خروجی آماده شد: ${j.fileName} (${fa(rnd(j.fileSize / 1048576, 1))}MB در ${fa(rnd(j.seconds, 1))} ثانیه)`);
      const a = document.createElement('a');
      a.href = withKey(`/api/jobs/${j.id}/file?download=1`); a.download = j.fileName;
      document.body.append(a); a.click(); a.remove();
    } else if (j.state === 'failed') toast(j.error || 'خروجی ساخته نشد', true);
    else toast('لغو شد.');
  } catch (e) { toast(e.message, true); }
  finally { exportJob = null; $('#jobBox').hidden = true; $('#export2').disabled = false; loadJobs(); }
}
async function loadJobs() {
  const box = $('#jobList');
  if (!doc) { box.innerHTML = ''; return; }
  try {
    const jobs = (await (await api(`/api/jobs?video=${doc.id}`)).json()).filter(j => j.kind === 'export');
    box.innerHTML = jobs.length ? '' : '<span class="muted small">هنوز خروجی‌ای ساخته نشده (بعد از روشن شدنِ دوبارهٔ سرور، فایل‌ها در پوشهٔ data\\videos\\…\\exports هستند).</span>';
    for (const j of jobs) {
      const el = document.createElement('div');
      el.className = 'job-item';
      el.innerHTML = '<span class="n"></span><span class="s muted"></span>';
      $('.n', el).textContent = j.fileName || j.stage;
      $('.s', el).textContent = j.state === 'done' ? `${fa(rnd(j.fileSize / 1048576, 1))}MB` : j.state === 'failed' ? 'خطا' : j.state === 'cancelled' ? 'لغو' : `${fa(Math.round(j.progress * 100))}٪`;
      if (j.state === 'done') {
        const a = document.createElement('a');
        a.href = withKey(`/api/jobs/${j.id}/file?download=1`); a.textContent = 'دانلود'; a.download = j.fileName;
        el.append(a);
      }
      box.append(el);
    }
  } catch { /* */ }
}

// ───────────── هوشِ مصنوعی ─────────────
async function runAi() {
  if (!doc) return;
  await flushSave();
  busy(health.ai.configured ? 'هوشِ مصنوعی دارد ویدیو را می‌بیند…' : 'تنظیمِ خودکار…');
  $('#aiRun').disabled = true;
  try {
    const j = await (await api(`/api/videos/${doc.id}/ai-edit`, post({ goal: $('#goal').value.trim(), recipe }))).json();
    recipe = normalize(j.recipe);
    commit(); syncUI(); drawTimeline(); requestFrame(true);
    const box = $('#aiOut');
    box.hidden = false; box.innerHTML = '';
    const line = (t, cls) => { const d = document.createElement('div'); d.textContent = t; if (cls) d.className = cls; box.append(d); };
    line(j.notes);
    if (j.usedAi) {
      line(`مدل: ${[...new Set(j.steps.map(s => s.model))].join('، ')} — ${fa(j.steps.length)} دور — توکن: ${fa(j.promptTokens)} ورودی + ${fa(j.completionTokens)} خروجی`, 'muted');
      for (const s of j.steps) if (s.notes) line(`دورِ ${fa(s.round)}${s.done ? ' (تأیید)' : ''}: ${s.notes}`, 'muted');
    } else if (j.error) line('هوشِ مصنوعی استفاده نشد: ' + j.error, 'warn');
  } catch (e) { toast(e.message, true); } finally { busy(''); $('#aiRun').disabled = false; }
}

// ───────────── زبانه‌ها و هم‌گام کردنِ صفحه ─────────────
function setTab(t) {
  const wasFraming = framing();
  activeTab = t;
  for (const b of $$('#tabs button')) b.classList.toggle('on', b.dataset.tab === t);
  for (const s of $$('.tab')) s.hidden = s.id !== 'tab-' + t;
  if (t === 'looks') renderLookThumbs();
  if (t === 'out') { syncOut(); loadJobs(); }
  if (t === 'audio' && stats) showStats();
  if (wasFraming !== framing()) requestFrame(true);
  else drawOverlay();
  updateStatus();
}
function markGroups() {
  for (const det of $$('#groups details.grp')) {
    const g = det.dataset.group;
    if (!g) continue;
    const changed = g === 'curve' ? !!recipe.curve : tools.params.some(p => p.group === g && Math.abs(getAdj(p.key) - p.default) > 1e-9);
    det.classList.toggle('changed', changed);
  }
}
function syncUI() {
  if (!tools) return;
  for (const p of tools.params) syncSlider(p.key);
  markGroups(); drawCurve(); syncLut(); syncFrame(); syncTime(); syncAudio(); syncOut(); markLooks();
}

// ───────────── اتصالِ دکمه‌ها ─────────────
function bindUI() {
  for (const inp of ['#open', '#open2']) $(inp).onchange = e => { upload([...e.target.files]); e.target.value = ''; };
  $('#undo').onclick = undo; $('#redo').onclick = redo;
  const before = $('#before');
  before.onpointerdown = beforeOn; before.onpointerup = before.onpointerleave = beforeOff;
  $('#reset').onclick = () => {
    if (!confirm('همهٔ تنظیم‌ها (رنگ، بُرش، بازه‌ها، سرعت، قاب، صدا، خروجی) پاک شود؟')) return;
    recipe = { adjust: {} }; presetState = null;
    commit(); syncUI(); drawTimeline(); requestFrame(true);
  };
  $('#export').onclick = $('#export2').onclick = doExport;
  $('#jobCancel').onclick = () => { if (exportJob) api(`/api/jobs/${exportJob}`, { method: 'DELETE' }).catch(() => { }); };
  for (const b of $$('#tabs button')) b.onclick = () => setTab(b.dataset.tab);
  bindTimeline();

  // پخش و جابه‌جایی
  $('#play').onclick = togglePlay;
  const step = dt => { if (!doc) return; stopPlay(); curT = clamp(curT + dt, 0, D()); drawTimeline(); requestFrame(true); };
  $('#stepBack').onclick = () => step(-1 / (doc?.media.fps || 25));
  $('#stepFwd').onclick = () => step(1 / (doc?.media.fps || 25));
  $('#toStart').onclick = () => { curT = trimS(); step(0); };
  $('#toEnd').onclick = () => { curT = Math.max(0, trimE() - 0.05); step(0); };
  $('#setIn').onclick = () => { if (!doc) return; setTrim(Math.min(curT, trimE() - 0.1), null); commit(); syncTime(); drawTimeline(); };
  $('#setOut').onclick = () => { if (!doc) return; setTrim(null, Math.max(curT, trimS() + 0.1)); commit(); syncTime(); drawTimeline(); };
  $('#cutSel').onclick = () => {
    if (!selection) return;
    addCut(selection.a, selection.b);
    selection = null; $('#cutSel').disabled = true;
    commit(); syncTime(); drawTimeline();
  };
  $('#delCut').onclick = () => {
    if (selectedCut < 0 || !recipe.cuts) return;
    recipe.cuts.splice(selectedCut, 1);
    if (!recipe.cuts.length) delete recipe.cuts;
    selectedCut = -1; $('#delCut').disabled = true;
    commit(); syncTime(); drawTimeline();
  };

  // رنگ
  $('#auto').onclick = () => runAuto(false);
  for (const b of $$('#scopeKind button')) b.onclick = () => { scopeKind = b.dataset.s; for (const x of $$('#scopeKind button')) x.classList.toggle('on', x === b); drawScope(); };
  $('#lutFile').onchange = e => setLut({ file: e.target.value });
  for (const b of $$('#lutMode button')) b.onclick = () => setLut({ mode: b.dataset.m });
  $('#lutAmount').oninput = e => { $('#lutAmountNum').value = e.target.value; };
  $('#lutAmount').onchange = e => setLut({ amount: +e.target.value });
  $('#lutAmountNum').onchange = e => setLut({ amount: clamp(+e.target.value, 0, 100) });
  $('#lutUpload').onchange = async e => {
    const f = e.target.files[0]; e.target.value = '';
    if (!f) return;
    try {
      const j = await (await api('/api/luts?name=' + encodeURIComponent(f.name), { method: 'POST', body: f })).json();
      await loadLuts();
      setLut({ file: j.file });
      toast(`LUTِ «${j.file}» اضافه شد.`);
    } catch (err) { toast(err.message, true); }
  };

  // قاب
  for (const b of $$('#aspect button')) b.onclick = () => setFrame({ aspect: b.dataset.a });
  for (const b of $$('#fit button')) b.onclick = () => setFrame({ fit: b.dataset.f });
  for (const k of ['focusX', 'focusY']) {
    $('#' + k).oninput = e => { $('#' + k + 'Num').value = e.target.value; recipe.frame && (recipe.frame[k] = +e.target.value / 100); drawOverlay(); };
    $('#' + k).onchange = e => setFrame({ [k]: +e.target.value / 100 });
    $('#' + k + 'Num').onchange = e => setFrame({ [k]: clamp(+e.target.value, 0, 100) / 100 });
  }
  $('#frame').addEventListener('click', e => {
    if (!framing()) return;
    const ir = $('#frame').getBoundingClientRect();
    const r = frameRect(ir.width, ir.height);
    const px = e.clientX - ir.left, py = e.clientY - ir.top;
    const fx = ir.width - r.w > 1 ? clamp((px - r.w / 2) / (ir.width - r.w), 0, 1) : 0.5;
    const fy = ir.height - r.h > 1 ? clamp((py - r.h / 2) / (ir.height - r.h), 0, 1) : 0.5;
    setFrame({ focusX: rnd(fx, 3), focusY: rnd(fy, 3) });
  });
  for (const id of ['cropL', 'cropR', 'cropT', 'cropB']) {
    $('#' + id).oninput = e => { $('#' + id + 'Num').value = e.target.value; setCropEdges(); requestFrame(false); };
    $('#' + id).onchange = () => { setCropEdges(); commit(); requestFrame(true); };
    $('#' + id + 'Num').onchange = e => { $('#' + id).value = e.target.value; setCropEdges(); commit(); syncFrame(); requestFrame(true); };
  }
  const setAngle = (v, final) => {
    recipe.crop = { ...(recipe.crop || {}), angle: rnd(clamp(+v || 0, -45, 45), 2) };
    $('#angle').value = $('#angleNum').value = recipe.crop.angle;
    cleanCrop();
    if (final) commit();
    requestFrame(final);
  };
  $('#angle').oninput = e => setAngle(e.target.value, false);
  $('#angle').onchange = e => setAngle(e.target.value, true);
  $('#angleNum').onchange = e => setAngle(e.target.value, true);
  for (const [id, k] of [['#flipH', 'flipH'], ['#flipV', 'flipV']]) $(id).onclick = () => {
    recipe.crop = { ...(recipe.crop || {}), [k]: !recipe.crop?.[k] };
    cleanCrop(); commit(); syncFrame(); requestFrame(true);
  };
  $('#stabOn').onchange = e => {
    if (e.target.checked) recipe.stabilize = { amount: +$('#stab').value || 50 }; else delete recipe.stabilize;
    commit(); syncFrame(); syncOut();
    if (e.target.checked) toast('تثبیت در «▶ پخش» و خروجی دیده می‌شود.');
  };
  $('#stab').oninput = e => { $('#stabNum').value = e.target.value; };
  $('#stab').onchange = e => { recipe.stabilize = { amount: +e.target.value }; commit(); };
  $('#stabNum').onchange = e => { recipe.stabilize = { amount: clamp(+e.target.value, 1, 100) }; commit(); syncFrame(); };

  // زمان
  $('#trimStart').onchange = e => { const v = parseT(e.target.value); if (isFinite(v)) { setTrim(v, null); commit(); } syncTime(); drawTimeline(); };
  $('#trimEnd').onchange = e => { const v = parseT(e.target.value); if (isFinite(v)) { setTrim(null, v); commit(); } syncTime(); drawTimeline(); };
  $('#trimStartHere').onclick = () => $('#setIn').click();
  $('#trimEndHere').onclick = () => $('#setOut').click();
  $('#trimClear').onclick = () => { delete recipe.trim; commit(); syncTime(); drawTimeline(); };
  for (const b of $$('#speedChips button')) b.onclick = () => { setTime({ speed: +b.dataset.v }); commit(); syncTime(); syncOut(); };
  $('#speed').oninput = e => { $('#speedNum').value = e.target.value; };
  $('#speed').onchange = e => { setTime({ speed: +e.target.value }); commit(); syncTime(); syncOut(); };
  $('#speedNum').onchange = e => { setTime({ speed: clamp(+e.target.value, 0.25, 4) }); commit(); syncTime(); syncOut(); };
  $('#smooth').onchange = e => { setTime({ smooth: e.target.checked }); commit(); };
  for (const k of ['fadeIn', 'fadeOut']) {
    $('#' + k).oninput = e => { $('#' + k + 'Num').value = e.target.value; };
    $('#' + k).onchange = e => { setTime({ [k]: +e.target.value }); commit(); syncTime(); };
    $('#' + k + 'Num').onchange = e => { setTime({ [k]: clamp(+e.target.value, 0, 5) }); commit(); syncTime(); };
  }
  for (const [r, n] of [['#pauseDb', '#pauseDbNum'], ['#pauseMin', '#pauseMinNum']]) {
    $(r).oninput = e => { $(n).value = e.target.value; if (r === '#pauseDb') pauseDbTouched = true; };
    $(n).onchange = e => { $(r).value = e.target.value; if (r === '#pauseDb') pauseDbTouched = true; };
    $(n).value = $(r).value;
  }
  $('#findPauses').onclick = findPauses;
  $('#applyPauses').onclick = () => {
    if (!pauses?.cuts.length) return;
    for (const c of pauses.cuts) addCut(c.start, c.end);
    pauses = null; $('#applyPauses').disabled = true; $('#pauseInfo').hidden = true;
    commit(); syncTime(); drawTimeline();
    toast('مکث‌ها حذف شد؛ با «▶ پخش» گوش کنید. هر بازه را می‌شود برگرداند.');
  };
  $('#cutsClear').onclick = e => { e.preventDefault(); delete recipe.cuts; selectedCut = -1; commit(); syncTime(); drawTimeline(); };

  // صدا
  $('#measure').onclick = measure;
  $('#autoAudio').onclick = () => runAuto(true);
  for (const b of $$('#norm button')) b.onclick = () => setAudio({ normalize: +b.dataset.n });
  for (const b of $$('#hum button')) b.onclick = () => setAudio({ hum: +b.dataset.h });
  $('#mute').onchange = e => setAudio({ mute: e.target.checked });

  // خروجی
  for (const b of $$('#fmt button')) b.onclick = () => setOut({ format: b.dataset.f });
  for (const b of $$('#codec button')) b.onclick = () => setOut({ codec: b.dataset.c });
  for (const b of $$('#size button')) b.onclick = () => setOut({ size: +b.dataset.s });
  for (const b of $$('#fps button')) b.onclick = () => setOut({ fps: +b.dataset.f });
  for (const b of $$('#qual button')) b.onclick = () => setOut({ quality: b.dataset.q });
  $('#safe').onchange = e => setOut({ broadcastSafe: e.target.checked });

  // هوشِ مصنوعی
  for (const b of $$('#goalChips button')) b.onclick = () => { $('#goal').value = b.textContent; };
  $('#aiRun').onclick = runAi;

  // کشیدن و رها کردن
  let depth = 0;
  window.addEventListener('dragenter', e => { if (e.dataTransfer?.types?.includes('Files')) { depth++; document.body.classList.add('dragging'); } });
  window.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; document.body.classList.remove('dragging'); } });
  window.addEventListener('dragover', e => e.preventDefault());
  window.addEventListener('drop', e => {
    e.preventDefault(); depth = 0; document.body.classList.remove('dragging');
    if (e.dataTransfer?.files?.length) upload([...e.dataTransfer.files]);
  });

  // صفحه‌کلید (e.code ⇒ روی صفحه‌کلیدِ فارسی هم کار می‌کند)
  document.addEventListener('keydown', e => {
    if (e.target.matches('input, textarea, select')) return;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.code === 'KeyZ') { e.preventDefault(); e.shiftKey ? redo() : undo(); }
    else if (mod && e.code === 'KeyY') { e.preventDefault(); redo(); }
    else if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
    else if (e.code === 'ArrowLeft') { e.preventDefault(); step(e.shiftKey ? -1 : -1 / (doc?.media.fps || 25)); }
    else if (e.code === 'ArrowRight') { e.preventDefault(); step(e.shiftKey ? 1 : 1 / (doc?.media.fps || 25)); }
    else if (e.code === 'KeyI') $('#setIn').click();
    else if (e.code === 'KeyO') $('#setOut').click();
    else if (e.code === 'Delete' || e.code === 'Backspace') { if (selection) $('#cutSel').click(); else $('#delCut').click(); }
    else if (e.code === 'Backslash' && !e.repeat) beforeOn();
  });
  document.addEventListener('keyup', e => { if (e.code === 'Backslash') beforeOff(); });
  window.addEventListener('resize', () => { drawTimeline(); drawOverlay(); });
  window.addEventListener('beforeunload', () => { if (saveTimer) save(); });
}
