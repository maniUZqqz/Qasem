// «تنظیمات» (docs/ui/views.md → settings): session, limits, usage, connection, look, files.
// ≥768px: the section list beside the open section; phones: the list, then one section page with a back arrow.
import { h, icon, ltr, bdi, mount } from "../core/dom.js";
import { api, getLimits, setLimits, resetLimits, clearCooldown, clearSession, getFiles, avatarUrl, authLogout, getUsers, saveUser, removeUser } from "../core/api.js";
import { faNum, faDate, faTime, faDateTime, bytes } from "../core/format.js";
import { state, subscribe, pref, pokePolling } from "../core/store.js";
import { button, avatar, empty, skeleton, segmented, field, setBusy, toast } from "../core/ui.js";
import { confirm } from "../core/overlay.js";
import { startJob, cost } from "../core/jobs.js";
import { vpnView } from "./vpn.js";

const SECTIONS = [["session", "user", "حساب و نشست", "حساب ذخیره‌شده و ورود"], ["limits", "gauge", "محدودیت‌ها", "سقف خواندن، دانلود و سرعت"],
  ["usage", "bar-chart", "مصرف", "مصرف این ساعت و امروز، مکث"], ["browser", "window", "مرورگر", "نمایش یا پنهان بودن پنجرهٔ Chromium"],
  ["connection", "globe", "اتصال", "پراکسی برای رسیدن به اینستاگرام"],
  ["split", "layers", "تقسیم کار", "چند سیستم روی یک کار، بی‌آنکه چیزی دو بار خوانده شود"],
  ["vpn", "pin-map", "VPN و نشانی", "کشورِ خروج و نشانی‌ای که اینستاگرام می‌بیند"],
  ["look", "sun", "ظاهر", "روشن، تیره یا همانند سیستم"], ["files", "folder", "فایل‌ها", "حجم و جای فایل‌های دانلودشده"],
  ["me", "key", "ورود به آباگرام", "حسابِ آبا وانِ تو و خروج"], ["users", "users", "کاربران", "چه کسانی وارد آباگرام شوند"],
].map(([id, ic, label, hint]) => ({ id, icon: ic, label, hint }));
const visible = () => SECTIONS.filter((x) => x.id !== "users" || state.me?.admin);   // «کاربران»: the admin only
const ROLE_FA = { full: "همه‌کاره", json: "فقط JSON" };
const ROLE_HINT = { full: "همهٔ بخش‌ها، از جمله حساب‌های اینستاگرام و صف", json: "فقط دیدنِ پیج‌ها، دانلود و آپلودِ JSON" };
const GROUPS = [["خواندن", ["posts", "detail_posts", "comments", "likers", "highlights", "highlight_items", "followers", "following"]],
  ["دانلود", ["media_files", "media_file_mb", "media_job_mb"]], ["سرعت", ["harvest_scroll", "pause_min", "pause_max", "cooldown_min", "request_check_min"]],
  ["بودجهٔ اینستاگرام", ["pages_hour", "pages_day", "scrolls_hour", "scrolls_day", "harvests_hour", "harvests_day", "lookups_hour", "lookups_day"]]];
// the fast profile reader (ig_lookup) is off until he says so: its limits show only when the server has it on
const fastOn = () => !!state.status?.fast_profiles;
const LABEL = {
  posts: "پست برای خواندن", detail_posts: "پست اخیر برای کامنت و لایک", comments: "کامنت برای هر پست", likers: "لایک‌کننده برای هر پست",
  highlights: "هایلایت در هر بار", highlight_items: "آیتم از هر هایلایت", followers: "فالوور", following: "فالووینگ",
  media_files: "فایل در هر دانلود", media_file_mb: "حجم هر فایل (مگابایت)", media_job_mb: "حجم هر دانلود (مگابایت)",
  harvest_scroll: "فاصلهٔ دو اسکرولِ فهرست فالوورها (ثانیه)",
  pause_min: "کمترین مکث (ثانیه)", pause_max: "بیشترین مکث (ثانیه)", cooldown_min: "سکوت بعد از «صبر کن» (دقیقه)", request_check_min: "بررسی درخواست فالو هر (دقیقه)",
  pages_hour: "صفحه در ساعت", pages_day: "صفحه در روز", scrolls_hour: "ورق‌زدن در ساعت", scrolls_day: "ورق‌زدن در روز",
  harvests_hour: "خواندن کامل فهرست، صفحه در ساعت", harvests_day: "خواندن کامل فهرست، صفحه در روز",
  lookups_hour: "خواندن سریع پروفایل، نفر در ساعت", lookups_day: "خواندن سریع پروفایل، نفر در روز" };
const PROXY = /^(https?|socks5h?|socks4a?):\/\/([^\s:@/]+(:[^\s@/]*)?@)?[^\s:@/]+:\d{1,5}\/?$/i;

// Persian/Arabic digits and group marks typed into a number field → an integer (NaN when it is not one).
const toInt = (s) => (s = String(s).replace(/[۰-۹٠-٩]/g, (d) => d.charCodeAt(0) & 15).replace(/[٬,\s]/g, ""), /^\d+$/.test(s) ? Number(s) : NaN);
const keyed = (el, k) => { el.dataset.k = k; return el; };   // a redraw gives focus back to the same control
const linkBtn = (label, href, ic, kind) => h("a", { class: ["btn", kind], href }, icon(ic), h("span", { text: label }));
const failed = (title, again) => empty({ icon: "alert", title, text: "برنامه جواب نداد. اگر پنجرهٔ برنامه بسته شده، دوباره اجرایش کن.",
  action: button({ label: "دوباره امتحان کن", icon: "refresh", onClick: again }) });

export function render(params = {}, ctx = {}) {
  let shown = null, at;
  const rows = visible().map((x) => h("a", { class: "sg-row", href: `#/settings/${x.id}`, "data-id": x.id },
    h("span", { class: "sg-row-ic" }, icon(x.icon)),
    h("span", { class: "sg-row-t" }, h("span", { class: "sg-row-l", text: x.label }), h("span", { class: "sg-row-h", text: x.hint })),
    icon("chev-l", { size: "sm", cls: "sg-row-go" })));
  // «تبادلِ JSON» is a page of its own; on phones (no tab for it) this row is the way there
  const exchange = h("a", { class: "sg-row sg-row-out", href: "#/exchange" }, h("span", { class: "sg-row-ic" }, icon("braces")),
    h("span", { class: "sg-row-t" }, h("span", { class: "sg-row-l", text: "تبادلِ JSON" }), h("span", { class: "sg-row-h", text: "دریافت و آپلودِ JSONِ پیج‌ها" })),
    icon("chev-l", { size: "sm", cls: "sg-row-go" }));
  const main = h("div", { class: "sg-main" });
  const el = h("div", { class: "sg" }, h("div", { class: "sg-side" }, h("h1", { class: "sg-h1", text: "تنظیمات" }),
    h("nav", { class: "sg-nav", "aria-label": "بخش‌های تنظیمات" }, rows, exchange)), main);
  const sig = (s) => JSON.stringify([s?.session, s?.budget, s?.busy && s.mode]);
  let last = sig(state.status);

  function draw() {
    const keep = main.contains(document.activeElement) ? document.activeElement.dataset?.k : null;
    const s = SECTIONS.find((x) => x.id === shown);
    mount(main, h("header", { class: "sg-head" },
      h("button", { type: "button", class: "icon-btn sg-back", "aria-label": "بازگشت به تنظیمات", onclick: () => ctx.back?.("/settings") }, icon("arrow-r")),
      h("h2", { class: "sg-h2", tabindex: "-1", text: s.label })),
    VIEWS[shown](draw));
    if (keep) main.querySelector(`[data-k="${keep}"]`)?.focus({ preventScroll: true });
  }

  function update(p = {}) {
    const open = visible().some((x) => x.id === p.section) ? p.section : null;
    if (open === at) return;
    const first = at === undefined, prev = shown;
    at = open;
    el.classList.toggle("sg-at-list", !open);
    if ((open || "session") !== shown) {
      shown = open || "session";
      rows.forEach((r) => (r.dataset.id === shown ? r.setAttribute("aria-current", "page") : r.removeAttribute("aria-current")));
      draw();
    }
    if (first) return;
    window.scrollTo({ top: 0 });
    (open ? main.querySelector(".sg-h2") : rows.find((r) => r.dataset.id === prev))?.focus({ preventScroll: true });
  }

  const off = subscribe("status", (s) => {   // session and usage follow the poll; other sections hold the person's edits
    const now = sig(s);
    if (now !== last && (last = now) && (shown === "session" || shown === "usage")) draw();
  });
  update(params);
  return { el, update, destroy: off };
}

function sessionView() {
  const s = state.status, me = s?.session;
  if (!s) return h("div", { class: "sg-card" }, skeleton("avatar"), h("div", { class: "sg-grow" }, skeleton("line", 2)));
  if (!me) return empty({ icon: "user", title: "هنوز وارد نشده‌ای", text: "برای خواندن از اینستاگرام اول با حساب خودت وارد شو.",
    action: linkBtn("ورود به اینستاگرام", "#/login", "login", "primary") });
  const checking = s.busy && s.mode === "check", wait = s.busy && !checking ? "صبر کن کار در حال اجرا تمام شود" : null;
  return h("div", { class: "sg-stack" },
    h("div", { class: "sg-card" },
      avatar({ u: me.username, src: avatarUrl(me.username, me.saved_at), size: 64, ring: checking ? "loading" : "seen" }),
      h("div", { class: "sg-grow" },
        h("a", { class: "sg-acct", href: `#/u/${me.username}` }, ltr(`@${me.username}`)),
        me.saved_at ? h("p", { class: "sg-muted" }, "ذخیره‌شده در ", bdi(faDate(me.saved_at)), "، ", bdi(faTime(me.saved_at))) : null)),
    h("div", { class: "sg-acts" },
      keyed(button({ label: "بررسی نشست", icon: "shield", busy: checking, disabled: !!wait, title: wait,
        onClick: () => startJob("check", {}, { lines: cost("check") }) }), "check"),
      linkBtn("ورود با حساب دیگر", "#/login", "login")),
    h("div", { class: "sg-zone" },
      h("p", { class: "sg-muted", text: "با پاک‌کردن نشست، ورودِ ذخیره‌شده از این کامپیوتر برداشته می‌شود." }),
      keyed(button({ label: "پاک‌کردن نشست", icon: "trash", kind: "danger", disabled: !!s.busy, title: wait, onClick: forget }), "forget")));
}

// Ask first, then call the server and say how it went (the poll brings the new state).
async function act(question, call, done, fail) {
  if (!(await confirm({ danger: true, ...question }))) return;
  const r = await call().catch(() => null);
  if (r?.ok) pokePolling();
  toast(r?.ok ? done : fail, { tone: r?.ok ? "ok" : "danger" });
}
const forget = () => act({ title: "نشست ذخیره‌شده پاک شود؟", text: "برای خواندن دوباره باید وارد شوی.", cta: "پاک‌کردن نشست" },
  clearSession, "نشست پاک شد", "نشست پاک نشد. اگر کاری در حال اجراست صبر کن، بعد دوباره امتحان کن.");
const endCool = () => act({ title: "مکث همین حالا تمام شود؟", cta: "پایان مکث",
  text: "اینستاگرام خودش گفته بود صبر کن؛ تلاشِ زودتر از موعد ممکن است حساب را محدودتر کند." }, clearCooldown, "مکث تمام شد", "مکث تمام نشد. دوباره امتحان کن.");

function meter(label, used = 0, cap = 0, word) {
  const p = cap > 0 ? Math.min(1, used / cap) : 1;
  const tone = p >= 1 ? "full" : p >= 0.8 ? "high" : "ok";
  const text = `${faNum(used)} ${word} از ${faNum(cap)} ${word}`;
  return h("div", { class: ["sg-meter", `sg-${tone}`] },
    h("p", { class: "sg-meter-l", text: label }),
    h("p", { class: "sg-meter-v" }, h("bdi", {}, h("b", { class: "sg-big num", text: faNum(used) }), ` ${word}`), " از ", bdi(`${faNum(cap)} ${word}`)),
    h("div", { class: "sg-track", role: "meter", "aria-label": label, "aria-valuemin": 0, "aria-valuemax": cap,
      "aria-valuenow": Math.min(used, cap), "aria-valuetext": text }, h("i", { style: `inline-size:${Math.round(p * 1000) / 10}%` })),
    tone === "ok" ? null : h("p", { class: "sg-meter-s", text: tone === "full" ? "پر شده؛ کار تازه تا خالی شدنش شروع نمی‌شود." : "نزدیک سقف است." }));
}

function usageView() {
  const b = state.status?.budget;
  if (!b) return h("div", { class: "sg-stack" }, skeleton("line", 4));
  const L = b.limits || {}, u = b.used || {}, c = b.cooldown;
  return h("div", { class: "sg-stack" },
    h("div", { class: "sg-meters" },
      meter("صفحه در ساعت", u.page?.hour, L.pages_hour, "صفحه"), meter("صفحه در روز", u.page?.day, L.pages_day, "صفحه"),
      meter("ورق‌زدن در ساعت", u.scroll?.hour, L.scrolls_hour, "ورق‌زدن"), meter("ورق‌زدن در روز", u.scroll?.day, L.scrolls_day, "ورق‌زدن"),
      meter("خواندن کامل فهرست در ساعت", u.harvest?.hour, L.harvests_hour, "صفحه"), meter("خواندن کامل فهرست در روز", u.harvest?.day, L.harvests_day, "صفحه"),
      ...(fastOn() ? [meter("خواندن سریع پروفایل در ساعت", u.lookup?.hour, L.lookups_hour, "نفر"), meter("خواندن سریع پروفایل در روز", u.lookup?.day, L.lookups_day, "نفر")] : [])),
    c ? h("div", { class: "sg-card sg-cool", role: "status" }, h("span", { class: "sg-card-ic" }, icon("hourglass")),
      h("div", { class: "sg-grow" }, h("h3", { class: "sg-h3", text: "در مکثِ بعد از «صبر کن»" }),
        h("p", {}, "تا ساعت ", bdi(faTime(c.until)), " هیچ درخواستی به اینستاگرام فرستاده نمی‌شود."),
        c.reason ? h("p", { class: "sg-muted" }, bdi(c.reason)) : null),
      keyed(button({ label: "پایان مکث", onClick: endCool }), "cool"))
      : h("div", { class: "sg-card sg-calm" }, h("span", { class: "sg-card-ic" }, icon("circle-check")),
        h("p", { class: "sg-grow", text: "مکثی در کار نیست؛ اینستاگرام اخیراً نگفته صبر کن." })),
    h("p", { class: "sg-muted" }, "هر کار پیش از شروع می‌گوید چقدر از این سقف‌ها برمی‌دارد. سقف‌ها را در ",
      h("a", { class: "sg-link", href: "#/settings/limits", text: "محدودیت‌ها" }), " عوض کن."));
}

function limitsView(again) {
  const box = h("div", { class: "sg-stack" }, skeleton("line", 6)), fail = () => mount(box, failed("محدودیت‌ها خوانده نشد", again));
  getLimits().then((r) => (r.ok ? mount(box, limitsForm(r.data)) : fail()), fail);
  return box;
}

function limitsForm(snap = {}) {
  const limits = { ...snap.limits }, ranges = snap.ranges || {}, fields = {};
  const span = (k) => `از ${faNum(ranges[k]?.[0])} تا ${faNum(ranges[k]?.[1])}`;
  const note = h("p", { class: "sg-dirty", "aria-live": "polite" });
  const save = button({ label: "ذخیرهٔ محدودیت‌ها", kind: "primary", type: "submit", disabled: true });
  const dirty = (n = Object.keys(fields).filter((k) => toInt(fields[k].input.value) !== limits[k]).length) =>
    { save.disabled = !n; note.textContent = n ? `${faNum(n)} تغییر ذخیره نشده` : ""; };
  const sets = GROUPS.map(([legend, keys]) => h("fieldset", { class: "sg-set" }, h("legend", { class: "sg-h3", text: legend }),
    h("div", { class: "sg-grid" }, keys.filter((k) => k in limits && (!k.startsWith("lookups_") || fastOn())).map((k) => {
      const input = h("input", { class: "input num", type: "text", inputmode: "numeric", dir: "ltr", name: k, autocomplete: "off", value: faNum(limits[k]), oninput: () => dirty() });
      const help = ranges[k] ? `${span(k)}، پیش‌فرض ${faNum(snap.defaults?.[k])}` : null;
      return (fields[k] = Object.assign(field({ id: `sg-${k}`, label: LABEL[k] || k, input, help }), { input }));
    }))));
  const mark = (keys) => { keys.forEach((k) => fields[k]?.setError(`عدد باید ${span(k)} باشد.`)); fields[keys[0]]?.input.focus(); };
  async function submit(e) {
    e.preventDefault();
    const values = {}, bad = [];
    for (const [k, f] of Object.entries(fields)) {
      const v = toInt(f.input.value), [lo, hi] = ranges[k] || [0, Infinity];
      if (v >= lo && v <= hi) { values[k] = v; f.setError(""); } else bad.push(k);
    }
    if (bad.length) return mark(bad);
    setBusy(save, true);
    const r = await setLimits(values).catch(() => null);
    setBusy(save, false);
    if (r?.ok) { Object.assign(limits, r.data?.limits || values); dirty(); pokePolling(); toast("محدودیت‌ها ذخیره شد", { tone: "ok" }); }
    else if (r?.status === 422) mark(r.data?.fields || []);
    else toast("محدودیت‌ها ذخیره نشد. برنامه جواب نداد؛ دوباره امتحان کن.", { tone: "danger" });
  }
  async function reset() {
    if (!(await confirm({ title: "محدودیت‌ها به پیش‌فرض برگردند؟", text: "همهٔ عددهایی که عوض کرده‌ای کنار گذاشته می‌شوند.", cta: "برگرداندن پیش‌فرض‌ها" }))) return;
    const r = await resetLimits().catch(() => null);
    if (r?.ok) { form.replaceWith(limitsForm(r.data)); pokePolling(); }
    toast(r?.ok ? "محدودیت‌ها به پیش‌فرض برگشت" : "پیش‌فرض‌ها برنگشت. دوباره امتحان کن.", { tone: r?.ok ? "ok" : "danger" });
  }
  const form = h("form", { class: "sg-stack", novalidate: true, onsubmit: submit },
    h("p", { class: "sg-intro", text: "این سقف‌ها از حساب تو در برابر اینستاگرام محافظت می‌کنند. عدد کمتر یعنی امن‌تر و کندتر." }), sets,
    h("div", { class: "sg-bar" }, note, h("div", { class: "sg-acts" }, button({ label: "برگرداندن پیش‌فرض‌ها", kind: "ghost", onClick: reset }), save)));
  return form;
}

function connectionView() {
  const input = h("input", { class: "input", type: "text", dir: "ltr", value: pref("proxy") || "", placeholder: "socks5://127.0.0.1:10808",
    autocomplete: "off", autocapitalize: "none", spellcheck: "false" });
  const f = field({ id: "sg-proxy", label: "پراکسی (اختیاری)", input,
    help: "اگر اینستاگرام روی این کامپیوتر بدون VPN باز نمی‌شود، آدرس پراکسی را این‌جا بده. خالی بماند یعنی از اینترنت خود سیستم استفاده شود." });
  const save = (e, v = input.value.trim()) => {
    e.preventDefault();
    if (v && !PROXY.test(v)) return f.setError("آدرس باید شبیه \u2066socks5://127.0.0.1:10808\u2069 یا \u2066http://host:8080\u2069 باشد."), input.focus();
    f.setError(""); pref("proxy", v || null);
    toast(v ? "پراکسی ذخیره شد؛ کارهای بعدی از آن می‌روند." : "پراکسی برداشته شد؛ کارها از اینترنت خود سیستم می‌روند.", { tone: "ok" });
  };
  return h("form", { class: "sg-stack", novalidate: true, onsubmit: save }, f,
    h("div", { class: "sg-acts" }, button({ label: "ذخیرهٔ پراکسی", kind: "primary", type: "submit" })));
}

// «تقسیم کار» (ig_share.py): this copy is system k of n. Every candidate of «پردازش» and every page belongs to one system by a
// fixed rule all copies compute alike, so copies that agree on n never read the same person twice. Kept per computer.
function splitView(again) {
  const box = h("div", { class: "sg-stack" }, skeleton("line", 4)), fail = () => mount(box, failed("تنظیمِ تقسیم کار خوانده نشد", again));
  api("/api/prefs").then((r) => (r.ok ? mount(box, splitForm(r.data)) : fail()), fail);
  return box;
}

function splitForm(p) {
  const num = (name, value) => h("input", { class: "input num", type: "text", inputmode: "numeric", dir: "ltr", name, autocomplete: "off", value: faNum(value) });
  const idx = num("share_index", p.share_index || 1), cnt = num("share_count", p.share_count || 1);
  const fi = field({ id: "sg-share-i", label: "شمارهٔ این سیستم", input: idx, help: "در هر سیستم یک عددِ دیگر: ۱، ۲، ۳ …" });
  const fc = field({ id: "sg-share-n", label: "تعداد همهٔ سیستم‌ها", input: cnt, help: "در همهٔ سیستم‌ها همین عدد. ۱ یعنی تقسیمی در کار نیست." });
  const now = h("p", { class: "sg-muted", "aria-live": "polite" });
  const say = (k, n) => (now.textContent = n > 1 ? `الان: سیستمِ ${faNum(k)} از ${faNum(n)} — از هر ${faNum(n)} نامزد و پیج، حدود یکی مالِ این سیستم است.`
    : "الان: تقسیمی در کار نیست؛ همهٔ کارها مالِ همین سیستم است.");
  say(p.share_index || 1, p.share_count || 1);
  const save = button({ label: "ذخیرهٔ تقسیم کار", kind: "primary", type: "submit" });
  async function submit(e) {
    e.preventDefault();
    const k = toInt(idx.value), n = toInt(cnt.value);
    fi.setError(""); fc.setError("");
    if (!(n >= 1 && n <= 50)) { fc.setError("عددی از ۱ تا ۵۰."); return cnt.focus(); }
    if (!(k >= 1 && k <= n)) { fi.setError(`عددی از ۱ تا ${faNum(n)}.`); return idx.focus(); }
    setBusy(save, true);
    const r = await api("/api/prefs", { values: { share_index: k, share_count: n } }).catch(() => null);
    setBusy(save, false);
    if (r?.ok) { say(k, n); pokePolling(); toast(n > 1 ? `این سیستم: ${faNum(k)} از ${faNum(n)}` : "تقسیم کار خاموش شد", { tone: "ok" }); }
    else if (r?.status === 422) (r.data?.fields || []).includes("share_count") ? fc.setError("عددی از ۱ تا ۵۰.") : fi.setError(`عددی از ۱ تا ${faNum(n)}.`);
    else toast("ذخیره نشد؛ برنامه جواب نداد.", { tone: "danger" });
  }
  const steps = ["در همهٔ سیستم‌ها «تعداد همهٔ سیستم‌ها» یکی باشد و «شمارهٔ این سیستم» در هر کدام فرق کند.",
    "JSONِ پیج (مثلاً همان پیجی که فالوورهایش خوانده شده) را در سیستمِ اصلی «دریافت» کن و در بقیه «آپلود»؛ بعد در «پردازش» امتیازدهی و «شروع خواندن». هر سیستم فقط سهمِ خودش را می‌خواند و کسی که پروفایلش آمده دوباره خوانده نمی‌شود.",
    "هر چند وقت JSONِ همان پیج را از هر سیستم «دریافت» کن و در سیستمِ اصلی «آپلود»؛ پروفایل‌های خوانده‌شدهٔ همه یک‌جا جمع می‌شود.",
    "خواندنِ کاملِ فهرستِ فالوورهای یک پیج فقط در یک سیستم انجام شود (جای فهرست مالِ همان حساب است)؛ استخراج کامل، رصد و فهرستِ پیجی که سهمِ سیستمِ دیگری است، پیش از شروع می‌پرسد."];
  return h("form", { class: "sg-stack", novalidate: true, onsubmit: submit },
    h("p", { class: "sg-intro", text: "اگر این برنامه روی چند کامپیوتر کپی شده، کار را بینشان تقسیم کن تا هیچ نامزد یا پیجی دو بار خوانده نشود. سیستم‌ها به هم وصل نمی‌شوند؛ همه از یک قاعدهٔ ثابت می‌فهمند هر نفر سهمِ کیست." }),
    h("div", { class: "sg-grid" }, fi, fc), now,
    h("div", { class: "sg-acts" }, save),
    h("fieldset", { class: "sg-set" }, h("legend", { class: "sg-h3", text: "روشِ کار" }), h("ol", { class: "pj-steps" }, steps.map((t) => h("li", { text: t })))),
    h("p", { class: "sg-muted", text: "اگر تعداد سیستم‌ها را عوض کردی، در همهٔ سیستم‌ها با هم عوض کن؛ اگر سیستمی کنار رفت، JSONِ بقیه را آپلود کن و تعداد را یکی کم کن تا سهمِ او هم پخش شود." }));
}

// His rule: Chromium works without a window by default; a switch shows it when he wants to watch or step in.
function browserView() {
  const on = !!state.status?.prefs?.show_browser;
  const sw = h("button", { type: "button", role: "switch", class: "sg-switch", "aria-checked": String(on), "aria-labelledby": "sg-br-l",
    onclick: async () => {
      const next = sw.getAttribute("aria-checked") !== "true";
      sw.setAttribute("aria-checked", String(next));
      const r = await api("/api/prefs", { values: { show_browser: next } }).catch(() => null);
      if (!r?.ok) { sw.setAttribute("aria-checked", String(!next)); return toast("ذخیره نشد؛ برنامه جواب نداد.", { tone: "danger" }); }
      toast(next ? "از کار بعدی پنجرهٔ Chromium دیده می‌شود." : "از کار بعدی Chromium بدون پنجره کار می‌کند.", { tone: "ok" });
      pokePolling();
    } }, h("span", { class: "sg-knob" }));
  return h("div", { class: "sg-stack" },
    h("div", { class: "sg-card sg-switchrow" }, h("span", { class: "sg-card-ic" }, icon("window")),
      h("div", { class: "sg-grow" }, h("p", { id: "sg-br-l", class: "strong", text: "نمایش پنجرهٔ Chromium هنگام کار" }),
        h("p", { class: "sg-muted", text: "خاموش (پیش‌فرض): همهٔ کارها پشت صحنه انجام می‌شوند و پنجره‌ای باز نمی‌شود." })), sw),
    h("p", { class: "sg-intro", text: "اگر اینستاگرام هنگام ورود کار دستی خواست (تأیید هویت یا پازل)، این را روشن کن و دوباره وارد شو تا پنجره را ببینی. تغییر از کار بعدی اعمال می‌شود." }));
}

function lookView() {
  const t = pref("theme");
  return h("div", { class: "sg-stack sg-look" }, h("p", { class: "sg-intro", text: "«همانند سیستم» با روشن یا تیره شدنِ ویندوز خودش عوض می‌شود." }),
    segmented({ label: "ظاهر", value: t === "light" || t === "dark" ? t : "system", onChange: (v) => pref("theme", v === "system" ? null : v),
      options: [{ value: "system", label: "همانند سیستم" }, { value: "light", label: "روشن" }, { value: "dark", label: "تیره" }] }));
}

function filesView() {
  const total = h("div", { class: "sg-big" }, skeleton("line")), miss = () => mount(total, h("span", { class: "sg-muted", text: "حجم خوانده نشد؛ برنامه جواب نداد." }));
  getFiles(state.status?.session?.username || "_").then((r) => (r.ok && Number.isFinite(r.data?.all_bytes) ? mount(total, bdi(bytes(r.data.all_bytes))) : miss()), miss);
  return h("div", { class: "sg-stack" }, h("div", { class: "sg-card" }, h("span", { class: "sg-card-ic" }, icon("folder")),
    h("div", { class: "sg-grow" }, h("p", { class: "sg-muted", text: "حجم همهٔ فایل‌های دانلودشده" }), total)),
    h("p", {}, "عکس‌ها و ویدیوهای دانلودشده در پوشهٔ ", ltr("data/files"), " کنار برنامه ذخیره می‌شوند."));
}

// «ورود به آباگرام»: who is in (his AbaOne account), what he may do, until when, and «خروج».
function meView() {
  const me = state.me;
  if (!me || me.username === "local") return empty({ icon: "key", title: "ورود به آباگرام خاموش است", text: "این نسخه بدون ورود کار می‌کند." });
  const out = button({ label: "خروج از آباگرام", icon: "login", kind: "danger",
    onClick: async (e) => { setBusy(e.currentTarget, true); await authLogout().catch(() => null); location.reload(); } });
  return h("div", { class: "sg-stack" },
    h("div", { class: "sg-card" }, h("span", { class: "sg-card-ic" }, icon("key")),
      h("div", { class: "sg-grow" }, h("p", { class: "strong" }, ltr(me.username)),
        h("p", { class: "sg-muted" }, `${ROLE_FA[me.role] || me.role}${me.admin ? "، مدیر" : ""} — ${ROLE_HINT[me.role] || ""}`))),
    me.until ? h("p", { class: "sg-muted" }, "این ورود تا ", bdi(faDateTime(me.until)), " می‌ماند؛ بعد دوباره رمز خواسته می‌شود.") : null,
    h("div", { class: "sg-acts" }, out));
}

// «کاربران» (the admin only): the people who may come in with their AbaOne account, and what each may do.
function usersView(again) {
  const box = h("div", { class: "sg-stack" }, skeleton("line", 4));
  const fail = () => mount(box, failed("فهرستِ کاربران خوانده نشد", again));
  const load = () => getUsers().then((r) => (r.ok ? mount(box, usersBody(r.data, load)) : fail()), fail);
  load();
  return box;
}

const roleOptions = () => [{ value: "json", label: ROLE_FA.json }, { value: "full", label: ROLE_FA.full }];

function userRow(u, reload) {
  const seg = segmented({ label: `دسترسیِ ${u.username}`, value: u.role, options: roleOptions(), onChange: async (v) => {
    const r = await saveUser(u.username, v).catch(() => null);
    toast(r?.ok ? `دسترسیِ ${u.username}: ${ROLE_FA[v]}` : "ذخیره نشد؛ برنامه جواب نداد.", { tone: r?.ok ? "ok" : "danger" });
    if (!r?.ok) reload();
  } });
  const drop = button({ label: "برداشتن", icon: "trash", kind: "danger", size: "sm", onClick: async () => {
    if (!(await confirm({ danger: true, title: `${u.username} برداشته شود؟`, cta: "برداشتن",
      text: "دیگر نمی‌تواند وارد آباگرام شود و اگر همین حالا وارد است، بیرون می‌افتد." }))) return;
    const r = await removeUser(u.username).catch(() => null);
    toast(r?.ok ? `${u.username} برداشته شد` : "برداشته نشد؛ دوباره امتحان کن.", { tone: r?.ok ? "ok" : "danger" });
    reload();
  } });
  return h("div", { class: "sg-user" }, h("span", { class: "sg-card-ic" }, icon("user")),
    h("div", { class: "sg-grow" }, h("p", { class: "strong" }, ltr(u.username)),
      h("p", { class: "sg-muted" }, u.last_login ? ["آخرین ورود ", bdi(faDateTime(u.last_login))] : "هنوز وارد نشده")),
    h("div", { class: "sg-user-acts" }, seg, drop));
}

function usersBody(data, reload) {
  const name = h("input", { class: "input", type: "text", dir: "ltr", autocomplete: "off", autocapitalize: "none", spellcheck: "false" });
  const f = field({ id: "sg-user-name", label: "نام کاربریِ آبا وان", input: name, help: "همان نامی که با آن در آبا وان وارد می‌شود." });
  let role = "json";
  const hint = h("p", { class: "sg-muted", text: ROLE_HINT[role] });
  const seg = segmented({ label: "دسترسی", value: role, options: roleOptions(), onChange: (v) => { role = v; hint.textContent = ROLE_HINT[v]; } });
  const add = button({ label: "افزودن", icon: "plus", kind: "primary", type: "submit" });
  async function submit(e) {
    e.preventDefault();
    const v = name.value.trim();
    if (!v) { f.setError("نام کاربری را بنویس."); name.focus(); return; }
    f.setError("");
    setBusy(add, true);
    const r = await saveUser(v, role).catch(() => null);
    setBusy(add, false);
    if (r?.ok) { toast(`${v} اضافه شد (${ROLE_FA[role]})`, { tone: "ok" }); reload(); }
    else if (r?.status === 422) { f.setError("این نام درست نیست: فاصله و نشانه‌هایی مثل / یا \" نباید داشته باشد."); name.focus(); }
    else toast("ذخیره نشد؛ برنامه جواب نداد.", { tone: "danger" });
  }
  const people = data.items || [];
  return h("div", { class: "sg-stack" },
    h("p", { class: "sg-intro", text: "فقط این افراد و مدیر با حسابِ آبا وانشان وارد آباگرام می‌شوند. «فقط JSON» پیج‌ها را می‌بیند و JSONشان را دانلود و آپلود می‌کند، ولی به اینستاگرام، حساب‌ها و صف دست نمی‌زند." }),
    people.length ? h("div", { class: "sg-users" }, people.map((u) => userRow(u, reload)))
      : empty({ icon: "users", title: "هنوز کسی اضافه نشده", text: "همکارت را با نام کاربریِ آبا وانش از فرمِ زیر اضافه کن." }),
    h("form", { class: "sg-set sg-stack", novalidate: true, onsubmit: submit, "aria-label": "افزودنِ کاربر" },
      h("h3", { class: "sg-h3", text: "افزودنِ کاربر" }), f, h("div", { class: "sg-roles" }, seg, hint), h("div", { class: "sg-acts" }, add)),
    h("p", { class: "sg-muted" }, "مدیر: کاربرِ شمارهٔ ", (data.admins || []).map((id, i) => [i ? "، " : "", bdi(String(id).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]))]),
      " در آبا وان؛ عوض کردنش با متغیرِ ", ltr("IGS_ADMINS"), " روی سرور است."));
}

const VIEWS = { session: sessionView, limits: limitsView, usage: usageView, browser: browserView, connection: connectionView, split: splitView, vpn: vpnView, look: lookView, files: filesView,
  me: meView, users: usersView };
