// The end of a reading job: what was saved (with a way to open it), or what went wrong and what to do next.
// Used by activity.js (the finished run) and login.js. Builds DOM only through h() (Instagram text is never markup).
import { h, icon, ltr, bdi, uid } from "../core/dom.js";
import { avatarUrl, cancelJob, clearCooldown, shotUrl } from "../core/api.js";
import { pokePolling, state as storeState } from "../core/store.js";
import { avatar, button, empty, setBusy, toast } from "../core/ui.js";
import { confirm } from "../core/overlay.js";
import { KIND, startJob } from "../core/jobs.js";
import { bytes, unit } from "../core/format.js";

const FIN = new Set(["success", "failed", "cancelled"]);
const OFFLINE = "سرور محلی در دسترس نیست؛ برنامه را دوباره اجرا کن.";
const enc = encodeURIComponent;
const n = (v) => (Array.isArray(v) ? v.length : Number(v) || 0);
const U = (v, word) => bdi(unit(n(v), word));          // every number+unit in its own <bdi> (rule 2)
const to = (u, tail = "") => `#/u/${enc(u)}${tail}`;

const WHY = {
  empty: "فهرست خالی بود", private: "حساب خصوصی است", no_link: "اینستاگرام لینک این فهرست را نشان نداد",
  no_reply: "اینستاگرام جواب نداد", refused: "اینستاگرام فهرست را نشان نداد", stalled: "فهرست بیشتر از این باز نشد",
  budget: "سقف ایمنی پر شد", cooldown: "در مکث بعد از «صبر کن» بود",
};
const LISTS = [["followers", "فالوور", "فالوورها", "دیدن فالوورها"], ["following", "فالووینگ", "فالووینگ‌ها", "دیدن فالووینگ‌ها"]];

// Per mode: the sentence that says what was saved, a few facts, and where the result opens.
const SUM = {
  login(r, o, check) {
    o.title = [check ? "نشست معتبر است" : r.reused ? "نشست قبلی هنوز معتبر بود" : "وارد شدی"];
    o.facts.push(["shield", check || r.reused ? "اینستاگرام هنوز این نشست را می‌شناسد."
      : "نشست روی همین کامپیوتر ذخیره شد؛ دفعهٔ بعد پسورد لازم نیست."]);
    if (o.open) o.open.label = "باز کردن پروفایل";
  },
  check(r, o) { SUM.login(r, o, true); },
  profile(r, o) {
    o.title = ["پروفایل خوانده شد"];
    if (r.cached) o.facts.push(["clock", "نسخهٔ ذخیره‌شده نشان داده شد؛ صفحه‌ای از اینستاگرام مصرف نشد."]);
    if (n(r.posts)) o.facts.push(["grid", [U(r.posts, "پست"), " همراه پروفایل ذخیره شد."]]);
  },
  posts(r, o) {
    const saved = r.saved ?? r.read;
    o.title = [U(saved, "پست"), " ذخیره شد", n(r.new) ? [" (", U(r.new, "تازه"), ")"] : null];
    if (r.read != null) o.facts.push(["refresh", ["در این بار ", U(r.read, "پست"), " خوانده شد."]]);
    if (r.total != null) o.facts.push(["grid", [U(saved, "پست"), " از ", U(r.total, "پست"), " این حساب ذخیره شده است."]]);
    if (o.open) o.open.label = "دیدن پست‌ها";
  },
  details(r, o) {
    const codes = Array.isArray(r.codes) ? r.codes : [];
    o.title = ["کامنت‌ها و لایک‌کنندگان ", U(r.codes, "پست"), " خوانده شد"];
    if (codes.length === 1 && o.u) o.open = { label: "دیدن پست", href: to(o.u, `/p/${enc(codes[0])}`) };
  },
  stories(r, o) {
    const none = !n(r.items);
    o.title = none ? ["استوری فعالی نیست"] : [U(r.items, "استوری"), " خوانده شد"];
    if (none) o.facts.push(["clock", "اینستاگرام الان استوری‌ای از این حساب نشان نمی‌دهد."]);
    else if (o.u) o.open = { label: "دیدن استوری", href: to(o.u, "/stories") };
  },
  highlights(r, o) {
    const ids = Array.isArray(r.ids) ? r.ids : [];
    o.title = [U(ids.length || r.found, "هایلایت"), " خوانده شد"];
    if (r.items != null) o.facts.push(["layers", [U(r.items, "آیتم"), " ذخیره شد."]]);
    if (ids.length === 1 && o.u) o.open = { label: "دیدن هایلایت", href: to(o.u, `/hl/${enc(ids[0])}`) };
  },
  follow(r, o) {
    const L = r.lists || {}, parts = [];
    for (const [key, word, label, cta] of LISTS) {
      const x = L[key];
      if (!x) continue;
      parts.push(parts.length ? " و " : null, U(x.kept, word));
      const why = x.limited ? "اینستاگرام خودش فهرست را کوتاه کرد" : WHY[x.reason] || (x.reason ? ltr(x.reason) : null);
      o.facts.push(["users", [`${label}: `, U(x.kept, "نفر"), x.total != null ? [" از ", U(x.total, "نفر")] : null,
        why ? ["؛ ", why] : null], why ? "warn" : null]);
      if (o.u && !o.openSet) { o.open = { label: cta, href: to(o.u, `/${key}`) }; o.openSet = true; }
    }
    o.title = parts.length ? [...parts, " ذخیره شد"] : ["فهرستی ذخیره نشد"];
  },
  download(r, o) {
    const f = r.files || {};
    o.title = n(f.saved) ? [U(f.saved, "فایل"), " دانلود شد، ", bdi(bytes(f.bytes || 0))]
      : [n(f.had) ? "همهٔ فایل‌ها از قبل دانلود شده بود" : "فایلی دانلود نشد"];
    const add = (v, ic, text, tone) => { if (v) o.facts.push([ic, text, tone]); };
    add(n(f.planned), "list", ["برنامهٔ این کار: ", U(f.planned, "فایل")]);
    add(n(f.had), "folder", [U(f.had, "فایل"), " از قبل روی همین کامپیوتر بود."]);
    add(n(f.expired), "clock", [U(f.expired, "فایل"), " لینکش منقضی شده بود؛ دوباره بخوان و بعد دانلود کن."], "warn");
    add(n(f.too_big), "alert", [U(f.too_big, "فایل"), " از سقف حجم هر فایل بزرگ‌تر بود."], "warn");
    add(n(f.failed), "circle-x", [U(f.failed, "فایل"), " دانلود نشد."], "warn");
    add(f.stopped, "gauge", "دانلود پیش از پایان فهرست ایستاد (سقف تعداد یا حجم این کار).", "warn");
    if (r.target === "story" && o.u) o.open = { label: "دیدن استوری", href: to(o.u, "/stories") };
    else if (o.open) o.open.label = r.target === "highlights" ? "دیدن هایلایت‌ها" : "دیدن پست‌ها";
  },
};

function summary(s) {
  const r = s.result || {}, p = r.profile || {};
  const u = p.username || r.username || s.username || "";
  const src = p.has_avatar && u ? avatarUrl(u, p.fetched_at) : r.avatar || null;
  const o = { u, p, src, title: ["انجام شد"], facts: [], open: u ? { label: "دیدن پروفایل", href: to(u) } : null };
  SUM[s.mode]?.(r, o);
  return o;
}

/** The body to send again for the same job, when the status tells enough (else null: pass {body} yourself). */
export function retryBody(s) {
  const last = storeState.lastJob;                       // the exact body of the job started from this page
  if (last && last.kind === s?.mode && (!s.username || (last.body.username || "").toLowerCase() === s.username.toLowerCase())) return last.body;
  const r = s?.result || {}, u = r.profile?.username || s?.username;
  const only = (key, list) => (Array.isArray(list) && list.length ? { [key]: list } : {});
  if (s?.mode === "check") return {};
  const extra = { profile: {}, posts: {}, stories: {}, details: only("codes", r.codes), highlights: only("ids", r.ids),
    follow: only("which", Object.keys(r.lists || {})) }[s?.mode];
  return u && extra ? { username: u, ...extra } : null;   // login needs the password; a download's selection is not in the status
}

// ---- small parts ----
const disc = (tone, ic) => h("span", { class: `oc-disc oc-disc-${tone}`, "aria-hidden": "true" }, icon(ic));
const link = (href, label, ic, kind) => h("a", { class: ["btn", kind], href }, ic ? icon(ic) : null, h("span", { text: label }));
const factList = (facts) => (facts.length ? h("ul", { class: "oc-facts" }, facts.map(([ic, text, tone]) =>
  h("li", { class: ["oc-fact", tone && `oc-fact-${tone}`] }, icon(ic, { size: "sm" }), h("span", {}, text)))) : null);
const who = (o) => (o.u ? h("p", { class: "oc-who" }, ltr(`@${o.u}`),
  o.p.full_name ? h("span", { class: "oc-name", dir: "auto", text: o.p.full_name }) : null) : null);

// ---- actions: the button stays busy while its request runs; the poller then redraws the activity drawer ----
async function run(btn, work) {
  setBusy(btn, true);
  try { await work(); } catch { toast(OFFLINE, { tone: "danger" }); }
  setBusy(btn, false);
}
const ask = (call, ok, bad) => async () => {
  const r = await call();
  toast(r.ok ? ok : bad, { tone: r.ok ? "ok" : "danger" });
  pokePolling();
};
const closeBrowser = (btn) => run(btn, ask(cancelJob, "مرورگر بسته شد", "مرورگر بسته نشد؛ دوباره امتحان کن."));
async function endPause(btn) {
  if (await confirm({ title: "مکث تمام شود؟", cta: "پایان مکث",
    text: "اینستاگرام خودش گفته بود صبر کن. اگر زود دوباره درخواست بفرستی، ممکن است مکث طولانی‌تری بدهد." })) {
    run(btn, ask(clearCooldown, "مکث تمام شد", "مکث تمام نشد؛ دوباره امتحان کن."));
  }
}

function actions(s, ...list) {
  if (s.browser_open) list.push(button({ label: "بستن مرورگر", icon: "window", onClick: (e) => closeBrowser(e.currentTarget) }));
  list = list.filter(Boolean);
  return list.length ? h("div", { class: "oc-acts" }, list) : null;
}

/** What a failure lets the person do: one primary step for the kind, then a retry of the same job. */
function failActions(s, kind, body) {
  const special = {
    budget: () => link("#/settings/limits", "باز کردن محدودیت‌ها", "gauge", "primary"),
    cooldown: () => button({ label: "پایان مکث", icon: "hourglass", kind: "primary", onClick: (e) => endPause(e.currentTarget) }),
    session_invalid: () => link("#/login", "ورود دوباره", "login", "primary"),
  }[kind]?.() || (s.mode === "login" ? link("#/login", "ورود دوباره", "login", "primary") : null);
  const again = body && s.mode !== "login" ? button({ label: "دوباره امتحان کن", icon: "refresh", kind: special ? "secondary" : "primary",
    onClick: (e) => run(e.currentTarget, () => startJob(s.mode, body)) }) : null;
  const u = s.result?.profile?.username;
  const open = u && kind !== "not_found" ? link(to(u), "دیدن پروفایل", "user") : null;
  return actions(s, special, again, open);
}

// The browser window's screenshot: a 160px thumbnail that opens large in the shared viewer (rule 16).
const shot = (src) => h("figure", { class: "oc-shot" }, h("button", { type: "button", class: "oc-shot-btn", "data-zoom": "",
  "data-zoom-src": src, "data-zoom-title": "عکس پنجرهٔ مرورگر", "aria-label": "باز کردن عکس پنجرهٔ مرورگر در اندازهٔ بزرگ" },
h("img", { src, alt: "صفحه‌ای که اینستاگرام در پنجرهٔ مرورگر نشان داد", loading: "lazy", decoding: "async" })),
h("figcaption", { class: "oc-cap", text: "عکس پنجرهٔ مرورگر" }));

function tech(o) {
  const d = o.detail;
  const rows = d && typeof d === "object" ? Object.entries(d).filter(([, v]) => v !== null && v !== undefined && v !== "") : [];
  const text = typeof d === "string" && d ? d : null;
  if (!rows.length && !text && !o.page_text) return null;
  return h("details", { class: "oc-tech" },
    h("summary", {}, icon("braces", { size: "sm" }), h("span", { text: "جزئیات فنی" }), icon("chevron", { size: "sm", cls: "oc-chev" })),
    rows.length ? h("dl", { class: "oc-kv" }, rows.map(([k, v]) =>
      [h("dt", {}, ltr(k)), h("dd", {}, ltr(typeof v === "string" ? v : JSON.stringify(v)))])) : null,
    text ? h("pre", { class: "oc-pre", dir: "ltr", text }) : null,
    o.page_text ? [h("p", { class: "oc-cap", text: "متن صفحه" }), h("pre", { class: "oc-pre", dir: "auto", text: o.page_text })] : null);
}

// ---- the cards ----
function okCard(s) {
  const o = summary(s), id = uid("oc");
  // The person's avatar in the story ring with a check at its corner: the one loud thing on the card.
  const face = o.u || o.src ? h("span", { class: "oc-face" }, avatar({ u: o.u, src: o.src, size: 56, ring: "story" }),
    h("span", { class: "oc-tick", "aria-hidden": "true" }, icon("check", { size: "sm" }))) : disc("ok", "circle-check");
  return h("section", { class: "oc oc-ok", "aria-labelledby": id },
    h("header", { class: "oc-head" }, face, h("div", { class: "oc-head-t" }, h("h3", { class: "oc-title", id }, o.title), who(o))),
    factList(o.facts), actions(s, o.open ? link(o.open.href, o.open.label, null, "primary") : null));
}

function badCard(s, kind, out, body) {
  const K = KIND[kind] || KIND.other, tone = K.tone === "ok" ? "ok" : K.tone === "warn" ? "warn" : "bad", id = uid("oc");
  return h("section", { class: ["oc", `oc-${tone}`], "aria-labelledby": id },
    h("header", { class: "oc-head" }, disc(tone, K.icon),
      h("div", { class: "oc-head-t" }, h("h3", { class: "oc-title", id, text: K.title }),
        K.text ? h("p", { class: "oc-text", text: K.text }) : null)),
    out.note ? h("p", { class: "oc-note", dir: "auto" }, icon("gauge", { size: "sm" }), h("span", { text: out.note })) : null,
    out.ig_message ? h("figure", { class: "oc-quote" }, h("figcaption", { class: "oc-cap", text: "پیام اینستاگرام، متن اصلی" }),
      h("blockquote", { dir: "auto", text: out.ig_message })) : null,
    Number.isFinite(out.shot) ? shot(shotUrl(out.shot)) : null,   // false: no picture could be taken (a crashed page)
    tech(out), failActions(s, kind, body));
}

/** The full card for a finished run (status = /api/status). opts.body: the job body, when the caller knows it. */
export function outcomeCard(status, { body } = {}) {
  const s = status || {};
  if (s.busy || !FIN.has(s.state)) return empty({ icon: "activity", title: "هنوز نتیجه‌ای نیست", text: "وقتی کار تمام شود، نتیجه این‌جا می‌آید." });
  const out = s.outcome || {};
  const kind = out.kind || (s.state === "success" ? "ok" : s.state === "cancelled" ? "cancelled" : "error");
  if (s.state === "success" && kind === "ok") return okCard(s);
  return badCard(s, kind, out, body === undefined ? retryBody(s) : body);
}

/** One line for a successful run: what was saved and a link to it. Null when the run did not succeed. */
export function resultSummary(status) {
  const s = status || {};
  if (s.state !== "success" || (s.outcome?.kind && s.outcome.kind !== "ok")) return null;
  const o = summary(s);
  return h("div", { class: "oc-sum" }, icon("circle-check", { cls: "oc-sum-ic" }),
    h("p", { class: "oc-sum-t" }, o.title),
    o.open ? link(o.open.href, o.open.label, null, "link") : null);
}
