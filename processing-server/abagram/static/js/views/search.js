// «جستجو»: find a saved profile or read a new one from Instagram. A drawer beside the nav; a full page on phones.
import { h, icon, ltr, bdi, on, uid, qsa } from "../core/dom.js";
import { getProfiles, avatarUrl, cleanUsername, isPostLink } from "../core/api.js";
import { faNum, faCompact, ago, fresh, unit } from "../core/format.js";
import { state, subscribe, pref } from "../core/store.js";
import { avatar, verified, lock, skeleton, pagedList, listState, button, iconButton } from "../core/ui.js";
import { startJob, cost, runningFor } from "../core/jobs.js";
import { confirm } from "../core/overlay.js";

const RECENT_MAX = 8;
const LOAD_MAX = 50;
const RINGS = ["story", "seen", "loading"];
const KEEP = ["full_name", "followers", "is_verified", "is_private", "has_avatar", "fetched_at", "story_at"];
const POST_LINK = "این لینک پست است؛ لینک صفحهٔ پروفایل یا یوزرنیم را بده.";

const href = (u) => `#/u/${encodeURIComponent(u)}`;
const pic = (p) => (p.has_avatar ? avatarUrl(p.username, p.fetched_at) : null);
// /api/profiles rows may carry story_at flat or inside `more` (the dossier shape)
const restRing = (p) => (fresh(p.story_at ?? p.more?.story_at) ? "story" : "");

// ---- recent: the last 8 profiles opened from here (pref 'recent'), newest first ----
export function recent() {
  const list = pref("recent");
  return (Array.isArray(list) ? list : []).map((r) => (typeof r === "string" ? { username: r } : r)).filter((r) => r && cleanUsername(r.username));
}

// A name we may ask Instagram for: never a post link (same rule as the server)
const nameOf = (raw) => { const t = String(raw || "").trim(); return t && !isPostLink(t) ? cleanUsername(t) : null; };

/** Put a profile on top of the recent list. p: a /api/profiles row, a dossier profile, or just {username}. */
export function remember(p) {
  const u = cleanUsername(p?.username);
  if (!u) return;
  const list = recent();
  const entry = { ...(list.find((r) => r.username === u) || {}), username: u };
  for (const k of KEEP) if (p[k] !== undefined && p[k] !== null) entry[k] = p[k];
  if (!entry.story_at && p.more?.story_at) entry.story_at = p.more.story_at;
  pref("recent", [entry, ...list.filter((r) => r.username !== u)].slice(0, RECENT_MAX));
}

const forget = (u) => pref("recent", recent().filter((r) => r.username !== u));

// The ring slot keeps its size, so a ring that appears (a job starts) never moves the text.
function setRing(av, ring) {
  if ((RINGS.find((r) => av.classList.contains(`av-${r}`)) || "") === ring) return;
  av.classList.remove("av-ring", ...RINGS.map((r) => `av-${r}`));
  if (ring) av.classList.add("av-ring", `av-${ring}`);
}

function face(p) {
  const rest = restRing(p);
  const av = avatar({ u: p.username, src: pic(p), size: 44, ring: runningFor(p.username) ? "loading" : rest || null, zoom: true });
  av.dataset.seU = p.username;
  av.dataset.seRest = rest;
  return h("span", { class: "se-av" }, av, rest ? h("span", { class: "sr-only", text: "استوری تازه" }) : null);
}

// ---- one saved profile: the picture opens big (zoom.js takes that click), the rest opens the profile ----
function personRow(p, onOpen, extra) {
  const name = p.full_name ? h("span", { class: "se-sub-name ellipsis" }, bdi(p.full_name)) : null;
  const fol = p.followers != null ? h("span", { class: "se-sub-fol nowrap" }, bdi(`${faCompact(p.followers)} فالوور`)) : null;
  return h("div", { class: "se-item" },
    h("a", { class: "se-row", href: href(p.username), onclick: () => onOpen(p) },
      face(p),
      h("span", { class: "se-text" },
        h("span", { class: "se-top" }, h("span", { class: "se-user ellipsis", dir: "ltr" }, ltr(p.username)),
          p.is_verified ? verified() : null, p.is_private ? lock() : null),
        name || fol ? h("span", { class: "se-sub" }, name, fol) : null)),
    extra || null);
}

// ---- the row that asks Instagram: «خواندن @name از اینستاگرام» ----
function readRow(u, saved, onRead) {
  let sub;
  if (state.status?.busy) sub = "یک کار دیگر در حال اجراست؛ بعد از پایانش شروع کن.";
  else if (saved?.fetched_at) sub = h("span", null, "آخرین خواندن ", bdi(ago(saved.fetched_at)));
  else sub = state.status?.budget ? cost("profile")[0] : `${faNum(1)} صفحه از اینستاگرام`;
  return h("button", { type: "button", class: "se-row se-read", onclick: () => onRead(u, saved) },
    h("span", { class: "se-av" }, h("span", { class: "se-read-ic" }, icon(saved ? "refresh" : "search"))),
    h("span", { class: "se-text" },
      h("span", { class: "se-read-label" }, "خواندن ", ltr(`@${u}`), " از اینستاگرام"),
      h("span", { class: "se-sub" }, sub)));
}

const placeholder = () => h("div", { class: "se-sk", "aria-hidden": "true" },
  Array.from({ length: 3 }, () => h("div", { class: "se-sk-row" }, skeleton("avatar"),
    h("span", { class: "se-sk-lines" }, skeleton("line", 2)))));

const missNote = () => h("div", { class: "se-miss" },
  h("p", { class: "se-miss-title", text: "پروفایل ذخیره‌شده‌ای با این متن نیست" }),
  h("p", { class: "se-miss-text", text: "برای خواندن از اینستاگرام یوزرنیم را بنویس: حروف لاتین، عدد، نقطه و زیرخط، تا ۳۰ حرف." }));

export function render(params, ctx) {
  const ids = { title: uid("se-t"), err: uid("se-e"), recent: uid("se-r"), found: uid("se-f") };
  let saved = null, total = 0, failed = false, alive = true, exact = null, lastQ = null, frame = 0;

  const input = h("input", {
    class: "se-input", type: "search", dir: "ltr", placeholder: "یوزرنیم یا لینک پروفایل", "aria-label": "یوزرنیم یا لینک پروفایل",
    autocomplete: "off", autocapitalize: "off", autocorrect: "off", spellcheck: "false", enterkeyhint: "search", "aria-describedby": ids.err });
  const clear = h("button", { type: "button", class: "se-clear", "aria-label": "پاک کردن متن", title: "پاک کردن متن", hidden: true,
    onclick: () => { input.value = ""; draw(); input.focus(); } }, h("span", { class: "se-clear-face" }, icon("x", { size: "sm" })));
  const err = h("p", { class: "se-err", id: ids.err, "aria-live": "polite" });
  const body = h("div", { class: "se-body" });

  // Opening goes through the row's own href. The recent list is written a tick later: redrawing it now would
  // detach the clicked link, and a detached link does not navigate.
  const open = (p) => { setTimeout(() => remember(p), 0); };

  async function read(u, savedP) {
    const r = await startJob("profile", { username: u, fresh: !!savedP });
    if (r?.ok) { remember(savedP || { username: u }); ctx.navigate(`/u/${u}`); }
  }

  // ---- recent ----
  const removeBtn = (p) => iconButton({ icon: "x", label: `حذف ${p.username} از اخیر`, cls: "se-remove", onClick: () => forget(p.username) });
  const recentList = pagedList({ key: "search-recent", label: "جستجوهای اخیر", items: recent(), cls: "se-list",
    row: (p) => personRow(p, open, removeBtn(p)),
    emptyEl: h("p", { class: "se-none", text: "جستجوی اخیری نیست. یوزرنیم یا لینک صفحه‌ای را بالا بنویس." }) });
  const clearAll = button({ label: "پاک کردن همه", kind: "link", size: "sm", cls: "se-clear-all", onClick: async () => {
    const yes = await confirm({ title: "پاک کردن جستجوهای اخیر؟", text: "فقط همین فهرست پاک می‌شود؛ پروفایل‌های ذخیره‌شده سر جایشان می‌مانند.",
      cta: "پاک کردن همه", danger: true });
    if (yes) { pref("recent", []); input.focus(); }
  } });
  clearAll.hidden = !recent().length;
  const recentSec = h("section", { class: "se-sec", "aria-labelledby": ids.recent },
    h("div", { class: "se-sec-head" }, h("h3", { class: "se-sec-title", id: ids.recent, text: "اخیر" }), clearAll),
    recentList);

  // ---- results ----
  const count = h("span", { class: "se-count" });
  const note = h("p", { class: "se-note" });
  const foundList = pagedList({ key: "search-results", label: "پروفایل‌های ذخیره‌شده", items: [], cls: "se-list", row: (p) => personRow(p, open) });
  const foundSec = h("section", { class: "se-sec", "aria-labelledby": ids.found },
    h("div", { class: "se-sec-head" }, h("h3", { class: "se-sec-title", id: ids.found, text: "پروفایل‌های ذخیره‌شده" }), count),
    note, foundList);

  function matches(q) {
    const low = (p) => String(p.username).toLowerCase();
    const rank = (p) => (low(p) === q ? 0 : low(p).startsWith(q) ? 1 : 2);
    return (saved || []).filter((p) => low(p).includes(q) || String(p.full_name || "").toLowerCase().includes(q))
      .sort((a, b) => rank(a) - rank(b));
  }

  const failBox = () => h("div", { class: "se-fail", role: "alert" },
    h("span", { text: "پروفایل‌های ذخیره‌شده خوانده نشدند؛ سرور محلی جواب نداد." }),
    button({ label: "دوباره", icon: "refresh", size: "sm", onClick: () => { failed = false; draw(); load(); } }));

  function draw() {
    const text = input.value.trim(), post = !!text && isPostLink(text), name = nameOf(text);
    clear.hidden = !input.value;
    err.textContent = post ? POST_LINK : "";
    input.setAttribute("aria-invalid", post ? "true" : "false");
    exact = null;
    if (!text) { lastQ = null; body.replaceChildren(recentSec); return; }
    if (post) { body.replaceChildren(); return; }
    const q = (name || text.replace(/^@/, "")).toLowerCase();
    if (q !== lastQ) { listState("search-results").page = 0; lastQ = q; }
    const kids = [];
    if (failed) kids.push(failBox());
    else if (!saved) kids.push(h("div", { class: "se-sec", "aria-busy": "true" }, placeholder()));
    else {
      const found = matches(q);
      exact = (name && found.find((p) => String(p.username).toLowerCase() === name)) || null;
      if (found.length) {
        count.replaceChildren(bdi(unit(found.length, "پروفایل")));
        note.textContent = total > saved.length ? `جستجو فقط در ${faNum(saved.length)} پروفایل تازه‌تر از ${faNum(total)} پروفایل ذخیره‌شده انجام شد.` : "";
        note.hidden = !note.textContent;
        foundList.redraw(found);
        kids.push(foundSec);
      } else if (!name) kids.push(missNote());
    }
    if (name) kids.push(readRow(name, exact, read));
    body.replaceChildren(...kids);
  }

  async function load() {
    try {
      const r = await getProfiles(0, LOAD_MAX);
      failed = !r.ok;
      if (r.ok) { saved = (r.data?.items || []).filter((p) => p?.username); total = r.data?.total ?? saved.length; }
    } catch { failed = true; }
    if (alive) draw();
  }

  function syncRings() {
    for (const av of qsa("[data-se-u]", body)) setRing(av, runningFor(av.dataset.seU) ? "loading" : av.dataset.seRest || "");
  }

  // Enter opens the exact saved match (else asks Instagram); the first Esc empties the field (the next one closes
  // the drawer); arrow keys walk the rows, and up from the first row returns to the field.
  function keys(e) {
    const inField = e.target === input;
    if (inField && e.key === "Enter") {
      e.preventDefault();
      if (exact) { remember(exact); ctx.navigate(`/u/${exact.username}`); } else if (nameOf(input.value)) read(nameOf(input.value), null);
    } else if (inField && e.key === "Escape" && input.value) {
      e.preventDefault(); input.value = ""; draw();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const rows = qsa(".se-row", body), i = inField ? -1 : rows.indexOf(document.activeElement);
      const next = !inField && i < 0 ? null : e.key === "ArrowDown" ? rows[i + 1] : inField ? null : rows[i - 1] || input;
      if (next) { e.preventDefault(); next.focus(); }
    }
  }

  const el = h("section", { class: "se", "aria-labelledby": ids.title, onkeydown: keys },
    h("header", { class: "se-head" }, h("h2", { class: "se-title", id: ids.title, text: "جستجو" }),
      h("div", { class: "se-box" }, icon("search", { size: "sm", cls: "se-glass" }), input, clear), err),
    body);

  const offs = [on(input, "input", draw), subscribe("status", syncRings), subscribe("job-start", draw), subscribe("job-end", load),
    subscribe("settings", ({ key }) => { if (key === "recent") { clearAll.hidden = !recent().length; recentList.redraw(recent()); } })];

  draw();
  load();
  frame = requestAnimationFrame(() => { if (alive && el.isConnected) input.focus({ preventScroll: true }); });
  return { el, update() { if (!input.value) recentList.redraw(recent()); },
    destroy() { alive = false; cancelAnimationFrame(frame); offs.forEach((off) => off()); } };
}
