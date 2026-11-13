"use strict";

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const fa = (n) => Number(n).toLocaleString("fa-IR");
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

const STEP_TITLES = {
  login: {
    browser: "باز کردن مرورگر",
    page: "رفتن به صفحهٔ ورود",
    credentials: "وارد کردن یوزرنیم و پسورد",
    answer: "پاسخ اینستاگرام",
    save: "ذخیرهٔ نشست",
  },
  profile: {
    browser: "باز کردن مرورگر",
    page: "رفتن به پروفایل",
    read: "خواندن اطلاعات",
    save: "ذخیرهٔ اطلاعات",
  },
  details: {
    browser: "باز کردن مرورگر",
    page: "رفتن به پست‌ها",
    read: "خواندن کامنت و لایک‌کنندگان",
    save: "ذخیرهٔ اطلاعات",
  },
};
const stepMode = (s) => (s && (s.mode === "profile" || s.mode === "details") ? s.mode : "login");

// What each outcome means, in plain Persian. The raw Instagram text is shown next to it.
const KIND = {
  ok: { tone: "ok", icon: "circle-check", title: "وارد شدی", text: "نشست روی همین کامپیوتر ذخیره شد. دفعهٔ بعد بدون پسورد وارد می‌شویم." },
  bad_password: { tone: "bad", icon: "circle-x", title: "پسورد اشتباه است", text: "اینستاگرام می‌گوید این یوزرنیم حساب دارد، ولی پسورد را قبول نکرد." },
  bad_username: { tone: "bad", icon: "circle-x", title: "این یوزرنیم حسابی ندارد", text: "اینستاگرام حسابی با این نام پیدا نکرد. املای یوزرنیم را دوباره چک کن." },
  bad_credentials: { tone: "bad", icon: "circle-x", title: "یوزرنیم یا پسورد اشتباه است", text: "اینستاگرام نمی‌گوید کدام‌یک غلط است. هر دو را دوباره چک کن." },
  bad_code: { tone: "bad", icon: "circle-x", title: "کد قبول نشد", text: "کد را دوباره بخوان. کدها بعد از چند دقیقه منقضی می‌شوند." },
  rate_limit: { tone: "warn", icon: "alert", title: "اینستاگرام گفت صبر کن", text: "چند دقیقه صبر کن و بعد یک بار دیگر امتحان کن. تلاش پشت‌سرهم وضع را بدتر می‌کند." },
  disabled: { tone: "bad", icon: "circle-x", title: "حساب محدود یا غیرفعال است", text: "وضعیت حساب را از خود اپ اینستاگرام ببین، بعد دوباره امتحان کن." },
  automated: { tone: "bad", icon: "circle-x", title: "اینستاگرام رفتار خودکار را تشخیص داد", text: "ورود را در پنجرهٔ باز مرورگر دستی انجام بده، یا کمی بعد دوباره امتحان کن." },
  network: { tone: "bad", icon: "circle-x", title: "اینستاگرام باز نشد", text: "اتصال قطع است یا فیلتر شده. VPN را روشن کن یا در «تنظیمات اتصال» پراکسی بده." },
  timeout: { tone: "warn", icon: "alert", title: "جواب روشنی نیامد", text: "پنجرهٔ مرورگر باز مانده. ببین اینستاگرام چه نشان می‌دهد." },
  session_invalid: { tone: "warn", icon: "alert", title: "نشست ذخیره‌شده معتبر نیست", text: "اینستاگرام صفحهٔ ورود نشان داد. با یوزرنیم و پسورد دوباره وارد شو." },
  browser: { tone: "bad", icon: "circle-x", title: "مرورگر باز نشد", text: "اگر پنجرهٔ دیگری از همین پروژه باز است ببندش و دوباره امتحان کن." },
  cancelled: { tone: "warn", icon: "alert", title: "لغو شد", text: "مرورگر بسته شد. هر وقت خواستی دوباره شروع کن." },
  budget: { tone: "warn", icon: "gauge", title: "سقف ایمنی پر شده", text: "برای محافظت از حساب، کار را شروع نکردم." },
  cooldown: { tone: "warn", icon: "hourglass", title: "در مکثِ بعد از «صبر کن»", text: "اینستاگرام چند دقیقه پیش گفت صبر کن." },
  no_posts: { tone: "warn", icon: "alert", title: "پستی برای خواندن نیست", text: "برای این پروفایل پستی ذخیره نشده؛ اول پروفایل را بخوان." },
  not_found: { tone: "bad", icon: "circle-x", title: "این پروفایل پیدا نشد", text: "اینستاگرام صفحه‌ای با این یوزرنیم ندارد. املا را چک کن؛ ممکن است حساب پاک شده یا یوزرنیمش عوض شده باشد." },
  unreadable: { tone: "warn", icon: "alert", title: "اطلاعات پروفایل خوانده نشد", text: "صفحه باز شد ولی چیزی که بشناسم در آن پیدا نکردم. عکس صفحه و جزئیات پایین است." },
  other: { tone: "bad", icon: "circle-x", title: "اینستاگرام خطا داد", text: "متن اصلی پیام پایین است." },
  error: { tone: "bad", icon: "circle-x", title: "خطای برنامه", text: "جزئیات در گزارش پایین صفحه هست." },
};
const DETAIL_ORDER = ["http", "path", "status", "error_type", "authenticated", "user", "two_factor_required",
  "checkpoint_url", "message", "feedback_title", "feedback_message", "fail_text", "lock", "spam", "page_url", "page_lines", "page_inputs", "page_buttons", "error"];

// Open with the layout of last time; the first status reply corrects it if it was wrong.
document.getElementById("main").dataset.session = stored("igs.ready") === "1" ? "1" : "0";

const S = { run: 0, cursor: 0, log: [], snap: null, timer: null, offline: false, answerKey: "", stepsKey: "", reacted: 0 };

// DOM is built with createElement/textContent only, so Instagram's text can never run as markup.
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}

function icon(name, cls) {
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "ic" + (cls ? " " + cls : ""));
  const use = document.createElementNS(NS, "use");
  use.setAttribute("href", "#i-" + name);
  svg.append(use);
  return svg;
}

async function api(path, body) {
  const opts = body === undefined
    ? { cache: "no-store" }
    : { method: "POST", headers: { "Content-Type": "application/json", "X-Igs": "1" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  return { ok: res.ok, status: res.status, data };
}

function stored(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key) || "";
    localStorage.setItem(key, value);
  } catch { /* storage can be blocked; the page works without it */ }
  return value;
}

function savedAt(iso) {
  try {
    return new Intl.DateTimeFormat("fa-IR-u-ca-persian", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
  } catch { return ""; }
}

/* ---------- chip, steps, log ---------- */
function renderChip(s) {
  const chip = $("chip");
  const meta = s && s.session;
  let key, kids, on = false;
  if (S.offline) {
    key = "off";
    kids = [icon("alert"), h("span", { text: "ارتباط با برنامه قطع است" })];
  } else if (meta) {
    on = true;
    const when = savedAt(meta.saved_at);
    key = "on|" + meta.username + "|" + meta.saved_at;
    kids = [icon("shield"), h("span", {}, "نشست ذخیره‌شده برای ", h("bdi", { dir: "ltr", text: meta.username ? "@" + meta.username : "id " + meta.user_id }), when ? "، " + when : "")];
  } else {
    key = "none";
    kids = [icon("user"), h("span", { text: "نشستی ذخیره نشده" })];
  }
  if (chip.dataset.key === key) return;
  chip.dataset.key = key;
  chip.dataset.on = String(on);
  chip.replaceChildren(...kids);
}

const STATE_LABEL = { idle: "منتظر", active: "در حال انجام", waiting: "منتظر تو", done: "انجام شد", failed: "ناموفق", skipped: "لازم نبود" };
const stepEls = {};

function stepContent(state, n) {
  if (state === "done") return icon("check");
  if (state === "failed") return icon("x");
  if (state === "waiting") return icon("hourglass");
  return document.createTextNode(state === "skipped" ? "–" : fa(n));
}

let stepsFor = "";
// The list of steps depends on the kind of job (signing in, or reading a profile), so it is rebuilt when that changes.
function buildSteps(mode, keys) {
  $("steps").replaceChildren();
  for (const k of Object.keys(stepEls)) delete stepEls[k];
  keys.forEach((key, i) => {
    const node = h("span", { class: "node" }, stepContent("idle", i + 1));
    const sr = h("span", { class: "sr", text: "، " + STATE_LABEL.idle });
    const note = h("p", { class: "step-note", hidden: true });
    const li = h("li", { class: "step", "data-s": "idle" }, node,
      h("div", {}, h("div", { class: "step-title" }, STEP_TITLES[mode][key], sr), note));
    stepEls[key] = { li, node, sr, note, state: "idle", text: "", n: i + 1 };
    $("steps").append(li);
  });
  stepsFor = mode + ":" + keys.join();
  $("t-reply").textContent = { profile: "مسیر خواندن پروفایل", details: "مسیر خواندن پست‌ها" }[mode] || "مسیر ورود";
}

function lastNote(key) {
  for (let i = S.log.length - 1; i >= 0; i--) if (S.log[i].step === key) return S.log[i].msg;
  return "";
}

function renderSteps(s) {
  const waiting = s.state === "need_code" || s.state === "need_manual";
  const mode = stepMode(s), keys = s.steps.map((x) => x.key);
  if (stepsFor !== mode + ":" + keys.join()) buildSteps(mode, keys);
  for (const st of s.steps) {
    const e = stepEls[st.key];
    const state = waiting && st.key === "answer" && st.state === "active" ? "waiting" : st.state;
    if (e.state !== state) {
      e.state = state;
      e.li.dataset.s = state;
      e.node.replaceChildren(stepContent(state, e.n));
      e.sr.textContent = "، " + STATE_LABEL[state];
    }
    const text = state === "active" || state === "waiting" ? lastNote(st.key) : "";
    if (e.text !== text) {
      e.text = text;
      e.note.textContent = text;
      e.note.hidden = !text;
    }
  }
}

let logShown = 0;
function resetLogView() {
  logShown = 0;
  $("log").replaceChildren();
}

function renderLog() {
  const ol = $("log");
  const stick = ol.scrollTop + ol.clientHeight >= ol.scrollHeight - 24;
  for (; logShown < S.log.length; logShown++) {
    const e = S.log[logShown];
    const lv = e.level === "info"
      ? h("span", { class: "lv", text: "•", "aria-hidden": "true" })
      : icon({ ok: "check", err: "x", warn: "alert" }[e.level], "lv");
    ol.append(h("li", { "data-l": e.level }, h("time", { text: e.t }), lv, h("span", { class: "msg", text: e.msg })));
  }
  if (stick) ol.scrollTop = ol.scrollHeight;
  $("log-count").textContent = S.log.length ? fa(S.log.length) + " مورد" : "";
}

/* ---------- answer card ---------- */
const QUOTED = new Set(["bad_password", "bad_username", "bad_credentials", "bad_code", "rate_limit",
  "disabled", "automated", "other", "timeout", "session_invalid"]);

function verdict(iconName, title, text, spinner) {
  return h("div", { class: "verdict" },
    h("span", { class: "badge", "aria-hidden": "true" }, spinner ? h("span", { class: "ring" }) : icon(iconName)),
    h("div", {}, h("h3", { text: title }), text ? h("p", { text }) : null));
}

function flash(btn, text) {
  const label = btn.querySelector("span");
  const before = label.textContent;
  label.textContent = text;
  setTimeout(() => { label.textContent = before; }, 1500);
}

// Instagram's own words, untouched: this is what the page exists to show.
function quote(msg, hasShot, label = "پیام اینستاگرام، متن اصلی") {
  const copy = h("button", {
    type: "button", class: "btn ghost copy", "aria-label": "کپی متن پیام",
    onclick: async (e) => {
      const btn = e.currentTarget;
      try { await navigator.clipboard.writeText(msg); flash(btn, "کپی شد"); } catch { /* clipboard blocked */ }
    },
  }, icon("copy"), h("span", { text: "کپی" }));
  return h("figure", { class: "quote" },
    h("figcaption", {}, h("span", { text: label }), msg ? copy : null),
    msg ? h("blockquote", { lang: "en", text: msg })
      : h("blockquote", { class: "none", text: hasShot ? "اینستاگرام متنی نداد. عکس صفحه‌اش پایین است." : "متنی از اینستاگرام دریافت نشد." }));
}

function techDetails(detail) {
  const keys = DETAIL_ORDER.filter((k) => detail && detail[k] != null && detail[k] !== "");
  if (!keys.length) return null;
  return h("details", { class: "more" },
    h("summary", {}, icon("window"), h("span", { text: "جزئیات فنی پاسخ اینستاگرام" }), icon("chevron", "chev")),
    h("dl", { class: "tech" }, keys.flatMap((k) => [h("dt", { text: k }), h("dd", { text: String(detail[k]) })])));
}

function shotDetails(o, s) {
  if (!o.shot) return null;
  return h("details", { class: "more shot", open: !o.ig_message && !o.page_text },
    h("summary", {}, icon("image"), h("span", { text: "عکس از پنجرهٔ اینستاگرام" }), icon("chevron", "chev")),
    h("img", { src: `/api/shot?v=${s.run}-${o.shot}`, alt: "عکسی از صفحهٔ اینستاگرام در لحظهٔ پاسخ", loading: "lazy" }));
}

function focusForm(mode) {
  if (mode === "profile" || mode === "details") { $("pu").focus(); $("pu").select(); return; }
  const field = $("u").value ? $("p") : $("u");
  field.focus();
}

// The error Instagram gave, or else what its page says (for example where the code was sent).
function pageQuote(o, s) {
  if (o.ig_message) return quote(o.ig_message, !!o.shot);
  if (o.page_text) return quote(o.page_text, !!o.shot, "متن صفحهٔ اینستاگرام");
  return null;
}

function codeCard(s, o) {
  const input = h("input", { id: "code", type: "text", inputmode: "numeric", autocomplete: "one-time-code",
    dir: "ltr", maxlength: "10", "aria-label": "کد تأیید", placeholder: "••••••" });
  const form = h("form", { class: "code-row", onsubmit: submitCode }, input,
    h("button", { class: "btn primary", type: "submit" }, h("span", { text: "تأیید کد" })));
  return { tone: "warn", focus: input, kids: [
    verdict("phone", o.ig_message ? "کد دوباره لازم است" : "اینستاگرام کد تأیید خواست",
      "کد را از پیامک، ایمیل یا اپ احراز هویت بخوان و اینجا بنویس. اگر ترجیح می‌دهی در خود پنجره بزنی هم، سایت خودش ادامه می‌دهد."),
    pageQuote(o, s), form, techDetails(o.detail), shotDetails(o, s)] };
}

async function submitCode(e) {
  e.preventDefault();
  const input = $("code");
  const code = input.value.replace(/\s+/g, "");
  if (code.length < 4) {
    input.setAttribute("aria-invalid", "true");
    input.focus();
    return;
  }
  input.readOnly = true;
  await api("/api/code", { code });
}

function manualCard(s, o) {
  return { tone: "warn", kids: [
    verdict("window", "تأیید هویت در پنجرهٔ مرورگر",
      "اینستاگرام مرحله‌ای خواست که باید خودت در پنجرهٔ Chromium انجامش بدهی. این صفحه خودش ادامه می‌دهد."),
    pageQuote(o, s), techDetails(o.detail), shotDetails(o, s)] };
}

function successCard(s) {
  const r = s.result || {};
  const name = r.username || "";
  const avatar = h("span", { class: "avatar", "aria-hidden": "true" }, (name || "?").slice(0, 1).toUpperCase(),
    r.avatar ? h("img", { src: r.avatar, alt: "", referrerpolicy: "no-referrer", onerror: (e) => e.currentTarget.remove() }) : null);
  const who = h("div", { class: "who" }, avatar, h("div", {},
    h("strong", {}, name ? h("bdi", { dir: "ltr", text: "@" + name }) : "نام حساب خوانده نشد"),
    r.user_id ? h("span", {}, "شناسهٔ حساب: ", h("bdi", { dir: "ltr", text: String(r.user_id) })) : null));
  const note = r.verified === false
    ? (name ? "نام حساب از روی چیزی است که تایپ کردی؛ صفحهٔ اینستاگرام نامی نشان نداد."
      : "ورود تأیید شد ولی نام حساب از صفحه خوانده نشد.")
    : "";
  return { tone: "ok", kids: [
    verdict("circle-check", r.reused ? "نشست ذخیره‌شده معتبر است" : KIND.ok.title,
      r.reused ? "اینستاگرام هنوز تو را با همین نشست می‌شناسد و پسورد لازم نیست." : KIND.ok.text),
    who, note ? h("p", { class: "help", text: note }) : null] };
}

function failCard(s, o) {
  const k = KIND[o.kind] || KIND.error;
  const actions = [];
  if (s.browser_open) {
    actions.push(h("button", { type: "button", class: "btn", onclick: () => api("/api/cancel", {}) }, icon("x"), h("span", { text: "بستن مرورگر" })));
  }
  if (o.kind === "cooldown") actions.push(h("button", { type: "button", class: "btn", onclick: () => api("/api/cooldown/clear", {}).then(poll) }, icon("check"), h("span", { text: "پایان مکث" })));
  if (o.kind === "budget") {
    actions.push(h("button", { type: "button", class: "btn", onclick: () => { $("limits").open = true; $("limits").scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" }); } },
      icon("gauge"), h("span", { text: "باز کردن محدودیت‌ها" })));
  }
  actions.push(h("button", { type: "button", class: "btn", onclick: () => focusForm(s.mode) }, icon("login"), h("span", { text: "دوباره امتحان کن" })));
  const said = o.ig_message || o.page_text || QUOTED.has(o.kind);
  return { tone: k.tone, kids: [
    verdict(k.icon, k.title, o.note || k.text),
    said ? pageQuote(o, s) || quote(null, !!o.shot) : null,
    techDetails(o.detail), shotDetails(o, s), h("div", { class: "answer-actions" }, actions)] };
}

/* ---------- the profile card ---------- */
const compact = new Intl.NumberFormat("fa-IR", { notation: "compact", maximumFractionDigits: 1 });
const grouped = new Intl.NumberFormat("fa-IR");
const relative = new Intl.RelativeTimeFormat("fa", { numeric: "auto" });
const STAT_LABELS = [["posts", "پست"], ["followers", "فالوور"], ["following", "فالووینگ"]];
const COUNT_NAMES = { posts: "پست", followers: "فالوور", following: "فالووینگ" };

function agoText(sec) {
  if (sec < 60) return "چند ثانیه پیش";
  const [v, unit] = sec < 3600 ? [Math.floor(sec / 60), "minute"]
    : sec < 86400 ? [Math.floor(sec / 3600), "hour"] : [Math.floor(sec / 86400), "day"];
  return relative.format(-v, unit);
}

function tag(name, text, tone) {
  return h("span", { class: "tag" + (tone ? " " + tone : "") }, icon(name), h("span", { text }));
}

// Big number first (compact when it is long), the exact figure under it, a screen reader gets the exact one only.
function statCell(label, value, approx) {
  const known = typeof value === "number";
  const big = !known ? "؟" : value >= 10000 ? compact.format(value) : grouped.format(value);
  const exact = known && approx ? "تقریبی" : known && value >= 10000 ? grouped.format(value) : "";
  const spoken = known ? grouped.format(value) + (approx ? " تقریباً" : "") : "نامشخص";
  return h("div", { class: "pstat" }, h("dt", { text: label }),
    h("dd", {}, h("span", { "aria-hidden": "true", "data-to": known ? String(value) : null, text: big }), h("span", { class: "sr", text: spoken })),
    exact ? h("dd", { class: "exact", "aria-hidden": "true", text: exact }) : null);
}

function countUp(root) {
  if (reduced) return;
  for (const el of root.querySelectorAll("[data-to]")) {
    const to = Number(el.dataset.to);
    if (!(to > 0)) continue;
    const fmt = to >= 10000 ? compact : grouped;
    const t0 = performance.now();
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / 650);
      el.textContent = fmt.format(k < 1 ? Math.round(to * (1 - Math.pow(1 - k, 3))) : to);
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
}

function linkChip(l) {
  let shown = l.url;
  try { const u = new URL(l.url); shown = u.host + (u.pathname === "/" ? "" : u.pathname); } catch { /* keep the address as it is */ }
  return h("a", { class: "plink", href: l.url, target: "_blank", rel: "noopener noreferrer", title: l.title || null },
    icon("link"), h("span", { text: shown }));
}

function relationText(rel) {
  if (!rel) return "";
  const parts = [];
  if (rel.following) parts.push("این حساب را دنبال می‌کنی");
  else if (rel.requested) parts.push("برای دنبال‌کردنش درخواست فرستاده‌ای");
  if (rel.followed_by) parts.push("او تو را دنبال می‌کند");
  if (rel.blocking) parts.push("این حساب را مسدود کرده‌ای");
  return parts.join("، ");
}

async function copyText(btn, text) {
  try { await navigator.clipboard.writeText(text); flash(btn, "کپی شد"); } catch { /* clipboard blocked */ }
}

function profileCard(s) {
  const r = s.result || {}, p = r.profile || {}, approx = p.approx || [];
  const handle = h("bdi", { dir: "ltr", text: "@" + (p.username || "") });
  const avatar = h("span", { class: "pavatar", "aria-hidden": "true" }, (p.username || "?").slice(0, 1).toUpperCase(),
    p.has_avatar ? h("img", { src: `/api/avatar/${encodeURIComponent(p.username)}?v=${encodeURIComponent(p.fetched_at || "")}`,
      alt: "", onerror: (e) => e.currentTarget.remove() }) : null);
  const tags = [
    p.is_private === true ? tag("lock", "حساب خصوصی", "lock") : p.is_private === false ? tag("globe", "حساب عمومی") : null,
    p.is_verified ? tag("verified", "تأییدشده", "good") : null,
    p.is_business || p.is_professional ? tag("briefcase", p.category ? "کسب‌وکار، " + p.category : "حساب حرفه‌ای")
      : (p.more || {}).account_type === 3 ? tag("briefcase", "حساب سازندهٔ محتوا") : null,
    (p.more || {}).story_at && Date.now() / 1000 - p.more.story_at < 86400 ? tag("circle-play", "استوری فعال", "good") : null,
    (p.more || {}).live ? tag("circle-play", "الان لایو است", "good") : null,
    (p.more || {}).memorial ? tag("clock", "حساب یادبود") : null,
  ].filter(Boolean);
  const links = (p.links || []).filter((l) => /^https?:\/\//.test(l.url));
  const notes = [];
  if (!links.length && p.link_text) {
    notes.push(h("p", { class: "pnote" }, "لینک بیو: ", h("bdi", { dir: "auto", text: p.link_text }), "؛ نشانی کاملش از اینستاگرام نیامد."));
  }
  if (approx.length) {
    notes.push(h("p", { class: "pnote", text: "عدد دقیق " + approx.map((k) => COUNT_NAMES[k]).join("، ") + " از اینستاگرام نیامد؛ عدد گردشده است." }));
  }
  if (p.mutual_text) notes.push(h("p", { class: "pnote" }, h("bdi", { dir: "auto", text: p.mutual_text })));
  else if (p.mutual_count > 0) notes.push(h("p", { class: "pnote", text: "دنبال‌کنندهٔ مشترک با حساب تو: " + grouped.format(p.mutual_count) }));
  if (relationText(p.relation)) notes.push(h("p", { class: "pnote", text: relationText(p.relation) }));
  const json = JSON.stringify(p, null, 2);
  const when = r.cached ? "از ذخیره‌ها، " + agoText(r.age || 0) : "همین حالا از اینستاگرام خوانده شد";
  const foot = h("div", { class: "pfoot" },
    h("span", { class: "pwhen" }, icon("clock"), h("span", { text: when })),
    h("div", { class: "acts" },
      h("button", { type: "button", class: "btn", onclick: () => readProfile(p.username, true) },
        icon("refresh"), h("span", { text: "تازه‌سازی از اینستاگرام" })),
      h("button", { type: "button", class: "btn", onclick: (e) => copyText(e.currentTarget, json) },
        icon("copy"), h("span", { text: "کپی JSON" }))));
  const raw = h("details", { class: "more" },
    h("summary", {}, icon("braces"), h("span", { text: "داده‌های ذخیره‌شده (JSON)" }), icon("chevron", "chev")),
    h("pre", { class: "pjson", text: json }));
  const card = h("div", { class: "pcard" },
    h("div", { class: "phead" }, avatar, h("div", {},
      h("h3", { class: "pname" }, p.full_name ? h("bdi", { dir: "auto", text: p.full_name }) : handle),
      p.full_name ? h("div", { class: "phandle" }, handle) : null)),
    tags.length ? h("div", { class: "tags" }, tags) : null,
    h("div", { class: "pstats" }, h("dl", {}, STAT_LABELS.map(([k, label]) => statCell(label, p[k], approx.includes(k))))),
    p.biography ? h("p", { class: "pbio", dir: "auto", text: p.biography }) : h("p", { class: "pbio none", text: "این حساب بیو ندارد." }),
    links.length ? h("div", { class: "plinks" }, links.map(linkChip)) : null,
    notes.length ? h("div", { class: "pnotes" }, notes) : null, h("div", { class: "dossier", "data-user": p.username }), foot, raw);
  return { tone: "profile", kids: [card], after: (box) => { countUp(box); loadDossier(box, r.section === "details" ? r.codes : []); } };
}

function buildAnswer(s) {
  const o = s.outcome || {};
  if (s.state === "running") {
    const msg = S.log.length ? S.log[S.log.length - 1].msg : "";
    const title = { profile: "در حال خواندن پروفایل", details: "در حال خواندن کامنت و لایک‌کنندگان", posts: "در حال خواندن پست‌های بیشتر",
      stories: "در حال خواندن استوری", highlights: "در حال خواندن هایلایت‌ها", follow: "در حال خواندن فالوورها و فالووینگ",
      download: "در حال دانلود عکس و ویدیو" }[s.mode] || "منتظر اینستاگرام";
    const stop = h("button", { type: "button", class: "btn", onclick: (e) => { e.currentTarget.disabled = true; api("/api/cancel", {}).then(() => poll()); } },
      icon("x"), h("span", { text: "لغو و بستن مرورگر" }));
    return { tone: "wait", kids: [verdict("", title, msg, true), h("div", { class: "answer-actions" }, stop)] };
  }
  if (s.state === "need_code") return codeCard(s, o);
  if (s.state === "need_manual") return manualCard(s, o);
  if (s.state === "success") return s.mode === "profile" || s.mode === "details" ? profileCard(s) : successCard(s);
  if (s.state === "failed" || s.state === "cancelled") return failCard(s, o);
  const ready = !!(s.session || s.profile_exists);
  return { tone: "idle", kids: [verdict("shield", "هنوز پاسخی نیست", ready
    ? "یک یوزرنیم را در «خواندن پروفایل» بنویس. نتیجه‌اش همین‌جا می‌آید."
    : "یوزرنیم و پسورد را بده و ورود را بزن. جواب اینستاگرام همین‌جا با متن اصلی‌اش نشان داده می‌شود.")] };
}

function renderAnswer(s) {
  const o = s.outcome || {};
  const last = s.state === "running" && S.log.length ? S.log[S.log.length - 1].msg : "";
  const key = [s.run, s.state, o.kind, o.ig_message, o.shot, s.result && s.result.username, s.browser_open, last, !!(s.session || s.profile_exists)].join("|");
  if (key === S.answerKey) return;
  const first = S.answerKey === "";
  S.answerKey = key;
  const view = s.run + "|" + s.state + "|" + o.kind;
  const changed = view !== S.viewKey;
  S.viewKey = view;
  const res = buildAnswer(s);
  const box = $("answer");
  box.dataset.tone = res.tone;
  box.replaceChildren(...res.kids.filter(Boolean));
  box.classList.remove("enter");
  if (changed && !first && s.state !== "idle") {
    void box.offsetWidth;
    box.classList.add("enter");
  }
  if (res.focus) res.focus.focus({ preventScroll: true });
  if (res.after) res.after(box);
  if (changed && !first && s.state !== "idle") {
    // On a phone the steps sit below the form: bring them into view when a run starts.
    const target = s.state === "running" ? box.closest(".panel") : box;
    target.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }
}

/* ---------- form ---------- */
const PROXY_RE = /^(https?|socks5):\/\/\S+$/;
const FIELDS = { u: "username", p: "password", x: "proxy" };

function setError(id, msg) {
  const box = $("e-" + id);
  const input = $(id);
  if (!msg) {
    box.hidden = true;
    box.replaceChildren();
    input.removeAttribute("aria-invalid");
    input.removeAttribute("aria-describedby");
    return;
  }
  box.replaceChildren(icon("alert"), h("span", { text: msg }));
  box.setAttribute("role", "alert");
  box.hidden = false;
  input.setAttribute("aria-invalid", "true");
  input.setAttribute("aria-describedby", box.id);
}

function openAdvanced(open) {
  $("adv-toggle").setAttribute("aria-expanded", String(open));
  $("adv-body").hidden = !open;
}

function togglePw() {
  const input = $("p");
  const btn = $("pw-toggle");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  btn.setAttribute("aria-pressed", String(show));
  btn.setAttribute("aria-label", show ? "پنهان کردن پسورد" : "نمایش پسورد");
  btn.replaceChildren(icon(show ? "eye-off" : "eye"));
}

function renderForm(s) {
  const busy = s.busy;
  const has = !!s.session;
  const usable = has || !!s.profile_exists;
  const login = $("btn-login");
  const loginBusy = busy && s.mode === "login";
  login.disabled = busy;
  login.setAttribute("aria-busy", String(loginBusy));
  login.querySelector(".label").textContent = loginBusy ? "در حال ورود…" : "ورود به اینستاگرام";
  const check = $("btn-check");
  const checkBusy = busy && s.mode === "check";
  check.disabled = busy || !usable;
  check.setAttribute("aria-busy", String(checkBusy));
  check.querySelector(".label").textContent = checkBusy ? "در حال بررسی…" : "ورود با نشست ذخیره‌شده";
  $("btn-clear").disabled = busy || !usable;
  for (const id of Object.keys(FIELDS)) $(id).readOnly = busy;
  const cancel = $("btn-cancel");
  cancel.hidden = !(busy || s.browser_open);
  cancel.querySelector(".label").textContent = busy ? "لغو و بستن مرورگر" : "بستن مرورگر";
  $("replace-hint").hidden = !has || busy;
  const pbusy = busy && s.mode === "profile";
  const pb = $("btn-profile");
  pb.disabled = busy || !usable;
  pb.setAttribute("aria-busy", String(pbusy));
  pb.querySelector(".label").textContent = pbusy ? "در حال خواندن…" : "خواندن پروفایل";
  $("pu").readOnly = busy;
  $("main").dataset.session = usable ? "1" : "0";
  stored("igs.ready", usable ? "1" : "0");
  login.classList.toggle("primary", !usable);
  pb.classList.toggle("primary", usable);
  $("prof-hint").textContent = usable
    ? "پروفایلی که تا ۱۲ ساعت پیش خوانده‌ای از ذخیره‌ها می‌آید و دوباره به اینستاگرام نمی‌رود. برای خواندن تازه، «تازه‌سازی» روی کارت را بزن."
    : "اول در بخش «ورود به حساب» وارد اینستاگرام شو؛ بعد اینجا هر یوزرنیمی را بخوان.";
  syncBusy();
}

// A wrong password is cleared and refocused so it is never re-sent by habit.
function reactToFailure(s) {
  if (s.state !== "failed" || S.reacted === s.run) return;
  S.reacted = s.run;
  const kind = (s.outcome || {}).kind;
  if (s.mode === "profile" || s.mode === "details") { if (kind === "not_found") { $("pu").focus({ preventScroll: true }); $("pu").select(); } return; }
  if (kind === "bad_username") $("u").focus({ preventScroll: true });
  else if (kind === "bad_password" || kind === "bad_credentials") {
    $("p").value = "";
    $("p").focus({ preventScroll: true });
  }
}

const LOGIN_IDS = { username: "u", password: "p", proxy: "x" };
const BAD_NAME = "این یوزرنیم یا لینک درست نیست. یوزرنیم فقط حروف انگلیسی، عدد، نقطه و _ دارد؛ لینک پست یا صفحه‌های دیگر اینستاگرام قبول نیست.";

async function start(path, body, ids = LOGIN_IDS) {
  let r;
  try { r = await api(path, body); } catch { S.offline = true; renderChip(S.snap); return; }
  if (r.status === 422) {
    for (const f of (r.data && r.data.fields) || []) {
      const id = ids[f];
      if (id) setError(id, f === "proxy" ? "آدرس پراکسی معتبر نیست." : id === "pu" ? BAD_NAME : "این فیلد خالی است یا خیلی بلند است.");
    }
    return;
  }
  poll();
}

async function onSubmit(e) {
  e.preventDefault();
  const username = $("u").value.trim().replace(/^@/, "");
  const password = $("p").value;
  const proxy = $("x").value.trim();
  const proxyBad = proxy && !PROXY_RE.test(proxy);
  setError("u", username ? "" : "یوزرنیم را بنویس.");
  setError("p", password ? "" : "پسورد را بنویس.");
  setError("x", proxyBad ? "آدرس پراکسی باید با http://، https:// یا socks5:// شروع شود." : "");
  const bad = !username ? $("u") : !password ? $("p") : proxyBad ? $("x") : null;
  if (bad) {
    if (bad === $("x")) openAdvanced(true);
    bad.focus();
    return;
  }
  await start("/api/login", { username, password, proxy });
}

let clearTimer = 0;
function resetClear() {
  clearTimeout(clearTimer);
  const btn = $("btn-clear");
  btn.classList.remove("confirm");
  btn.querySelector(".label").textContent = "پاک‌کردن نشست";
}

function onClear() {
  const btn = $("btn-clear");
  if (!btn.classList.contains("confirm")) {
    btn.classList.add("confirm");
    btn.querySelector(".label").textContent = "مطمئنی؟ دوباره بزن";
    clearTimer = setTimeout(resetClear, 4000);
    return;
  }
  resetClear();
  api("/api/session/clear", {}).then(() => poll());
}

/* ---------- highlights, fine details and similar accounts ---------- */
const NOT_READ = "برای این پروفایل هنوز خوانده نشده؛ «تازه‌سازی از اینستاگرام» را بزن.";
const ACCOUNT_TYPE = { 1: "حساب شخصی", 2: "حساب کسب‌وکار", 3: "حساب سازندهٔ محتوا" };

function highlightsSection(user, data) {
  const items = (data && data.items) || [];
  const grid = items.length
    ? h("ul", { class: "hl-grid" }, items.slice(0, 40).map((hl) => h("li", {},
      h("a", { class: "hl", href: "https://www.instagram.com" + hl.url, target: "_blank", rel: "noopener noreferrer", title: "باز کردن در اینستاگرام" },
        h("span", { class: "hl-cover", "aria-hidden": "true" }, icon("circle-play"),
          hl.has_cover ? h("img", { src: `/api/media/${encodeURIComponent(user)}/hl_${encodeURIComponent(hl.id)}?v=${encodeURIComponent(data.fetched_at || "")}`, alt: "", loading: "lazy",
            onerror: (e) => e.currentTarget.remove() }) : null),
        h("span", { class: "hl-title", dir: "auto", text: hl.title || "بدون عنوان" })))))
    : h("p", { class: "pnote", text: data ? "این حساب هایلایتی ندارد یا دیده نمی‌شود." : NOT_READ });
  return dsec("sec-hl-" + user, "circle-play", "هایلایت‌ها", data ? items.length : null, data ? sinceText(data.fetched_at) : "", grid);
}

function storyText(epoch) {
  const ago = Math.max(0, Date.now() / 1000 - epoch);
  return `${faDate.format(new Date(epoch * 1000))} (${agoText(ago)})${ago < 86400 ? "، هنوز فعال است" : ""}`;
}

function accountFacts(p) {
  const m = p.more || {}, rows = [];
  const chipsOf = (names, ic) => h("span", { class: "chips" }, names.map((n) => chipButton(ic, n)));
  const yes = (key, label) => { if (m[key]) rows.push(fact(label, "بله")); };
  if (m.account_type != null) rows.push(fact("نوع حساب", (ACCOUNT_TYPE[m.account_type] || "نوع " + fa(m.account_type)) + (p.category ? "، " + p.category : "")));
  if (m.address) rows.push(fact("آدرس", h("bdi", { dir: "auto", text: [m.address.street, m.address.city, m.address.zip].filter(Boolean).join("، ") })));
  if (m.contact) {
    if (m.contact.email) rows.push(fact("ایمیل", h("bdi", { dir: "ltr", text: m.contact.email })));
    if (m.contact.phone) rows.push(fact("تلفن", h("bdi", { dir: "ltr", text: m.contact.phone })));
  }
  if (m.story_at) rows.push(fact("آخرین استوری", storyText(m.story_at)));
  if (m.close_story_at) rows.push(fact("استوری «دوستان نزدیک»", storyText(m.close_story_at)));
  yes("live", "الان لایو است");
  if (m.reels != null) rows.push(fact("تعداد ریل", grouped.format(m.reels)));
  yes("threads", "نشان تردز دارد");
  yes("meta_verified", "Meta Verified دارد");
  if (m.bio_mentions) rows.push(fact("منشن‌های بیو", chipsOf(m.bio_mentions, "at")));
  if (m.bio_hashtags) rows.push(fact("هشتگ‌های بیو", h("span", { class: "chips" }, m.bio_hashtags.map((t) => h("span", { class: "tag" }, icon("hash"), h("bdi", { dir: "auto", text: t }))))));
  if (m.facepile) rows.push(fact("دنبال‌کنندگان مشترک", chipsOf(m.facepile, "users")));
  if (m.badges) rows.push(fact("نشان‌ها", m.badges.join("، ")));
  if (p.pronouns && p.pronouns.length) rows.push(fact("ضمیر", p.pronouns.join(" / ")));
  yes("similar", "فهرست حساب‌های مشابه دارد");
  yes("story_archive", "آرشیو استوری دارد");
  yes("memorial", "حساب یادبود است");
  yes("default_avatar", "عکس پروفایل پیش‌فرض است");
  yes("ai_label", "برچسب هوش مصنوعی دارد");
  yes("embeds_off", "جاسازی پست‌هایش بسته است");
  yes("unpublished", "حساب منتشرنشده است");
  if (m.facebook_id) rows.push(fact("شناسهٔ فیسبوک", h("bdi", { dir: "ltr", text: m.facebook_id })));
  if (p.user_id) rows.push(fact("شناسهٔ حساب", h("bdi", { dir: "ltr", text: p.user_id })));
  return rows;
}

function detailsSection(user, p) {
  const rows = p ? accountFacts(p) : [];
  if (!rows.length) return null;
  return h("details", { class: "more dsec-more" },
    h("summary", {}, icon("braces"), h("span", { text: `ریزجزئیات حساب (${fa(rows.length)} مورد)` }), icon("chevron", "chev")),
    h("dl", { class: "pfacts" }, rows));
}

function similarSection(user, data) {
  const items = (data && data.items) || [];
  const state = listState("similar:" + user);
  const list = h("div", { class: "dlist" });
  const draw = () => {
    const ctl = listControls(state, items.length, draw);
    list.replaceChildren(ctl.seg || "", h("ul", { class: "plist" }, items.slice(ctl.from, ctl.to).map(personRow)), ctl.pager || "");
  };
  if (items.length) draw();
  else list.append(h("p", { class: "pnote", text: data ? "اینستاگرام حساب مشابهی پیشنهاد نداد." : NOT_READ }));
  return dsec("sec-sim-" + user, "users", "حساب‌های مشابه", data ? items.length : null, data ? sinceText(data.fetched_at) : "", list);
}

/* ---------- limits and the count of what was asked of Instagram ---------- */
const LIMIT_FORM = [
  ["سقف خواندن", [["detail_posts", "پست اخیر برای خواندن کامل"], ["comments", "کامنت برای هر پست"], ["likers", "لایک‌کننده برای هر پست"],
    ["followers", "فالوور"], ["following", "فالووینگ"]]],
  ["سرعت", [["pause_min", "کمترین مکث بین کارها (ثانیه)"], ["pause_max", "بیشترین مکث (ثانیه)"], ["cooldown_min", "سکوت بعد از «صبر کن» (دقیقه)"]]],
  ["بودجهٔ اینستاگرام", [["pages_hour", "صفحه در ساعت"], ["pages_day", "صفحه در روز"], ["scrolls_hour", "ورق‌زدن فهرست در ساعت"], ["scrolls_day", "ورق‌زدن فهرست در روز"]]],
];
const METERS = [["page", "hour", "pages_hour", "صفحه در این ساعت"], ["page", "day", "pages_day", "صفحه در این روز"],
  ["scroll", "hour", "scrolls_hour", "ورق‌زدن فهرست در این ساعت"], ["scroll", "day", "scrolls_day", "ورق‌زدن فهرست در این روز"]];
const L = { built: false, dirty: false, note: "" };
const faTime = new Intl.DateTimeFormat("fa-IR", { timeStyle: "short" });

function meterRow(label, used, cap) {
  const ratio = cap ? Math.min(1, used / cap) : 0;
  return h("div", { class: "meter", "data-t": ratio >= 1 ? "bad" : ratio >= 0.8 ? "warn" : "ok" },
    h("div", { class: "meter-top" }, h("span", { text: label }), h("strong", { text: `${fa(used)} از ${fa(cap)}` })),
    h("div", { class: "meter-bar", role: "meter", "aria-label": label, "aria-valuemin": "0", "aria-valuemax": String(cap), "aria-valuenow": String(used) },
      h("span", { style: `--p:${ratio}` })));
}

function buildLimitForm(b) {
  const form = $("lform");
  form.replaceChildren(...LIMIT_FORM.map(([legend, fields]) => h("fieldset", { class: "lset" }, h("legend", { text: legend }),
    h("div", { class: "lgrid" }, fields.map(([key, label]) => {
      const [lo, hi] = b.ranges[key];
      return h("div", { class: "field" }, h("label", { for: "lim-" + key, text: label }),
        h("input", { id: "lim-" + key, name: key, type: "number", inputmode: "numeric", min: String(lo), max: String(hi), step: "1", dir: "ltr",
          value: String(b.limits[key]), "aria-describedby": "lh-" + key, oninput: () => { L.dirty = true; $("lim-" + key).removeAttribute("aria-invalid"); } }),
        h("p", { class: "help", id: "lh-" + key, text: `از ${fa(lo)} تا ${fa(hi)}، پیش‌فرض ${fa(b.defaults[key])}` }));
    })))),
    h("div", { class: "actions" },
      h("button", { type: "submit", class: "btn primary", id: "lim-save" }, icon("check"), h("span", { text: "ذخیرهٔ محدودیت‌ها" })),
      h("button", { type: "button", class: "btn", id: "lim-reset", onclick: resetLimits }, icon("refresh"), h("span", { text: "برگرداندن پیش‌فرض‌ها" }))),
    h("p", { class: "help", id: "lim-note", role: "status", "aria-live": "polite" }));
  L.built = true;
  L.dirty = false;
}

function renderBudget(b) {
  if (!b) return;
  const u = b.used, lim = b.limits, ratio = lim.pages_hour ? u.page.hour / lim.pages_hour : 0;
  const chip = $("chip-budget"), cool = b.cooldown;
  const text = cool ? `مکث تا ${faTime.format(new Date(cool.until * 1000))}` : `${fa(u.page.hour)} از ${fa(lim.pages_hour)} صفحه در این ساعت`;
  const key = text + "|" + (cool ? "c" : ratio >= 1 ? "b" : ratio >= 0.8 ? "w" : "o");
  if (chip.dataset.key !== key) {
    chip.dataset.key = key;
    chip.dataset.t = cool || ratio >= 1 ? "bad" : ratio >= 0.8 ? "warn" : "ok";
    chip.replaceChildren(icon(cool ? "hourglass" : "gauge"), h("span", { text }));
  }
  const banner = $("cool");
  banner.hidden = !cool;
  if (cool) {
    banner.replaceChildren(icon("hourglass"), h("div", {}, h("strong", { text: "اینستاگرام گفته بود صبر کن" }),
      h("p", { text: `تا ${faTime.format(new Date(cool.until * 1000))} هیچ درخواستی نمی‌فرستم. اگر مطمئنی می‌توانی مکث را تمام کنی.` })),
      h("button", { type: "button", class: "btn", onclick: () => api("/api/cooldown/clear", {}).then(poll) }, h("span", { text: "پایان مکث" })));
  }
  $("lsum").textContent = `${fa(u.page.day)} از ${fa(lim.pages_day)} امروز`;
  $("meters").replaceChildren(...METERS.map(([kind, win, cap, label]) => meterRow(label, u[kind][win], lim[cap])));
  if (!L.built || (!L.dirty && JSON.stringify(b.limits) !== L.shown)) buildLimitForm(b);
  L.shown = JSON.stringify(b.limits);
}

async function saveLimits(e) {
  e.preventDefault();
  const values = {};
  for (const input of $("lform").querySelectorAll("input")) values[input.name] = Number(input.value);
  const r = await api("/api/limits", { values });
  const note = $("lim-note");
  if (r.status === 422) {
    const bad = (r.data && r.data.fields) || [];
    for (const key of bad) { const el = $("lim-" + key); if (el) el.setAttribute("aria-invalid", "true"); }
    note.textContent = "این مقدارها خارج از بازه‌اند یا درست نیستند: " + bad.map((k) => (LIMIT_FORM.flatMap((g) => g[1]).find((f) => f[0] === k) || [k, k])[1]).join("، ");
    note.dataset.t = "bad";
    const first = $("lim-" + bad[0]);
    if (first) first.focus();
    return;
  }
  if (r.ok) { L.dirty = false; note.textContent = "ذخیره شد."; note.dataset.t = "ok"; poll(); }
}

async function resetLimits() {
  const r = await api("/api/limits/reset", {});
  if (r.ok) { L.built = false; L.dirty = false; poll(); const n = $("lim-note"); if (n) n.textContent = ""; }
}

/* ---------- comments and likers under a post ---------- */
function readDetails(user, opts) {
  return start("/api/details", { username: user, proxy: $("x").value.trim(), ...opts }, PROFILE_IDS);
}

// One person in a list (similar accounts, the people who liked a post): a click reads that profile.
function personRow(s) {
  const avatar = h("span", { class: "avatar", "aria-hidden": "true" }, (s.username || "?").slice(0, 1).toUpperCase(),
    s.avatar && /^https:\/\//.test(s.avatar) ? h("img", { src: s.avatar, alt: "", loading: "lazy", referrerpolicy: "no-referrer", onerror: (e) => e.currentTarget.remove() }) : null);
  return h("li", {}, h("button", { type: "button", class: "prow", "aria-label": "خواندن پروفایل " + (s.full_name || s.username), onclick: () => readProfile(s.username, false) },
    avatar,
    h("span", {}, h("strong", {}, h("bdi", { dir: "auto", text: s.full_name || s.username }), s.verified ? icon("verified", "okmark") : null, s.private ? icon("lock", "lockmark") : null),
      h("small", {}, h("bdi", { dir: "ltr", text: "@" + s.username }))),
    h("span", { class: "num" }, icon("search"))));
}

// A short list kept in memory with a page size and a pager; rows come from build(item).
function shortList(key, items, build, tag) {
  const state = listState(key);
  const box = h("div", { class: "dlist" });
  const draw = () => {
    const ctl = listControls(state, items.length, draw);
    box.replaceChildren(ctl.seg || "", h("ul", { class: "plist" + (tag ? " " + tag : "") }, items.slice(ctl.from, ctl.to).map(build)), ctl.pager || "");
  };
  draw();
  return box;
}

function commentRow(c) {
  return h("li", { class: "crow" },
    h("div", { class: "chead" }, chipButton("at", c.user), c.verified ? icon("verified", "okmark") : null,
      c.at ? h("time", { datetime: new Date(c.at * 1000).toISOString(), text: faDate.format(new Date(c.at * 1000)) }) : null,
      c.pinned ? h("span", { class: "tag" }, icon("pin"), h("span", { text: "سنجاق‌شده" })) : null),
    h("p", { class: "ctext", dir: "auto", text: c.text || "(بدون متن)" }),
    h("div", { class: "cmeta" }, c.likes != null ? mini("heart", grouped.format(c.likes), "لایک") : null,
      c.replies ? mini("comment", grouped.format(c.replies), "پاسخ") : null, c.edited ? h("span", { text: "ویرایش‌شده" }) : null));
}

const LIKERS_NOTE = {
  hidden: "صاحب این پست شمارش لایک را پنهان کرده، پس فهرستی نیست.",
  none: "این پست هنوز لایکی ندارد.",
  no_count: "عدد لایک در صفحه همان چیزی نبود که انتظار داشتم؛ کلیک نکردم.",
  no_click: "روی عدد لایک کلیک نشد.",
  empty: "اینستاگرام فهرستی نداد.",
};

function detailBlock(user, p, det) {
  const again = h("button", { type: "button", class: "btn", onclick: () => readDetails(user, { codes: [p.code] }) },
    icon("refresh"), h("span", { text: det ? "خواندن دوبارهٔ کامنت و لایک‌کنندگان این پست" : "خواندن کامنت و لایک‌کنندگان این پست" }));
  if (!det) return h("div", { class: "dblock" }, h("p", { class: "pnote", text: "کامنت‌ها و لایک‌کنندگان این پست هنوز خوانده نشده." }), again);
  if (det.error) {
    return h("div", { class: "dblock" }, h("p", { class: "pnote", text: det.error === "not_found" ? "این پست دیگر در اینستاگرام پیدا نشد." : "صفحهٔ این پست باز نشد." }), again);
  }
  const comments = det.comments || [], likers = det.likers || [];
  const parts = [h("p", { class: "pnote" }, icon("clock"), " " + sinceText(det.read_at))];
  parts.push(h("h5", { class: "dh" }, icon("comment"), h("span", { text: p.comments_disabled ? "کامنت‌ها بسته است" : `کامنت‌ها، ${fa(comments.length)} از ${det.comments_total != null ? grouped.format(det.comments_total) : "؟"}` })));
  if (comments.length) parts.push(shortList(`comments:${user}:${p.code}`, comments, commentRow, "comments"));
  if (det.comments_more) parts.push(h("p", { class: "pnote", text: "کامنت‌های بیشتری هست؛ برای دیدنشان «کامنت برای هر پست» را در محدودیت‌ها بالا ببر." }));
  parts.push(h("h5", { class: "dh" }, icon("heart"), h("span", { text: likers.length ? `لایک‌کنندگان، ${fa(likers.length)} از ${det.likers_total != null ? grouped.format(det.likers_total) : "؟"}` : "لایک‌کنندگان" })));
  if (likers.length) parts.push(shortList(`likers:${user}:${p.code}`, likers, personRow));
  else if (det.likers_note) parts.push(h("p", { class: "pnote", text: LIKERS_NOTE[det.likers_note] || "فهرست لایک‌کنندگان نیامد." }));
  if (det.likers_more) parts.push(h("p", { class: "pnote", text: "اینستاگرام فقط حدود صد نفر اول را نشان می‌دهد؛ بیشتر از آن در دسترس نیست." }));
  parts.push(again);
  return h("div", { class: "dblock" }, parts);
}

function postsActions(user, data, details) {
  const items = (data && data.items) || [];
  if (!items.length) return null;
  const n = Math.min(((S.snap && S.snap.budget && S.snap.budget.limits.detail_posts) || 5), items.length);
  const done = Object.keys((details && details.posts) || {}).length;
  return h("div", { class: "dact" },
    h("button", { type: "button", class: "btn", onclick: () => readDetails(user, { count: n }) }, icon("comment"), h("span", { text: `خواندن کامنت و لایک‌کنندگان ${fa(n)} پست اخیر` })),
    h("p", { class: "pnote", text: `هر پست یک صفحه باز می‌کند. ${done ? fa(done) + " پست قبلاً خوانده شده. " : ""}سقف‌ها در «محدودیت‌ها» است.` }));
}

/* ---------- reading a profile ---------- */
const PROFILE_IDS = { username: "pu", proxy: "x" };

async function readProfile(name, fresh) {
  const username = String(name || "").trim();
  setError("pu", username ? "" : "یوزرنیم یا لینک پروفایل را بنویس.");
  if (!username) { $("pu").focus(); return; }
  $("pu").value = username;
  await start("/api/profile", { username, fresh: !!fresh, proxy: $("x").value.trim() }, PROFILE_IDS);
}

function onProfileSubmit(e) {
  e.preventDefault();
  readProfile($("pu").value, false);
}

/* ---------- saved profiles: a short list, a page size, a pager ---------- */
const SIZES = [5, 10, 15, 20];
const P = { size: Number(stored("igs.psize")) || 5, page: 0, total: 0, items: [], current: "" };
if (!SIZES.includes(P.size)) P.size = 5;

function syncBusy() {
  const busy = !!(S.snap && S.snap.busy);
  for (const b of document.querySelectorAll("#plist .prow")) b.disabled = busy;
}

function savedRow(it) {
  const name = it.full_name || it.username;
  const avatar = h("span", { class: "avatar", "aria-hidden": "true" }, it.username.slice(0, 1).toUpperCase(),
    it.has_avatar ? h("img", { src: `/api/avatar/${encodeURIComponent(it.username)}?v=${encodeURIComponent(it.fetched_at || "")}`,
      alt: "", loading: "lazy", onerror: (e) => e.currentTarget.remove() }) : null);
  const count = typeof it.followers === "number" ? (it.followers >= 10000 ? compact : grouped).format(it.followers) : "–";
  return h("li", {}, h("button", { type: "button", class: "prow", "aria-current": P.current === it.username ? "true" : null,
    "aria-label": "نمایش پروفایل " + name, onclick: () => readProfile(it.username, false) },
    avatar,
    h("span", {}, h("strong", {}, h("bdi", { dir: "auto", text: name }), it.is_private ? icon("lock", "lockmark") : null),
      h("small", {}, h("bdi", { dir: "ltr", text: "@" + it.username }))),
    h("span", { class: "num" }, count, h("small", { text: "فالوور" }))));
}

function renderSeg() {
  $("psize").replaceChildren(...SIZES.map((n) => h("button", {
    type: "button", "aria-pressed": String(n === P.size), text: fa(n),
    onclick: () => { P.size = n; P.page = 0; stored("igs.psize", String(n)); renderSeg(); loadSaved(); },
  })));
}

function renderSaved() {
  const pages = Math.max(1, Math.ceil(P.total / P.size));
  $("saved").hidden = P.total === 0;
  $("plist").replaceChildren(...P.items.map(savedRow));
  const pager = $("pager");
  pager.hidden = pages <= 1;
  pager.replaceChildren(
    h("button", { type: "button", class: "btn", disabled: P.page <= 0, onclick: () => { P.page -= 1; loadSaved(); } },
      icon("chev-r"), h("span", { text: "قبلی" })),
    h("span", { class: "where", text: `صفحهٔ ${fa(P.page + 1)} از ${fa(pages)}` }),
    h("button", { type: "button", class: "btn", disabled: P.page >= pages - 1, onclick: () => { P.page += 1; loadSaved(); } },
      h("span", { text: "بعدی" }), icon("chev-l")));
  syncBusy();
}

async function loadSaved() {
  let r;
  try { r = await api(`/api/profiles?offset=${P.page * P.size}&limit=${P.size}`); } catch { return; }
  if (!r.ok) return;
  P.total = r.data.total;
  P.items = r.data.items;
  const pages = Math.max(1, Math.ceil(P.total / P.size));
  if (P.page >= pages) { P.page = pages - 1; return loadSaved(); }
  renderSaved();
}

// After a profile has been read: mark it in the list, and if it is new, show the list from its top.
function noteProfileRun(d) {
  if (d.mode !== "profile" || d.state !== "success" || S.listedRun === d.run) return;
  S.listedRun = d.run;
  const r = d.result || {};
  P.current = (r.profile || {}).username || "";
  if (!r.cached) P.page = 0;
  loadSaved();
}

/* ---------- the dossier: what is saved about one person, section by section ---------- */
const PG = {};
const defaultSize = () => (SIZES.includes(Number(stored("igs.psize"))) ? Number(stored("igs.psize")) : 5);
const listState = (key) => PG[key] || (PG[key] = { size: defaultSize(), page: 0 });
const faDate = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { dateStyle: "medium", timeStyle: "short" });
const shortNum = (n) => (n >= 10000 ? compact : grouped).format(n);
const sinceText = (iso) => (iso ? "خوانده‌شده، " + agoText(Math.max(0, (Date.now() - Date.parse(iso)) / 1000)) : "");

// Page size (5, 10, 15, 20: remembered for new lists) and a pager, for a list that is already in memory.
function listControls(state, total, redraw) {
  const pages = Math.max(1, Math.ceil(total / state.size));
  state.page = Math.min(state.page, pages - 1);
  const go = (to) => { state.page = to; redraw(); };
  const seg = total <= SIZES[0] ? null : h("div", { class: "seg", role: "group", "aria-label": "تعداد در هر صفحه" },
    SIZES.map((n) => h("button", { type: "button", "aria-pressed": String(n === state.size), text: fa(n),
      onclick: () => { state.size = n; state.page = 0; stored("igs.psize", String(n)); redraw(); } })));
  const pager = pages <= 1 ? null : h("nav", { class: "pager", "aria-label": "صفحه‌بندی" },
    h("button", { type: "button", class: "btn", disabled: state.page <= 0, onclick: () => go(state.page - 1) }, icon("chev-r"), h("span", { text: "قبلی" })),
    h("span", { class: "where", text: `صفحهٔ ${fa(state.page + 1)} از ${fa(pages)}` }),
    h("button", { type: "button", class: "btn", disabled: state.page >= pages - 1, onclick: () => go(state.page + 1) }, h("span", { text: "بعدی" }), icon("chev-l")));
  return { seg, pager, from: state.page * state.size, to: (state.page + 1) * state.size };
}

function dsec(id, iconName, title, count, when, ...kids) {
  return h("section", { class: "dsec", "aria-labelledby": id },
    h("div", { class: "dsec-head" },
      h("h4", { id }, icon(iconName), h("span", { text: title }), count != null ? h("span", { class: "dcount", text: fa(count) }) : null),
      when ? h("span", { class: "dwhen", text: when }) : null),
    ...kids);
}

const chipButton = (iconName, name) => h("button", { type: "button", class: "tag action", title: "خواندن پروفایل این حساب", onclick: () => readProfile(name, false) },
  icon(iconName), h("bdi", { dir: "ltr", text: name }));
const KIND_FA = { photo: ["image", "عکس"], album: ["layers", "آلبوم"], reel: ["film", "ریل"], video: ["play", "ویدیو"] };

function mini(iconName, value, label, title) {
  return h("span", { class: "mini", title: title || null }, icon(iconName),
    h("span", { "aria-hidden": "true", text: value }), h("span", { class: "sr", text: label + " " + value }));
}

function postFacts(p) {
  const out = [];
  if (p.likes_hidden) out.push(mini("eye-off", "پنهان", "لایک", "صاحب پست شمارش لایک را پنهان کرده"));
  else if (p.likes != null) out.push(mini("heart", shortNum(p.likes), "لایک", grouped.format(p.likes)));
  if (p.comments_disabled) out.push(mini("comment", "بسته", "کامنت", "کامنت این پست بسته است"));
  else if (p.comments != null) out.push(mini("comment", shortNum(p.comments), "کامنت", grouped.format(p.comments)));
  if (p.views != null) out.push(mini("play", shortNum(p.views), "بازدید", grouped.format(p.views)));
  if (p.location && p.location.name) out.push(mini("pin-map", p.location.name, "مکان"));
  if (p.tagged && p.tagged.length) out.push(mini("tag", fa(p.tagged.length), "فرد تگ‌شده"));
  if (p.pinned) out.push(mini("pin", "سنجاق‌شده", "وضعیت"));
  return out;
}

function fact(label, ...value) {
  return h("div", { class: "pfact" }, h("dt", { text: label }), h("dd", {}, ...value));
}

function postDetail(user, p, det) {
  const rows = [fact("زمان انتشار", faDate.format(new Date(p.taken_at * 1000)))];
  if (p.caption) rows.push(fact("متن کامل", h("span", { class: "pcaption", dir: "auto", text: p.caption })));
  if (p.hashtags.length) rows.push(fact("هشتگ‌ها", h("span", { class: "chips" }, p.hashtags.map((t) => h("span", { class: "tag" }, icon("hash"), h("bdi", { dir: "auto", text: t }))))));
  if (p.mentions.length) rows.push(fact("منشن‌ها", h("span", { class: "chips" }, p.mentions.map((m) => chipButton("at", m)))));
  if (p.tagged.length) rows.push(fact("افراد تگ‌شده", h("span", { class: "chips" }, p.tagged.map((t) => chipButton("tag", t.username)))));
  if (p.coauthors.length) rows.push(fact("همکار پست", h("span", { class: "chips" }, p.coauthors.map((m) => chipButton("users", m)))));
  if (p.sponsors.length || p.paid_partnership) {
    rows.push(fact("همکاری تبلیغاتی", p.sponsors.length ? h("span", { class: "chips" }, p.sponsors.map((m) => chipButton("briefcase", m))) : "بله"));
  }
  if (p.location) {
    const l = p.location;
    rows.push(fact("مکان", h("bdi", { dir: "auto", text: [l.name, l.city, l.address].filter(Boolean).join("، ") }),
      l.lat != null && l.lng != null ? h("span", { class: "muted", text: `  (${l.lat}, ${l.lng})` }) : null));
  }
  if (p.music) rows.push(fact(p.music.kind === "music" ? "آهنگ" : "صدا", h("bdi", { dir: "auto", text: [p.music.title, p.music.artist].filter(Boolean).join(" از ") })));
  if (p.alt) rows.push(fact("متن جایگزین عکس", h("span", { class: "pcaption", dir: "auto", text: p.alt })));
  if (p.fb_likes != null || p.fb_comments != null) {
    rows.push(fact("روی فیسبوک (بازنشر)", [p.fb_likes != null ? grouped.format(p.fb_likes) + " لایک" : "", p.fb_comments != null ? grouped.format(p.fb_comments) + " کامنت" : ""].filter(Boolean).join("، ")));
  }
  if (p.items.length > 1 || (p.items[0] && p.items[0].video)) {
    rows.push(fact(p.kind === "album" ? "اسلایدها" : "فایل‌ها", h("ol", { class: "slides" }, p.items.map((it, i) => h("li", {},
      `${it.type === "video" ? "ویدیو" : "عکس"} ${grouped.format(it.width || 0)}×${grouped.format(it.height || 0)} `,
      ...[["image", "تصویر"], ["video", "ویدیو"]].filter(([k]) => it[k] && /^https:\/\//.test(it[k]))
        .map(([k, label]) => h("a", { class: "plink inline", href: it[k], target: "_blank", rel: "noopener noreferrer" }, icon("open"), h("span", { text: label }))))))));
  }
  rows.push(fact("شناسهٔ پست", h("bdi", { dir: "ltr", text: p.code + "  /  " + p.id })));
  const json = JSON.stringify(p, null, 2);
  return h("div", { class: "pdetail" }, h("dl", { class: "pfacts" }, rows), detailBlock(user, p, det),
    h("div", { class: "acts" },
      h("a", { class: "btn", href: "https://www.instagram.com" + p.url, target: "_blank", rel: "noopener noreferrer" }, icon("open"), h("span", { text: "باز کردن در اینستاگرام" })),
      h("button", { type: "button", class: "btn", onclick: (e) => copyText(e.currentTarget, json) }, icon("copy"), h("span", { text: "کپی JSON پست" }))));
}

function postRow(user, p, stamp, det) {
  const [kindIcon, kindText] = KIND_FA[p.kind] || KIND_FA.photo;
  const thumb = h("span", { class: "pthumb", "aria-hidden": "true" }, icon(kindIcon),
    p.has_thumb ? h("img", { src: `/api/media/${encodeURIComponent(user)}/${encodeURIComponent(p.code)}?v=${encodeURIComponent(stamp || "")}`, alt: "", loading: "lazy",
      onerror: (e) => e.currentTarget.remove() }) : null);
  const kindLabel = p.kind === "album" ? `آلبوم، ${fa(p.items_count)} اسلاید` : kindText;
  return h("details", { class: "post", "data-code": p.code },
    h("summary", {}, thumb,
      h("span", { class: "pmain" },
        h("span", { class: "pline" }, h("span", { class: "tag" }, icon(kindIcon), h("span", { text: kindLabel })), h("time", { datetime: p.taken_iso, text: faDate.format(new Date(p.taken_at * 1000)) })),
        h("span", { class: "pcap", dir: "auto", text: p.caption || "بدون متن" }),
        h("span", { class: "pmeta" }, postFacts(p))),
      icon("chevron", "chev")),
    postDetail(user, p, det));
}

const EMPTY_POSTS = {
  private: "این حساب خصوصی است؛ پست‌هایش دیده نمی‌شود.",
  empty: "این حساب هنوز پستی ندارد.",
  unread: "اینستاگرام پست‌ها را نفرستاد. «تازه‌سازی از اینستاگرام» را بزن.",
};

function postsSection(user, data, details) {
  const items = (data && data.items) || [];
  const state = listState("posts:" + user);
  const list = h("div", { class: "dlist" });
  const draw = () => {
    const ctl = listControls(state, items.length, draw);
    list.replaceChildren(ctl.seg || "", h("ul", { class: "plist posts" }, items.slice(ctl.from, ctl.to).map((p) => h("li", {}, postRow(user, p, data.fetched_at, ((details || {}).posts || {})[p.code])))), ctl.pager || "");
  };
  if (items.length) draw();
  else list.append(h("p", { class: "pnote", text: data ? (EMPTY_POSTS[data.reason] || "پستی نیست.") : "پست‌های این پروفایل هنوز خوانده نشده؛ «تازه‌سازی از اینستاگرام» را بزن." }));
  return dsec("sec-posts-" + user, "layers", "پست‌های اخیر", data ? items.length : null, data ? sinceText(data.fetched_at) : "", postsActions(user, data, details), list);
}

function dossierSections(user, d) {
  return [postsSection(user, d.posts, d.details), highlightsSection(user, d.highlights), detailsSection(user, d.profile), similarSection(user, d.similar)].filter(Boolean);
}

async function loadDossier(box, opened) {
  const holder = box.querySelector(".dossier");
  if (!holder) return;
  const user = holder.dataset.user;
  let r;
  try { r = await api("/api/dossier/" + encodeURIComponent(user)); } catch { return; }
  if (!r.ok || !holder.isConnected) return;
  holder.replaceChildren(...dossierSections(user, r.data));
  const first = (opened || []).map((c) => holder.querySelector(`.post[data-code="${CSS.escape(c)}"]`)).filter(Boolean);
  for (const el of first) el.open = true;
  if (first[0]) first[0].scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
}

/* ---------- polling ---------- */
// Returns true when the page must ask again at once (a new run arrived mid-cursor).
function apply(d) {
  const fresh = d.run !== S.run;
  if (fresh) {
    S.run = d.run;
    S.log = [];
    resetLogView();
  }
  if (fresh && S.cursor !== 0) {
    S.cursor = 0;
    return true;
  }
  S.log.push(...d.log);
  S.cursor = d.next;
  S.snap = d;
  renderSteps(d);
  renderLog();
  renderAnswer(d);
  renderForm(d);
  renderBudget(d.budget);
  reactToFailure(d);
  noteProfileRun(d);
  return false;
}

async function poll() {
  clearTimeout(S.timer);
  let again = false;
  try {
    const r = await api(`/api/status?since=${S.cursor}`);
    S.offline = !r.ok;
    if (r.ok) again = apply(r.data);
  } catch { S.offline = true; }
  renderChip(S.snap);
  S.timer = setTimeout(poll, again ? 0 : S.snap && S.snap.busy ? 700 : 2500);
}

function init() {
  $("x").value = stored("igs.proxy");
  if ($("x").value) openAdvanced(true);
  $("form").addEventListener("submit", onSubmit);
  for (const id of Object.keys(FIELDS)) $(id).addEventListener("input", () => setError(id, ""));
  $("x").addEventListener("input", () => stored("igs.proxy", $("x").value.trim()));
  $("pw-toggle").addEventListener("click", togglePw);
  $("adv-toggle").addEventListener("click", () => openAdvanced($("adv-toggle").getAttribute("aria-expanded") !== "true"));
  $("btn-check").addEventListener("click", () => start("/api/check", { proxy: $("x").value.trim() }));
  $("btn-clear").addEventListener("click", onClear);
  $("pform").addEventListener("submit", onProfileSubmit);
  $("lform").addEventListener("submit", saveLimits);
  $("pu").addEventListener("input", () => setError("pu", ""));
  renderSeg();
  loadSaved();
  $("btn-cancel").addEventListener("click", () => api("/api/cancel", {}).then(() => poll()));
  poll();
}
init();
