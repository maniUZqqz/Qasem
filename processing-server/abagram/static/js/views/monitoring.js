// «مانیتورینگ»: the dashboard of the whole engine — what runs now, the queue, this hour's usage against the caps, the
// account's health, and a connection test with a proxy for this one account. Read-only except the proxy field and the two
// buttons (test, cancel). Server: /api/health, /api/health/test, /api/prefs, and the status poll. One account by design.
import { h, icon, ltr, uid, mount } from "../core/dom.js";
import { getHealth, testConnection, setPrefs, cancelJob, getAccounts, addAccount, accountAct } from "../core/api.js";
import { faNum, faTime, ago } from "../core/format.js";
import { state, subscribe, pokePolling, pref } from "../core/store.js";
import { button, toast, spinner, avatar, iconButton } from "../core/ui.js";
import { confirm } from "../core/overlay.js";
import { navigate } from "../core/router.js";
import { JOB_TITLE, runningFor } from "../core/jobs.js";
import { taskPanel } from "./pagejobs.js";
import { enter } from "../core/motion.js";

// ---- his Instagram accounts: one active at a time; limits and the pause after «صبر کن» stay shared by all ----
function accountsCard() {
  const id = uid("mn-acc");
  const list = h("ul", { class: "mn-acc-list" });
  const input = h("input", { id, class: "input mn-acc-in", type: "text", dir: "ltr", autocomplete: "off", spellcheck: "false",
    autocapitalize: "none", placeholder: "یوزرنیم حساب تازه", enterkeyhint: "go" });
  const err = h("p", { class: "mn-err", role: "alert", hidden: true });
  const add = button({ label: "افزودن حساب", icon: "plus", kind: "primary", onClick: onAdd });
  let data = null, dead = false;

  async function load() {
    const r = await getAccounts().catch(() => null);
    if (dead) return;
    if (r?.ok) { data = r.data; draw(); }
  }
  const busy = () => !!state.status?.busy;

  async function onAdd() {
    err.hidden = true;
    const u = input.value.trim().replace(/^@/, "").toLowerCase();
    if (!/^[a-z0-9._]{1,30}$/.test(u)) { err.textContent = "یوزرنیم را درست بنویس (حروف انگلیسی، عدد، نقطه و _)."; err.hidden = false; input.focus(); return; }
    add.disabled = true;
    const r = await addAccount(u).catch(() => null);
    add.disabled = false;
    if (r?.ok) {
      toast(`حساب @${u} اضافه شد؛ وارد شو (حساب فعال همان قبلی می‌ماند)`, { tone: "ok" });
      pokePolling();
      return logIn(u);
    }
    err.textContent = r?.status === 409 ? (r.data?.detail === "busy" ? "تا پایان کار جاری نمی‌شود حساب را عوض کرد." : "این حساب قبلاً اضافه شده.") : "اضافه نشد.";
    err.hidden = false;
  }

  // the login page opens for THIS account, its name in place: only the password is left to type; the active account is not touched
  function logIn(u) {
    pref("login.prefill", u);
    pref("login.account", u);
    navigate("/login");
  }

  async function onSwitch(a) {
    const watching = data?.watching || [];
    if (watching.length && !(await confirm({ title: `به حساب @${a.username} بروم؟`, cta: "جابه‌جا شو",
      text: "درخواست‌های فالویی که در انتظار قبول‌اند با حساب قبلی فرستاده شده‌اند؛ با حساب دیگر وضعیتشان درست دیده نمی‌شود." }))) return;
    const r = await accountAct(a.username, "switch").catch(() => null);
    if (r?.ok) { toast(`حساب فعال: @${a.username}`, { tone: "ok" }); pokePolling(); if (!a.logged_in) { pref("login.prefill", a.username); navigate("/login"); } }
    else toast(r?.status === 409 ? "تا پایان کار جاری نمی‌شود حساب را عوض کرد." : "انجام نشد.", { tone: "danger" });
    load();
  }

  async function onRemove(a) {
    if (!(await confirm({ title: `حساب @${a.username} حذف شود؟`, cta: "حذف حساب", danger: true,
      text: "نشست ذخیره‌شدهٔ این حساب پاک می‌شود و برای استفادهٔ دوباره باید دوباره واردش شوی. داده‌های درآمده سر جایشان می‌مانند." }))) return;
    const r = await accountAct(a.username, "remove").catch(() => null);
    if (r?.ok) toast(`@${a.username} حذف شد`); else toast("انجام نشد.", { tone: "danger" });
    load();
  }

  function row(a) {
    const lock = busy() ? "تا پایان کار جاری صبر کن" : null;
    return h("li", { class: ["mn-acc", a.active && "is-active"] },
      avatar({ u: a.username, src: null, size: 40, zoom: false }),
      h("span", { class: "mn-acc-who" },
        h("b", { class: "mn-acc-name" }, ltr(a.username)),
        h("span", { class: ["mn-acc-state", a.logged_in ? "on" : "off"] }, h("i", { "aria-hidden": "true" }),
          a.active ? (a.logged_in ? "فعال؛ کارها با این حساب انجام می‌شود" : "فعال، هنوز وارد نشده") : (a.logged_in ? "وارد شده، آمادهٔ جابه‌جایی" : "هنوز وارد نشده"))),
      a.active ? (a.logged_in ? null : button({ label: "ورود", size: "sm", kind: "primary", onClick: () => { pref("login.prefill", a.username); navigate("/login"); } }))
        : [a.logged_in ? button({ label: "فعال کردن", size: "sm", disabled: !!lock, title: lock, onClick: () => onSwitch(a) })
            : button({ label: "ورود", size: "sm", kind: "primary", onClick: () => logIn(a.username) }),
          iconButton({ icon: "trash", label: `حذف حساب ${a.username}`, size: "sm", onClick: () => onRemove(a) })]);
  }

  function draw() {
    const items = data?.items || [];
    mount(list, items.length ? items.map(row) : h("li", { class: "mn-note", text: "هنوز حسابی وارد نشده؛ یوزرنیم را پایین بنویس و وارد شو." }));
  }

  const form = h("form", { class: "mn-acc-add", novalidate: true, onsubmit: (e) => { e.preventDefault(); onAdd(); } },
    h("label", { class: "mn-acc-field", for: id }, icon("at", { size: "sm" }), input), add);
  const el = h("section", { class: "mn-card mn-accs" },
    h("header", { class: "mn-card-head" }, icon("users", { size: "sm" }), h("h2", { text: "حساب‌های اینستاگرام" })),
    h("p", { class: "mn-note", text: "بین حساب‌های خودت جابه‌جا شو. فقط یک حساب در هر زمان فعال است و کارها همه با همان انجام می‌شود؛ سقف‌ها و «صبر کن» برای همهٔ حساب‌ها مشترک است، پس جابه‌جا شدن ظرفیت اضافه نمی‌دهد." }),
    list, form, err);
  const offs = [subscribe("job-end", load), subscribe("status", () => data && draw())];
  load();
  return { el, destroy: () => { dead = true; offs.forEach((o) => o()); } };
}

// ---- connection + proxy: Instagram is filtered in Iran, so the browser needs a working line or proxy ----
function connCard() {
  const id = uid("mn-proxy");
  const input = h("input", { id, class: "input mn-proxy-in", type: "text", dir: "ltr", autocomplete: "off", spellcheck: "false",
    placeholder: "socks5://127.0.0.1:1080", enterkeyhint: "done" });
  const save = button({ label: "ذخیره", size: "sm", onClick: onSave });
  const test = button({ label: "تست اتصال به اینستاگرام", icon: "globe", kind: "primary", onClick: onTest });
  const result = h("p", { class: "mn-conn-result", role: "status", hidden: true });
  const err = h("p", { class: "mn-err", role: "alert", hidden: true });
  let lastProxy = null;

  function fillProxy() {
    const p = state.status?.prefs?.proxy ?? "";
    if (p === lastProxy) return;
    lastProxy = p;
    if (document.activeElement !== input) input.value = p;
  }
  async function onSave() {
    err.hidden = true;
    save.disabled = true;
    const r = await setPrefs({ proxy: input.value.trim() }).catch(() => null);
    save.disabled = false;
    if (r?.ok) { lastProxy = input.value.trim(); toast("پراکسی ذخیره شد", { tone: "ok" }); pokePolling(); }
    else { err.textContent = "پراکسی معتبر نیست. نمونه: socks5://127.0.0.1:1080 یا http://host:port"; err.hidden = false; }
  }
  async function onTest() {
    result.hidden = false;
    result.className = "mn-conn-result is-wait";
    result.replaceChildren(spinner(16), h("span", { text: "در حال تست…" }));
    const r = await testConnection(input.value.trim() || "").catch(() => null);
    const d = r?.ok ? r.data : null;
    const good = d?.ok;
    result.className = `mn-conn-result ${good ? "is-ok" : "is-bad"}`;
    result.replaceChildren(icon(good ? "circle-check" : "circle-x", { size: "sm" }),
      h("span", {}, good
        ? `اینستاگرام در دسترس است (${d.via === "proxy" ? "از راه پراکسی" : "اتصال مستقیم"}، ${faNum(d.ms)} میلی‌ثانیه، کد ${faNum(d.status)})`
        : d ? `اینستاگرام در دسترس نیست (${d.via === "proxy" ? "با پراکسی" : "اتصال مستقیم"}${d.error ? "، " + d.error : ""}). فیلترشکن یا پراکسی را روشن کن.`
          : "تست انجام نشد."));
  }

  const el = h("section", { class: "mn-card mn-conn" },
    h("header", { class: "mn-card-head" }, icon("globe", { size: "sm" }), h("h2", { text: "اتصال به اینستاگرام" })),
    h("p", { class: "mn-note", text: "اینستاگرام در ایران فیلتر است. یک پراکسی بده تا برنامه حتی وقتی فیلترشکن سیستم خاموش است از آن وصل شود؛ خالی بگذاری، از اتصال مستقیم سیستم استفاده می‌کند." }),
    h("div", { class: "mn-proxy-row" }, h("label", { class: "mn-proxy-field", for: id }, icon("link", { size: "sm" }), input), save),
    err,
    h("div", { class: "mn-conn-actions" }, test),
    result);
  return { el, sync: fillProxy };
}

// ---- what runs right now: the job, its step, and the countdown to its next request (cancel from here) ----
function liveCard() {
  const body = h("div", { class: "mn-live-body" });
  const el = h("section", { class: "mn-card mn-live" },
    h("header", { class: "mn-card-head" }, icon("activity", { size: "sm" }), h("h2", { text: "همین حالا" })), body);
  let key = "";
  function draw() {
    const s = state.status;
    const busy = !!s?.busy;
    const last = state.log.length ? state.log[state.log.length - 1].msg : "";
    const k = busy ? `${s.mode}|${s.username}|${s.state}|${last}` : (s?.budget?.cooldown ? "cool" : `idle${s?.queue?.signed_in === false}${(s?.queue?.tasks || []).length}`);
    if (k === key) return;
    key = k;
    if (!busy) {
      const cool = s?.budget?.cooldown;
      const q = s?.queue;
      body.replaceChildren(h("div", { class: "mn-idle" }, icon(cool ? "hourglass" : "check", { size: "md" }),
        h("p", { text: cool ? `در مکث بعد از «صبر کن» تا ساعت ${faTime(cool.until)}` : (q && q.signed_in === false && (q.tasks || []).length ? "وارد اینستاگرام نشده‌ای؛ صف منتظر ورود است." : "هیچ کاری در حال اجرا نیست؛ همه‌چیز آرام است.") })));
      return;
    }
    const wait = { need_code: "منتظر کد تأیید تو", need_manual: "منتظر یک کار دستی تو" }[s.state];
    mount(body,
      h("div", { class: "mn-live-top" },
        wait ? icon("key", { size: "md", cls: "mn-live-ic" }) : spinner(22),
        h("div", { class: "mn-live-what" },
          h("b", { text: JOB_TITLE[s.mode] || "در حال خواندن" }),
          s.username ? h("span", { class: "mn-live-user" }, ltr(`@${s.username}`)) : null),
        button({ label: "لغو", icon: "x", size: "sm", kind: "danger", onClick: () => { cancelJob().finally(pokePolling); } })),
      wait ? h("p", { class: "mn-live-wait", text: wait }) : null,
      last ? h("p", { class: "mn-live-log" }, ...lineParts(last)) : null);
  }
  const offs = [subscribe("status", draw), subscribe("log", draw)];
  draw();
  return { el, destroy: () => offs.forEach((o) => o()) };
}

function lineParts(msg) {
  return String(msg || "").split(/(⁦[^⁩]*⁩)/).filter(Boolean).map((p) => (p.startsWith("⁦") ? ltr(p.slice(1, -1)) : p));
}

// ---- this hour / today against the caps he set, so he sees how close to a limit he is ----
const USE = [["page", "صفحه‌های باز‌شده", "pages"], ["scroll", "ورق‌زدن فهرست‌ها", "scrolls"], ["harvest", "خواندن کامل فهرست", "harvests"]];

function meter(label, used, cap) {
  const r = cap > 0 ? Math.min(1, used / cap) : 0;
  const tone = r >= 1 ? "bad" : r >= 0.8 ? "warn" : "ok";
  return h("div", { class: ["mn-meter", `is-${tone}`] },
    h("div", { class: "mn-meter-top" }, h("span", { class: "mn-meter-label", text: label }),
      h("b", { class: "num" }, `${faNum(used)} از ${faNum(cap)}`)),
    h("span", { class: "mn-meter-bar", "aria-hidden": "true" }, h("i", { style: `--p:${r}` })));
}

function usageCard() {
  const grid = h("div", { class: "mn-use-grid" });
  const el = h("section", { class: "mn-card mn-use" },
    h("header", { class: "mn-card-head" }, icon("gauge", { size: "sm" }), h("h2", { text: "مصرف نسبت به سقف" }),
      h("a", { class: "mn-head-link", href: "#/settings/limits", text: "تغییر سقف‌ها" })),
    grid);
  let key = "";
  function draw() {
    const b = state.status?.budget;
    if (!b) return;
    const k = JSON.stringify([b.used, b.limits]);
    if (k === key) return;
    key = k;
    grid.replaceChildren(...USE.map(([kind, label, pre]) => h("div", { class: "mn-use-col" },
      h("h3", { class: "mn-use-h", text: label }),
      meter("این ساعت", b.used[kind]?.hour ?? 0, b.limits[`${pre}_hour`] ?? 0),
      meter("امروز", b.used[kind]?.day ?? 0, b.limits[`${pre}_day`] ?? 0))));
  }
  const off = subscribe("status", draw);
  draw();
  return { el, destroy: off };
}

// ---- account health: a traffic-light, counts of concerns, and the last incidents ----
const LIGHT = { ok: { text: "سالم", tone: "ok", ic: "circle-check" }, warn: { text: "مراقب باش", tone: "warn", ic: "alert" },
  bad: { text: "پرخطر", tone: "bad", ic: "shield" } };
const INCIDENT = { rate_limit: "«صبر کن» اینستاگرام", cooldown: "مکث بعد از «صبر کن»", network: "اینستاگرام در دسترس نبود",
  session_invalid: "نشست باطل شد", challenge: "تأیید هویت خواسته شد", automated: "رفتار خودکار دیده شد",
  not_found: "صفحه پیدا نشد", unreadable: "جواب روشن نبود", ok: "خواندن موفق" };

function healthCard() {
  const body = h("div", { class: "mn-health-body" }, spinner(20));
  const el = h("section", { class: "mn-card mn-health" },
    h("header", { class: "mn-card-head" }, icon("shield", { size: "sm" }), h("h2", { text: "سلامت حساب" })), body);
  let timer = 0, dead = false;

  function draw(d) {
    const light = LIGHT[d.light] || LIGHT.ok;
    const me = state.status?.session, sessionOn = !!me?.username && !me.lost_at;   // lost_at: Instagram threw the account out
    mount(body,
      h("div", { class: ["mn-light", `is-${light.tone}`] }, icon(light.ic, { size: "md" }),
        h("div", {}, h("b", { text: light.text }),
          h("span", { class: "mn-light-sub", text: sessionOn ? `نشست فعال: @${me.username}`
            : me?.lost_at ? `اینستاگرام @${me.username} را بیرون کرد؛ دوباره وارد شو` : "وارد نشده‌ای" }))),
      h("ul", { class: "mn-stats" },
        h("li", {}, h("b", { class: "num", text: faNum(d.hour_waits) }), h("span", { text: "«صبر کن» این ساعت" })),
        h("li", {}, h("b", { class: "num", text: faNum(d.day_concerns) }), h("span", { text: "هشدار امروز" })),
        h("li", {}, h("b", { class: "num", text: faNum(d.week_concerns) }), h("span", { text: "هشدار این هفته" })),
        h("li", {}, h("b", { class: "num", text: faNum(d.day_ok) }), h("span", { text: "خواندن موفق امروز" }))),
      d.recent?.length ? h("div", { class: "mn-events" },
        h("h3", { class: "mn-events-h", text: "رویدادهای اخیر" }),
        h("ul", { class: "mn-events-list" }, d.recent.map((e) => h("li", { class: ["mn-event", e.concern ? "is-bad" : "is-ok"] },
          icon(e.concern ? "alert" : "check", { size: "sm" }),
          h("span", { class: "mn-event-what" }, INCIDENT[e.kind] || e.kind, e.username ? h("span", { class: "mn-event-user" }, " ", ltr(`@${e.username}`)) : null),
          h("time", { class: "mn-event-when", text: ago(e.at_iso) }))))) : null);
  }
  async function load() {
    const r = await getHealth().catch(() => null);
    if (dead) return;
    if (r?.ok) draw(r.data);
    else body.replaceChildren(h("p", { class: "mn-note", text: "سلامت حساب باز نشد." }));
  }
  const off = subscribe("job-end", load);
  load();
  timer = setInterval(load, 30000);
  return { el, destroy: () => { dead = true; off(); clearInterval(timer); } };
}

export function render() {
  const accs = accountsCard();
  const conn = connCard();
  const live = liveCard();
  const queue = taskPanel(() => null);     // every page's queue task (null name = all)
  const usage = usageCard();
  const health = healthCard();
  const queueWrap = h("section", { class: "mn-card mn-queue" },
    h("header", { class: "mn-card-head" }, icon("list", { size: "sm" }), h("h2", { text: "صف کارها" })),
    queue.el);
  const emptyNote = h("p", { class: "mn-note mn-queue-empty", text: "صفی در کار نیست." });
  queueWrap.append(emptyNote);

  const el = h("div", { class: "mn" },
    h("header", { class: "mn-head" }, h("h1", { class: "mn-title", text: "مانیتورینگ" }),
      h("p", { class: "mn-lede", text: "نگاهی یک‌جا به کل موتور: چه چیزی در حال اجراست، صف، مصرف، سلامت حساب و اتصال." })),
    live.el, queueWrap, usage.el, health.el, accs.el, conn.el);

  const syncQueueEmpty = () => { const q = state.status?.queue; emptyNote.hidden = !!(q && (q.tasks?.length || q.recent?.length)); };
  const offs = [subscribe("status", () => { conn.sync(); syncQueueEmpty(); })];
  conn.sync();
  syncQueueEmpty();
  enter(el, "fade");
  return {
    el,
    update() { conn.sync(); },
    destroy() { offs.forEach((o) => o()); accs.destroy(); live.destroy(); queue.destroy(); usage.destroy(); health.destroy(); },
  };
}
