// «پردازش»: who among a page's followers matters most. Step 1 scores everyone from the saved list alone (public or private, a
// real picture, business and trade words in the name; nothing is asked of Instagram) and makes the reading order, best first.
// Step 2 reads the profiles in that order through the queue. Step 3: the results — a final score, a label (farmer / seller /
// maker / other, his own label wins), filters, and an Excel file. Server: /api/process (ig_process.py, ig_score.py).
import { h, icon, ltr, bdi, uid, mount } from "../core/dom.js";
import { api, getProcessLists, getProcessPage, processAct, processRank, processLabel, processExportUrl, avatarUrl } from "../core/api.js";
import { faNum, faCompact, faTime, unit } from "../core/format.js";
import { state, subscribe, pokePolling } from "../core/store.js";
import { avatar, empty, skeleton, pagedList, listState, button, segmented, toast } from "../core/ui.js";
import { menu } from "../core/overlay.js";
import { enter } from "../core/motion.js";

const WHICH_FA = { followers: "فالوورها", following: "فالووینگ‌ها" };
const LABELS = [["farmer", "کشاورز"], ["seller", "فروشنده یا نماینده"], ["maker", "تولیدکننده یا شرکت"], ["org", "سازمان یا نهاد"], ["other", "نامرتبط"], ["unknown", "خوانده نشده"]];
const LABEL_FA = Object.fromEntries(LABELS);
const ACCOUNTS = [["", "همه"], ["business", "کسب‌وکار"], ["creator", "کریتور"], ["personal", "شخصی"]];
const MINS = [[0, "همه"], [40, "۴۰ به بالا"], [70, "۷۰ به بالا"]];
const href = (u) => `#/u/${encodeURIComponent(u)}`;
const tone = (score) => (score >= 70 ? "ok" : score >= 40 ? "warn" : "idle");

// ---- step 1: which list ----
function listPicker(lists, current, onPick) {
  return h("div", { class: "pc-lists", role: "radiogroup", "aria-label": "فهرست برای پردازش" }, lists.map((x) => {
    const on = current && x.source === current.source && x.which === current.which;
    return h("button", { type: "button", role: "radio", "aria-checked": String(!!on), class: "pc-list", onclick: () => onPick(x) },
      avatar({ u: x.source, src: avatarUrl(x.source), size: 36, zoom: false }),
      h("span", { class: "pc-list-t" }, h("b", {}, ltr(`@${x.source}`), ` — ${WHICH_FA[x.which]}`),
        h("small", { text: x.total ? `${faNum(x.saved)} از ${faNum(x.total)} نفر ذخیره شده${x.complete ? "؛ کامل" : ""}` : `${faNum(x.saved)} نفر ذخیره شده` })),
      on ? icon("check", { size: "sm", cls: "pc-list-ok" }) : null);
  }));
}

// ---- step 1: his trade words, as removable chips (they count on top of the built-in trade words) ----
function wordsEditor(initial) {
  let words = [...initial];
  const id = uid("pc-w");
  const box = h("div", { class: "pc-chips", "aria-live": "polite" });
  const input = h("input", { id, class: "input pc-w-in", type: "text", autocomplete: "off", spellcheck: "false", enterkeyhint: "done",
    placeholder: "کلمهٔ تازه، مثلاً netafim یا قطره‌ای" });
  const draw = () => mount(box, ...words.map((w) => h("span", { class: "pc-chip" }, bdi(w),
    h("button", { type: "button", class: "pc-chip-x", "aria-label": `حذف ${w}`, onclick: () => { words = words.filter((x) => x !== w); draw(); } },
      icon("x", { size: "sm" })))));
  const add = () => {
    const fresh = input.value.split(/[,،\n]/).map((w) => w.trim()).filter(Boolean).filter((w) => !words.includes(w));
    input.value = "";
    if (fresh.length) { words = [...words, ...fresh].slice(0, 60); draw(); }
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === "," || e.key === "،") { e.preventDefault(); add(); } });
  draw();
  const el = h("div", { class: "pc-words" },
    h("label", { class: "pc-label", for: id, text: "کلمه‌های کار تو (اختیاری)" }),
    h("p", { class: "pc-help", text: "کلمه‌های رایج این کار (آبیاری، قطره، sulama، drip، sera…) خودشان حساب می‌شوند؛ اسم برندها یا کلمه‌های خاص خودت را اینجا اضافه کن." }),
    box, h("div", { class: "pc-w-row" }, input, button({ label: "افزودن", icon: "plus", onClick: add })));
  return { el, get: () => words };
}

/** How many people are high, middle and low — one bar, three parts, with the numbers under it. */
function spread(b, people) {
  const all = Math.max(1, (b.high || 0) + (b.mid || 0) + (b.low || 0));
  const part = (k, cls) => h("i", { class: cls, style: `--w:${(b[k] || 0) / all}` });
  return h("div", { class: "pc-spread" },
    h("div", { class: "pc-spread-bar", "aria-hidden": "true" }, part("high", "is-ok"), part("mid", "is-warn"), part("low", "is-idle")),
    h("div", { class: "pc-spread-keys" },
      h("span", { class: "is-ok" }, h("b", {}, bdi(faNum(b.high || 0))), " امیدوارکننده (۷۰+)"),
      h("span", { class: "is-warn" }, h("b", {}, bdi(faNum(b.mid || 0))), " متوسط (۴۰ تا ۶۹)"),
      h("span", { class: "is-idle" }, h("b", {}, bdi(faNum(b.low || 0))), " کم (زیر ۴۰)"),
      h("span", { class: "pc-spread-all" }, "از ", bdi(unit(people, "نفر")))));
}

// ---- step 2: about how long reading the candidates left takes (the fast reader has its own limit) ----
function eta(left) {
  const lim = state.status?.budget?.limits || {}, fast = !!state.status?.fast_profiles;
  const perHour = fast ? lim.lookups_hour || 300 : lim.pages_hour || 30, perDay = fast ? lim.lookups_day || 3000 : lim.pages_day || 150;
  if (!left) return "";
  if (left <= perHour) return "کمتر از یک ساعت";
  if (left <= perDay) return `حدود ${faNum(Math.ceil(left / perHour))} ساعت`;
  return `حدود ${faNum(Math.ceil(left / perDay))} روز (روزی ${faNum(perDay)} پروفایل)`;
}

// ---- step 3: the results ----
/** A fact of the profile as a chip; numbers, mails and links read left to right inside the RTL page. */
function fact(ic, text, link) {
  const kids = [icon(ic, { size: "sm" }), ltr(text)];
  return link ? h("a", { class: "chip pc-fact", href: link, target: link.startsWith("http") ? "_blank" : null, rel: "noopener noreferrer" }, ...kids)
    : h("span", { class: "chip pc-fact" }, ...kids);
}

function resultRow(r, onLabel) {
  const facts = [
    r.phone ? fact("phone", r.phone, `tel:${r.phone.replace(/[^\d+]/g, "")}`) : null,
    r.email ? fact("at", r.email, `mailto:${r.email}`) : null,
    r.category ? h("span", { class: "chip pc-fact" }, icon("briefcase", { size: "sm" }), bdi(r.category)) : null,
    r.city ? h("span", { class: "chip pc-fact" }, icon("pin-map", { size: "sm" }), bdi(r.city)) : null,
    ...(r.links || []).map((l) => fact("link", l.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "").slice(0, 40), l)),
  ].filter(Boolean);
  const labelBtn = h("button", { type: "button", class: ["pc-label-btn", `is-${r.label}`, r.manual && "is-manual"],
    "aria-haspopup": "menu", title: r.manual ? "برچسبی که خودت گذاشتی" : "برچسب خودکار؛ برای عوض کردن بزن",
    onclick: () => menu(labelBtn, [
      ...LABELS.filter(([k]) => k !== "unknown").map(([k, t]) => ({ label: t, icon: k === r.label ? "check" : null, onSelect: () => onLabel(r, k) })),
      r.manual ? { label: "برگرداندن به برچسب خودکار", hint: LABEL_FA[r.label_auto], onSelect: () => onLabel(r, null) } : null,
    ], { label: "برچسب این نفر" }) },
  h("span", { text: LABEL_FA[r.label] || r.label }), icon("chevron", { size: "sm" }));
  const kind = { business: "کسب‌وکار", creator: "کریتور", personal: "شخصی" }[r.account];
  return h("article", { class: ["pc-row", !r.read && "is-unread"], "aria-label": `@${r.username}` },
    h("div", { class: ["pc-score", `is-${tone(r.score)}`], title: r.read ? "امتیاز نهایی" : "امتیاز اولیه (پروفایل هنوز خوانده نشده)" },
      h("b", { text: faNum(r.score) }), h("small", { text: r.read ? "امتیاز" : "اولیه" })),
    avatar({ u: r.username, src: r.read && r.has_avatar ? avatarUrl(r.username) : null, size: 44, href: href(r.username), label: `پروفایل @${r.username}` }),
    h("div", { class: "pc-row-main" },
      h("div", { class: "pc-row-top" },
        h("a", { class: "pc-user", href: href(r.username) }, ltr(`@${r.username}`)),
        kind ? h("span", { class: ["pc-tag", r.account !== "business" && "is-muted"], text: kind }) : null,
        r.private ? h("span", { class: "pc-tag is-muted", text: "خصوصی" }) : null,
        r.followers != null ? h("span", { class: "pc-num", text: `${faCompact(r.followers)} فالوور` }) : null,
        labelBtn),
      r.full_name ? h("div", { class: "pc-full" }, bdi(r.full_name)) : null,
      r.why?.length ? h("p", { class: "pc-why" }, ...r.why.filter((w) => !w.startsWith("دسته: ")).slice(0, 4)   // the category is a chip below
        .flatMap((w, i) => [i ? "، " : "", bdi(w)])) : null,
      r.bio ? h("p", { class: "pc-bio", dir: "auto", text: r.bio }) : null,
      facts.length ? h("div", { class: "pc-facts" }, facts) : null));
}

function results(src, which) {
  const f = { label: new Set(), account: "", contact: false, min_followers: "", city: "", q: "", sort: "score" };
  const params = () => ({ label: [...f.label].join(","), account: f.account, contact: f.contact ? 1 : "", min_followers: f.min_followers,
    city: f.city.trim(), q: f.q.trim(), sort: f.sort });
  const labels = h("div", { class: "pc-flabels", role: "group", "aria-label": "برچسب‌ها" });
  const box = h("div", { class: "pc-results" }, ...skeleton("line", 3));
  const found = h("p", { class: "pc-found", "aria-live": "polite" });
  const excel = h("a", { class: "btn sm pc-excel", download: "" }, icon("download", { size: "sm" }), h("span", { text: "خروجی Excel همین فهرست" }));
  let timer = 0, facets = null, run = 0;
  const later = () => { clearTimeout(timer); timer = setTimeout(load, 350); };
  const input = (ph, key, type = "text") => h("input", { class: "input pc-fin", type, placeholder: ph, dir: "auto", autocomplete: "off",
    inputmode: type === "number" ? "numeric" : null, "aria-label": ph, oninput: (e) => { f[key] = e.target.value; later(); } });
  const contact = h("label", { class: "pc-check" }, h("input", { type: "checkbox", class: "pc-check-box", onchange: (e) => { f.contact = e.target.checked; load(); } }),
    h("span", { class: "pc-check-ui", "aria-hidden": "true" }, icon("check", { size: "sm" })), h("span", { text: "فقط دارای شماره یا ایمیل" }));
  const tools = h("div", { class: "pc-filters" }, labels,
    h("div", { class: "pc-frow" }, segmented({ label: "نوع حساب", value: "", options: ACCOUNTS.map(([v, l]) => ({ value: v, label: l })), onChange: (v) => { f.account = v; load(); } }), contact),
    h("div", { class: "pc-frow" }, input("جستجو در نام، بیو و دسته", "q", "search"), input("شهر", "city"), input("حداقل فالوور", "min_followers", "number")),
    h("div", { class: "pc-frow pc-frow-end" }, h("span", { class: "pc-sort-l", text: "ترتیب:" }),
      segmented({ label: "ترتیب", value: "score", options: [{ value: "score", label: "امتیاز" }, { value: "followers", label: "فالوور" }, { value: "name", label: "یوزرنیم" }],
        onChange: (v) => { f.sort = v; load(); } }), excel));

  function drawLabels() {
    const n = facets?.label || {};
    mount(labels, ...LABELS.map(([k, t]) => h("button", { type: "button", class: ["pc-flabel", `is-${k}`], "aria-pressed": String(f.label.has(k)),
      onclick: () => { if (f.label.has(k)) f.label.delete(k); else f.label.add(k); drawLabels(); load(); } },
    h("span", { text: t }), h("b", { text: faNum(n[k] || 0) }))));
  }
  async function onLabel(r, label) {
    const res = await processLabel(src, which, r.username, label).catch(() => null);
    if (!res?.ok) return toast("برچسب عوض نشد.", { tone: "danger" });
    toast(label ? `@${r.username}: ${LABEL_FA[label]}` : `@${r.username}: برچسب خودکار`, { tone: "ok" });
    load(true);
  }
  async function load(keepPage) {
    const mine = ++run, st = listState("process-results");
    if (!keepPage) st.page = 0;
    const first = await getProcessPage(src, which, { ...params(), offset: st.page * st.size, limit: st.size }).catch(() => null);
    if (mine !== run) return;
    if (!first?.ok) { mount(box, empty({ icon: "alert", title: "نتیجه‌ها باز نشد", text: "سرور جواب نداد؛ دوباره امتحان کن." })); return; }
    const d = first.data.data;
    facets = d.facets; drawLabels();
    mount(found, bdi(unit(d.total, "نفر")), " از ", bdi(unit(Object.values(facets.label).reduce((a, b) => a + b, 0), "نامزد")),
      facets.contact ? ["، ", bdi(faNum(facets.contact)), " نفر با شماره یا ایمیل"] : "");
    excel.href = processExportUrl(src, which, params());
    excel.toggleAttribute("aria-disabled", !d.total);
    const cached = { from: st.page * st.size, rows: d.rows };
    mount(box, pagedList({ key: "process-results", total: d.total, row: (r) => resultRow(r, onLabel), cls: "pc-plist", label: "نتیجه‌ها",
      emptyEl: empty({ icon: "filter", title: "کسی با این فیلترها نیست", text: "یکی از فیلترها را بردار." }),
      load: async (from, size) => {
        if (from === cached.from && size === d.rows.length) return cached.rows;
        const r = await getProcessPage(src, which, { ...params(), offset: from, limit: size }).catch(() => null);
        return r?.ok ? r.data.data.rows : [];
      } }));
  }
  load();
  return { el: h("div", { class: "pc-res" }, tools, found, box), reload: () => load(true) };
}

const TASK_FA = { waiting: "در صف", running: "در حال خواندن", paused: "متوقف", done: "تمام شد" };
const taskAct = (t, action) => api(`/api/queue/${t.id}/${action}`, {}).then((r) => { if (!r?.ok) toast("انجام نشد.", { tone: "danger" }); pokePolling(); });

export function render() {
  let lists = null, cur = null, data = null, defaults = [], dead = false, lastKey = "", words = null, min = 40, res = null;
  const one = h("section", { class: "pc-card", "aria-label": "قدم ۱: امتیاز و ترتیب خواندن" });
  const two = h("section", { class: "pc-card", "aria-label": "قدم ۲: خواندن پروفایل‌ها" });
  const three = h("section", { class: "pc-card pc-card-res", "aria-label": "قدم ۳: نتیجه‌ها" });
  const el = h("div", { class: "pc" },
    h("header", { class: "pc-head" }, h("h1", { class: "pc-title", text: "پردازش" }),
      h("p", { class: "pc-lede", text: "مهم‌ترین پیج‌های فالوورها را پیدا کن: اول به همه از روی همین فهرست امتیاز داده می‌شود (بی هیچ درخواستی به اینستاگرام)، بعد پروفایل‌ها به ترتیب امتیاز خوانده می‌شوند و هر نفر برچسب می‌خورد: کشاورز، فروشنده یا تولیدکننده." })),
    one, two, three);
  const task = () => (state.status?.queue?.tasks || []).find((t) => t.kind === "process" && cur && t.username === cur.source
    && (["waiting", "running", "paused"].includes(t.state) || Date.now() / 1000 - t.updated_at < 600));
  const step = (n, t) => h("h2", { class: "pc-step" }, h("span", { class: "pc-n", text: n }), t);

  function drawOne() {
    if (!lists.length) {
      mount(one, empty({ icon: "users", title: "هنوز فهرستی ذخیره نشده",
        text: "اول فالوورهای یک پیج را بخوان (در پروفایل پیج: «خواندن همهٔ فالوورها»)، بعد اینجا امتیازدهی کن." }));
      return;
    }
    if (!words) words = wordsEditor(data?.words || []);
    const go = button({ label: data ? "امتیازدهی دوباره" : "امتیازدهی و ساختن ترتیب خواندن", icon: "filter", kind: "primary", onClick: async () => {
      go.disabled = true;
      const r = await processRank(cur.source, cur.which, words.get(), min).catch(() => null);
      go.disabled = false;
      if (!r?.ok) return toast("امتیازدهی نشد؛ برنامه جواب نداد.", { tone: "danger" });
      data = r.data.data;
      toast(`${faNum(data.counts.total)} نامزد از ${faNum(data.people)} نفر، به ترتیب امتیاز`, { tone: "ok" });
      drawOne(); drawTwo(); drawThree(true);
    } });
    const x = lists.find((l) => l.source === cur.source && l.which === cur.which);
    mount(one, step("۱", "امتیاز و ترتیب خواندن"),
      listPicker(lists, cur, (pick) => { cur = pick; words = null; res = null; load(); }),
      words.el,
      h("div", { class: "pc-min" }, h("span", { class: "pc-label", text: "چه کسانی خوانده شوند" }),
        segmented({ label: "حداقل امتیاز اولیه", value: min, options: MINS.map(([v, l]) => ({ value: v, label: l })), onChange: (v) => { min = v; } }),
        h("small", { class: "pc-help", text: "۴۰ به بالا یعنی حساب‌های خصوصی بی‌عکس و مانند آن کنار می‌روند؛ بعداً می‌شود پایین‌تر هم آورد." })),
      h("div", { class: "pc-act" }, go,
        data?.filtered_at ? h("span", { class: "pc-sum" }, "آخرین امتیازدهی ساعت ", bdi(faTime(data.filtered_at))) : null),
      data?.buckets ? spread(data.buckets, data.people) : null,
      x && !x.complete ? h("p", { class: "pc-note" }, icon("info", { size: "sm" }), "فهرست این پیج هنوز کامل خوانده نشده؛ وقتی بقیه هم آمد، دوباره «امتیازدهی» را بزن تا تازه‌ها هم بیایند (برچسب‌ها و خوانده‌شده‌ها می‌مانند).") : null);
  }

  function drawTwo() {
    const head = step("۲", "خواندن پروفایل‌ها، به ترتیب امتیاز");
    if (!data) { mount(two, head, h("p", { class: "pc-muted", text: "اول قدم ۱ را انجام بده." })); return; }
    // «تقسیم کار» (Settings): with several systems this one reads only its own share; everything below counts that share
    const sh = data.share?.count > 1 ? data.share : null;
    const c = sh ? sh.counts : data.counts, t = task(), fast = !!state.status?.fast_profiles;
    const split = sh ? h("p", { class: "pc-note" }, icon("layers", { size: "sm" }), h("span", {},
      `کار بین ${faNum(sh.count)} سیستم تقسیم شده و این سیستمِ ${faNum(sh.index)} فقط سهمِ خودش را می‌خواند: `,
      bdi(`${faNum(c.total)} از ${faNum(data.counts.total)} نامزد`), "؛ خوانده‌های سیستم‌های دیگر با آپلودِ JSONشان این‌جا «خوانده شده» می‌شوند.")) : null;
    const line = h("p", { class: "pc-sum" }, bdi(`${faNum(c.total)} نامزد`), "، ", bdi(`${faNum(c.done)} خوانده شد`),
      c.failed ? ["، ", bdi(`${faNum(c.failed)} خوانده نشد`)] : "", "، ", bdi(`${faNum(c.new)} مانده`),
      c.new ? ["؛ زمان باقی‌مانده ", bdi(eta(c.new))] : "");
    const bar = c.total ? h("span", { class: "pj-bar", "aria-hidden": "true" }, h("i", { style: `--p:${(c.done + c.failed) / c.total}` })) : null;
    const live = t && t.state !== "done";
    const btns = live ? [
      t.state === "waiting" && t.next_at * 1000 > Date.now() ? button({ label: "الان انجام بده", size: "sm", onClick: () => taskAct(t, "now") }) : null,
      t.state === "waiting" ? button({ label: "توقف", size: "sm", kind: "ghost", onClick: () => taskAct(t, "pause") }) : null,
      t.state === "paused" ? button({ label: "ادامه", size: "sm", kind: "primary", onClick: () => taskAct(t, "resume") }) : null,
    ].filter(Boolean) : c.new ? [button({ label: "شروع خواندن پروفایل‌ها", icon: "play", kind: "primary", onClick: async () => {
      const r = await processAct(cur.source, cur.which, "start").catch(() => null);
      if (!r?.ok) return toast("در صف گذاشته نشد.", { tone: "danger" });
      toast("خواندن پروفایل‌ها به ترتیب امتیاز در صف گذاشته شد", { tone: "ok" }); pokePolling();
    } })] : [];
    mount(two, head, split, line, bar,
      fast ? null : h("p", { class: "pc-note" }, icon("info", { size: "sm" }), "خواندن سریع پروفایل هنوز خاموش است: هر پروفایل یک صفحهٔ کامل است (ساعتی حدود ۳۰ نفر). با روشن شدنش ساعتی چند صد نفر خوانده می‌شود."),
      live ? h("p", { class: "pc-task" }, h("b", { text: TASK_FA[t.state] || t.state }), t.note ? ["؛ ", t.note] : "") : null,
      !c.new && !live ? h("p", { class: "pc-muted", text: sh ? "همهٔ نامزدهای سهمِ این سیستم خوانده شده‌اند." : "همهٔ نامزدها خوانده شده‌اند." }) : null,
      btns.length ? h("div", { class: "pc-act" }, btns) : null);
  }

  function drawThree(fresh) {
    if (!data || !data.counts?.total) { three.hidden = true; res = null; return; }
    three.hidden = false;
    if (!res || fresh) {
      res = results(cur.source, cur.which);
      mount(three, step("۳", "نتیجه‌ها: مهم‌ترین‌ها اول"), res.el);
      if (fresh) enter(three, "fade");
    }
  }

  async function load() {
    const r = cur ? await getProcessPage(cur.source, cur.which, { limit: 1 }).catch(() => null) : null;
    if (dead) return;
    data = r?.ok ? r.data.data : null;
    // «چه کسانی خوانده شوند» shows the choice of the last ranking: it always came back as «۴۰ به بالا», so a list ranked with
    // «همه» and ranked again without a look silently lost every candidate under 40 (thousands, read ones among them)
    if (typeof data?.min_score === "number") min = data.min_score;
    drawOne(); drawTwo(); drawThree(true);
  }

  async function start() {
    mount(one, ...skeleton("line", 3));
    const r = await getProcessLists().catch(() => null);
    if (dead) return;
    if (!r?.ok) {
      mount(one, empty({ icon: "alert", title: "«پردازش» باز نشد", text: "سرور جواب نداد؛ دوباره امتحان کن.",
        action: button({ label: "تلاش دوباره", icon: "refresh", onClick: start }) }));
      return;
    }
    lists = r.data.items || [];
    defaults = r.data.default_words || [];
    cur = lists.find((x) => x.filtered) || lists.find((x) => x.source === "growtech.events") || lists[0] || null;
    await load();
  }

  const offs = [
    subscribe("status", () => {   // the queue read more profiles: new counts in step 2, the results refreshed in place
      if (!data) return;
      const t = task();
      const k = t ? JSON.stringify([t.id, t.state, t.note, t.steps?.[0]?.done]) : "";
      if (k === lastKey) return;
      const more = lastKey && t && JSON.parse(lastKey)[3] !== t.steps?.[0]?.done;
      lastKey = k;
      if (more) { getProcessPage(cur.source, cur.which, { limit: 1 }).then((r) => { if (r?.ok && !dead) { data = r.data.data; drawTwo(); res?.reload(); } }); }
      else drawTwo();
    }),
  ];
  start();
  return { el, update() {}, destroy() { dead = true; offs.forEach((off) => off()); } };
}
