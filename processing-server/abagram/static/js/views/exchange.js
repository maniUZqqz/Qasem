// «تبادلِ JSON» (his order 2026-11-05): a page's whole JSON out — its profile, posts, highlights, its followers / following
// with each person's own saved profile — and such a file back in from another آباگرام (the colleague's copy). Nothing is
// asked of Instagram here. Inside the site it is a page of the shell; for the «فقط JSON» role it is the whole site.
import { h, icon, ltr, bdi, mount } from "../core/dom.js";
import { getExchange, exportUrl, importFile, authLogout, avatarUrl, cleanUsername } from "../core/api.js";
import { faNum, bytes } from "../core/format.js";
import { button, iconButton, avatar, empty, skeleton, pagedList, listState, chip, toast } from "../core/ui.js";
import { enter } from "../core/motion.js";

const ROLE_FA = { full: "همه‌کاره", json: "فقط JSON" };
const LIST_FA = { followers: "فالوورها", following: "فالووینگ‌ها" };
const SECTION_FA = { posts: "پست‌ها", highlights: "هایلایت‌ها", reels: "ریلز", stories: "استوری", details: "کامنت‌ها", similar: "پیج‌های مشابه" };
const isJson = (f) => /\.json$/i.test(f.name) || f.type === "application/json";

/** The download: a plain link (the browser shows its own progress; the server names the file after the page and the time). */
export const downloadLink = (u, { size = "sm", kind = "" } = {}) => h("a", { class: ["btn", size, kind, "xc-dl"], href: exportUrl(u), download: "",
  "aria-label": `دریافت JSONِ ${u}` }, icon("download", { size: "sm" }), h("span", { text: "دریافت JSON" }));

// ---- what an upload changed, in plain sentences (only the parts that are not zero) ----
const PROFILE_FA = { new: "پروفایلِ پیج تازه اضافه شد", updated: "پروفایلِ پیج به‌روز شد", kept: "پروفایلِ پیج همانِ این‌جا ماند (تازه‌تر بود)",
  bad: "پروفایلِ پیج در فایل خراب بود و کنار رفت", none: null };

function report(r) {
  const line = (text, tone) => h("li", { class: ["xc-rep-l", tone && `xc-${tone}`] }, icon(tone === "warn" ? "alert" : "check", { size: "sm" }), h("span", { text }));
  const out = [];
  if (PROFILE_FA[r.profile]) out.push(line(PROFILE_FA[r.profile]));
  for (const [which, x] of Object.entries(r.lists || {})) {
    out.push(x.skipped ? line(`فهرستِ ${LIST_FA[which]} دست نخورد، چون همین حالا در حالِ خواندن است؛ پروفایل‌هایش آمد.`, "warn")
      : line(x.added ? `فهرستِ ${LIST_FA[which]}: ${faNum(x.added)} نفرِ تازه، حالا ${faNum(x.saved)} نفر` : `فهرستِ ${LIST_FA[which]}: نفرِ تازه‌ای نداشت (${faNum(x.saved)} نفر)`));
  }
  const p = r.people || {}, parts = [];
  if (p.new) parts.push(`${faNum(p.new)} تازه`);
  if (p.updated) parts.push(`${faNum(p.updated)} به‌روز`);
  if (p.kept) parts.push(`${faNum(p.kept)} بی‌تغییر (این‌جا تازه‌تر بود)`);
  out.push(line(parts.length ? `پروفایل‌ها: ${parts.join("، ")}` : "پروفایلِ فالووری در فایل نبود"));
  if (r.sections) out.push(line(`${faNum(r.sections)} بخش از پیج (پست، هایلایت …) تازه شد`));
  if (p.bad) out.push(line(`${faNum(p.bad)} مورد نامعتبر کنار گذاشته شد`, "warn"));
  return h("div", { class: "xc-rep" }, h("p", { class: "xc-rep-h" }, "پیجِ ", ltr(`@${r.page}`)), h("ul", { class: "xc-rep-ls" }, out));
}

/** One file on its way: queued → uploading (a bar that fills) → merging on the server → done (what changed) or not. */
function jobRow(file) {
  const fill = h("i", { class: "xc-bar-i" });
  const bar = h("div", { class: "xc-bar", role: "progressbar", "aria-label": `آپلودِ ${file.name}`, "aria-valuemin": "0", "aria-valuemax": "100" }, fill);
  const said = h("span", { class: "xc-job-s", text: "در صف" });
  const body = h("div", { class: "xc-job-b" });
  const el = h("li", { class: "xc-job", "data-s": "wait" },
    h("div", { class: "xc-job-top" }, h("span", { class: "xc-job-ic" }, icon("braces", { size: "sm" })),
      h("span", { class: "xc-job-n" }, ltr(file.name), h("bdi", { class: "xc-job-z", text: bytes(file.size) })), said), bar, body);
  const end = (state, text, kids) => { el.dataset.s = state; said.textContent = text; bar.remove(); mount(body, kids); enter(body, "fade"); };
  return {
    el,
    stage(kind, p = 0) {
      el.dataset.s = kind;
      if (kind === "up") {
        fill.style.transform = `scaleX(${Math.max(0.02, p)})`;
        bar.setAttribute("aria-valuenow", String(Math.round(p * 100)));
        said.textContent = `آپلود ${faNum(Math.round(p * 100))}٪`;
      } else {
        fill.style.transform = "";
        bar.removeAttribute("aria-valuenow");
        said.textContent = "در حالِ یکی کردن با داده‌های این‌جا…";
      }
    },
    done: (rep) => end("ok", "انجام شد", report(rep)),
    fail: (msg) => end("bad", "انجام نشد", h("p", { class: "xc-job-err", role: "alert", text: msg })),
  };
}

function uploader(onDone) {
  const input = h("input", { type: "file", accept: ".json,application/json", multiple: true, hidden: true,
    onchange: () => { take([...input.files]); input.value = ""; } });
  const pick = button({ label: "انتخابِ فایل", icon: "folder", kind: "primary", onClick: () => input.click() });
  const zone = h("div", { class: "xc-drop" }, h("span", { class: "xc-drop-ic" }, icon("upload", { size: "lg" })),
    h("p", { class: "xc-drop-t", text: "فایل‌های JSON را این‌جا رها کن" }), h("p", { class: "xc-drop-or", text: "یا" }), pick, input);
  const jobs = h("ul", { class: "xc-jobs", "aria-label": "فایل‌های آپلودشده" });
  let line = Promise.resolve();    // one file after another: each gets its own clear progress and result

  async function send(file, row) {
    row.stage("up", 0);
    const r = await importFile(file, (p) => row.stage(p >= 1 ? "merge" : "up", p)).catch(() => null);
    if (r?.ok) { row.done(r.data.report); onDone?.(); return; }
    row.fail(r?.data?.message || (r ? `سرور نپذیرفت (کد ${faNum(r.status)}).` : "سرور جواب نداد؛ اتصال را ببین و فایل را دوباره بفرست."));
  }
  function take(files) {
    const good = files.filter(isJson);
    if (files.length > good.length) toast(`${faNum(files.length - good.length)} فایل JSON نبود و کنار رفت.`, { tone: "danger" });
    for (const f of good) {
      const row = jobRow(f);
      jobs.prepend(row.el);
      enter(row.el, "rise");
      line = line.then(() => send(f, row));
    }
  }
  const over = (on) => (e) => { e.preventDefault(); zone.classList.toggle("is-over", on); };
  zone.addEventListener("dragenter", over(true));
  zone.addEventListener("dragover", over(true));
  zone.addEventListener("dragleave", (e) => { if (!zone.contains(e.relatedTarget)) zone.classList.remove("is-over"); });
  zone.addEventListener("drop", (e) => { over(false)(e); take([...(e.dataTransfer?.files || [])]); });

  return h("section", { class: "xc-card", "aria-labelledby": "xc-up-h" },
    h("h2", { class: "xc-h2", id: "xc-up-h" }, icon("upload"), h("span", { text: "آپلودِ JSON" })),
    h("p", { class: "xc-help", text: "فایلی که «دریافت JSON» در یک آباگرامِ دیگر ساخته. هر چه تازه است اضافه می‌شود، هر چه تازه‌تر خوانده شده جایگزین می‌شود و چیزی پاک نمی‌شود." }),
    zone, jobs);
}

// ---- the pages there are, each with its download ----
function pageRow(p) {
  const fl = p.lists.followers, fg = p.lists.following;
  const listChip = (x, word) => chip({ icon: "users", text: `${faNum(x.saved)}${x.total ? ` از ${faNum(x.total)}` : ""} ${word}${x.complete ? "، کامل" : ""}` });
  const facts = [
    fl ? listChip(fl, "فالوور") : null,
    fl?.read ? chip({ icon: "circle-check", text: `${faNum(fl.read)} پروفایلِ خوانده‌شده`, tone: "ok" }) : null,
    fg ? listChip(fg, "فالووینگ") : null,
    ...p.sections.filter((s) => SECTION_FA[s]).slice(0, 2).map((s) => chip({ text: SECTION_FA[s] })),
  ].filter(Boolean);
  return h("div", { class: "xc-row" },
    avatar({ u: p.username, src: p.has_avatar ? avatarUrl(p.username) : null, size: 44, zoom: false }),
    h("div", { class: "xc-row-t" },
      h("p", { class: "xc-row-u" }, ltr(`@${p.username}`), p.full_name ? h("span", { class: "xc-row-n" }, bdi(p.full_name)) : null),
      facts.length ? h("p", { class: "xc-facts" }, facts) : null),
    downloadLink(p.username));
}

function pagesCard() {
  const find = h("input", { class: "input xc-find", type: "search", dir: "ltr", placeholder: "یوزرنیم یا نام", "aria-label": "پیدا کردنِ پیج",
    autocomplete: "off", autocapitalize: "none", spellcheck: "false" });
  const count = h("span", { class: "xc-count num" });
  const other = h("div", { class: "xc-other", hidden: true });     // a saved profile that is not in the list: still downloadable
  const box = h("div", { class: "xc-list" }, skeleton("line", 3));
  let all = [], list = null;

  function filter() {
    const q = find.value.trim().toLowerCase().replace(/^@/, "");
    const items = q ? all.filter((p) => p.username.includes(q) || (p.full_name || "").toLowerCase().includes(q)) : all;
    const exact = cleanUsername(q);
    other.hidden = !exact || all.some((p) => p.username === exact);
    if (!other.hidden) mount(other, h("p", { class: "xc-other-t" }, "پروفایلِ ", ltr(`@${exact}`), " اگر این‌جا خوانده شده باشد:"), downloadLink(exact, { kind: "ghost" }));
    listState("xc-pages").page = 0;
    list?.redraw(items);
    count.textContent = q ? `${faNum(items.length)} از ${faNum(all.length)}` : faNum(all.length);
  }
  async function load() {
    const r = await getExchange().catch(() => null);
    if (!r?.ok) {
      mount(box, empty({ icon: "alert", title: "فهرستِ پیج‌ها خوانده نشد", text: "سرور جواب نداد. کمی بعد دوباره امتحان کن.",
        action: button({ label: "دوباره امتحان کن", icon: "refresh", onClick: load }) }));
      return;
    }
    all = r.data.items || [];
    list = pagedList({ key: "xc-pages", items: all, row: pageRow, label: "پیج‌ها",
      emptyEl: empty({ icon: "search", title: all.length ? "پیجی با این نام نیست" : "هنوز پیجی ذخیره نشده",
        text: all.length ? "نام را کوتاه‌تر بنویس." : "با خواندنِ یک پیج یا آپلودِ یک فایلِ JSON، این‌جا پر می‌شود." }) });
    mount(box, list);
    filter();
  }
  find.addEventListener("input", filter);
  load();
  const el = h("section", { class: "xc-card", "aria-labelledby": "xc-pg-h" },
    h("div", { class: "xc-card-top" }, h("h2", { class: "xc-h2", id: "xc-pg-h" }, icon("download"), h("span", { text: "دریافتِ JSON" }), count),
      iconButton({ icon: "refresh", label: "تازه کردنِ فهرست", onClick: load })),
    h("p", { class: "xc-help", text: "هر فایل همه‌چیزِ ذخیره‌شدهٔ یک پیج است: پروفایل، پست‌ها، هایلایت‌ها، فهرستِ کاملِ فالوورها و فالووینگ‌ها، و پروفایلِ هر کدام که خوانده شده. عکس‌ها به‌صورتِ لینک داخلش هستند." }),
    find, other, box);
  return { el, reload: load };
}

export function render() {
  const pages = pagesCard();
  const el = h("div", { class: "xc" },
    h("header", { class: "xc-head" }, h("h1", { class: "xc-h1", text: "تبادلِ JSON" }),
      h("p", { class: "xc-lead", text: "دادهٔ یک پیج را برای آباگرامِ دیگری بفرست، یا فایلی که از آن‌جا آمده را این‌جا بگذار تا با داده‌های این‌جا یکی شود." })),
    uploader(() => pages.reload()), pages.el);
  return { el };
}

/** The whole site for the «فقط JSON» role: the same page under a small bar with who is in and «خروج». */
export function renderStandalone(me) {
  const out = button({ label: "خروج", icon: "login", kind: "ghost", size: "sm",
    onClick: async () => { await authLogout().catch(() => null); location.reload(); } });
  const top = h("header", { class: "xc-top" },
    h("span", { class: "xc-brand" }, icon("mark", { size: "lg", cls: "xc-mark" }), h("span", { class: "xc-word", text: "آباگرام" })),
    h("span", { class: "xc-me" }, icon("user", { size: "sm" }), ltr(me.username), chip({ text: ROLE_FA[me.role] || me.role })), out);
  const page = render();
  document.title = "آباگرام — تبادلِ JSON";
  return { el: h("div", { class: "xc-app" }, top, h("main", { id: "main", class: "xc-main", tabindex: "-1" }, page.el)) };
}
