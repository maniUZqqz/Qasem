// News from the queue (a follow request accepted, a full extraction finished): a toast, a desktop notification when he
// allowed it, and the unread count on «فعالیت». Started once by main.js. Also the list shown in the activity drawer.
import { h, icon, ltr, mount } from "../core/dom.js";
import { api, getAccounts, accountAct } from "../core/api.js";
import { ago, faNum } from "../core/format.js";
import { state, subscribe, pref, pokePolling } from "../core/store.js";
import { toast, button } from "../core/ui.js";
import { navigate } from "../core/router.js";

const ICON = { accepted: "circle-check", full_done: "layers", harvest_done: "users", process_done: "filter", monitor_new: "eye", limit: "hourglass", declined: "circle-x", failed: "alert" };

function badge(n, where = '.sh-item[data-name="activity"] .sh-ic, .sh-act .sh-ic') {
  for (const ic of document.querySelectorAll(where)) {
    let b = ic.querySelector(".sh-badge");
    if (!n) { b?.remove(); continue; }
    if (!b) ic.append(b = h("span", { class: "sh-badge", "aria-hidden": "true" }));
    b.textContent = n > 9 ? "۹+" : n.toLocaleString("fa-IR");
  }
}

export function startNotify() {
  let seen = new Set(pref("seenNotices") || []);
  let first = true;
  subscribe("status", (s) => {
    const q = s.queue;
    if (!q) return;
    badge(q.unread);
    badge(q.watch_unseen, '.sh-item[data-name="monitors"] .sh-ic');   // «رصدها»: new posts / stories not seen yet
    const fresh = (q.notices || []).filter((n) => !n.read && !seen.has(n.id));
    if (!fresh.length) return;
    fresh.forEach((n) => seen.add(n.id));
    pref("seenNotices", [...seen].slice(-80));
    if (first) { first = false; return; }      // what was already waiting when the page opened is shown in the drawer, not popped
    for (const n of fresh) {
      toast(n.title, { tone: n.kind === "declined" || n.kind === "failed" ? "danger" : "ok", action: { label: "نمایش", onClick: () => navigate(`/u/${n.username}`) } });
      try {
        if ("Notification" in window && Notification.permission === "granted") {
          const note = new Notification(n.title, { body: n.text || "", tag: n.id, icon: `/api/avatar/${encodeURIComponent(n.username)}` });
          note.onclick = () => { window.focus(); navigate(`/u/${n.username}`); };
        }
      } catch { /* not offered */ }
    }
  });
}

// By hand, one tap: the other logged-in account becomes the active one (limits stay shared; nothing switches by itself).
async function goOther() {
  const r = await getAccounts().catch(() => null);
  const to = r?.ok && r.data.items.find((a) => !a.active && a.logged_in);
  if (!to) { toast("حساب دیگری که وارد شده باشد نیست؛ از «مانیتورینگ» اضافه‌اش کن.", { tone: "danger" }); return; }
  const done = await accountAct(to.username, "switch").catch(() => null);
  if (done?.ok) { toast(`حساب فعال: @${to.username}`, { tone: "ok" }); pokePolling(); } else toast("تا پایان کار جاری نمی‌شود حساب را عوض کرد.", { tone: "danger" });
}

/** The news list for the activity drawer (unread first), with «همه خوانده شد». */
/** compact: only what is unread (three at most) and a button for the rest, so the news never pushes the page down. */
export function noticeList({ compact = false } = {}) {
  const el = h("section", { class: ["nt", compact && "nt-compact"], "aria-label": "خبرها" });
  let key = "", open = false;
  function draw() {
    const q = state.status?.queue, list = q?.notices || [];
    const k = JSON.stringify([open, list.map((n) => [n.id, n.read])]);
    if (k === key) return;
    key = k;
    if (!list.length) return mount(el);
    const unread = list.filter((n) => !n.read);
    const shown = !compact || open ? list : unread.slice(0, 3);
    const more = compact && (open || list.length > shown.length) ? button({ label: open ? "بستن خبرهای قبلی" : `همهٔ خبرها (${faNum(list.length)})`,
      kind: "link", size: "sm", onClick: () => { open = !open; draw(); } }) : null;
    mount(el, h("header", { class: "nt-head" }, h("h3", { text: compact && !open ? (unread.length ? `خبرهای تازه (${faNum(unread.length)})` : "خبر تازه‌ای نیست") : "خبرها" }),
      h("span", { class: "nt-acts" }, more, q.unread ? button({ label: "همه خوانده شد", kind: "link", size: "sm", onClick: () => api("/api/notices/read", {}).then(() => pokePolling()) }) : null)),
    shown.length ? h("ul", { class: "nt-list" }, shown.map((n) => h("li", { class: ["nt-row", !n.read && "is-new"] },
      h("a", { class: "nt-link", href: `#/u/${n.username}` }, h("span", { class: `nt-ic nt-${n.kind}` }, icon(ICON[n.kind] || "bell", { size: "sm" })),
        h("span", { class: "nt-text" }, h("b", { text: n.title }), n.text ? h("span", { text: n.text }) : null,
          h("small", {}, ltr(`@${n.username}`), " ", ago(n.at)))),
      n.kind === "limit" ? button({ label: "رفتن به حساب دیگر", size: "sm", onClick: goOther }) : null))) : null);
  }
  const off = subscribe("status", draw);
  draw();
  el.destroy = off;
  return el;
}
