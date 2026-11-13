// Story and highlight player (#/u/<name>/stories, #/u/<name>/hl/<id>): Instagram's full-screen viewer, mirrored for RTL.
import { h, svg, icon, ltr, bdi, on, mount } from "../core/dom.js";
import { api, media, alive, avatarUrl, thumbUrl, igUrl } from "../core/api.js";
import { faNum, ago } from "../core/format.js";
import { dossier as getDossier, files as getFiles, subscribe } from "../core/store.js";
import { avatar, button, spinner, setBusy } from "../core/ui.js";
import { startJob, cost } from "../core/jobs.js";
import { gallery } from "../core/zoom.js";
import { animate, enter, exit, DUR } from "../core/motion.js";

const IMAGE_MS = 5000, HOLD_MS = 200;   // a picture stays 5s (a video its own length); a press past 200ms pauses
const STICKER = { poll: ["نظرسنجی", "circle-check"], question: ["سؤال", "comment"], countdown: ["شمارش معکوس", "clock"],
  slider: ["اسلایدر", "gauge"], quiz: ["کوییز", "circle-check"] };
// Glyphs the sprite does not carry yet (Lucide paths). Once index.html has #i-<name>, the sprite wins.
const LOCAL = { pause: "M6 4h4v16H6zM14 4h4v16h-4z", volume: "M11 5 6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14",
  "volume-x": "M11 5 6 9H2v6h4l5 4zM22 9l-6 6M16 9l6 6", download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
  music: "M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z", maximize: "M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" };
const ic = (name, size = "md") => (LOCAL[name] && !document.getElementById(`i-${name}`)
  ? svg("svg", { class: ["ic", size === "sm" && "ic-sm"], viewBox: "0 0 24 24", "aria-hidden": "true" }, svg("path", { d: LOCAL[name] }))
  : icon(name, { size }));
const txt = (x, ...keys) => String((typeof x === "string" ? x : keys.map((k) => x?.[k]).find(Boolean)) || "");
const host = (url) => url.replace(/^https?:\/\/(www\.)?/i, "").split(/[/?#]/)[0];
// A layer above the story (the cost sheet, the big-picture viewer) holds it still and keeps the keys.
const covered = () => !!document.querySelector(".ov-layer, .vw:not([hidden])");
const keysOf = (it, hl) => ({ p: hl ? `h${hl}_p_${it.id}` : `sp_${it.id}`, v: hl ? `h${hl}_v_${it.id}` : `sv_${it.id}`,
  t: it.has_thumb ? `st_${it.id}` : null });
let lastClose = 0;

export function open(params, ctx) {
  const u = String(params.name || "").toLowerCase(), hl = params.id ? String(params.id) : null;
  const S = { items: [], i: 0, files: null, d: null, tray: [], title: "", av: null, paused: false, held: false, muted: false,
    spent: 0, last: 0, ready: false, video: null, want: null, raf: 0, leaving: false, closed: false };
  const from = document.activeElement, offs = [];
  const btn = (name, label, fn, cls) => h("button", { type: "button", class: ["icon-btn st-ib", cls], "aria-label": label, title: label, onclick: fn }, ic(name));
  const setBtn = (b, name, label) => { b.replaceChildren(ic(name)); b.setAttribute("aria-label", label); b.title = label; };

  const bars = h("div", { class: "st-bars", "aria-hidden": "true" }), where = h("span", { class: "sr-only" }), who = h("div", { class: "st-who" });
  const pauseB = btn("pause", "توقف", () => { S.paused = !S.paused; sync(); });
  const muteB = btn("volume", "بی‌صدا", () => { S.muted = !S.muted; if (S.video) S.video.muted = S.muted; sync(); });
  const box = h("div", { class: "st-media" }), hit = h("div", { class: "st-hit", "aria-hidden": "true" });
  const spot = h("div", { class: "st-spot", hidden: true });   // the shared post card: a tap shows «مشاهدهٔ پست» (Instagram does the same)
  const over = h("div", { class: "st-over" }), bar = h("div", { class: "st-bar" });
  const frame = h("div", { class: "st-frame" }, box, hit, spot,
    h("div", { class: "st-top" }, bars, h("div", { class: "st-head" }, who, h("div", { class: "st-acts" }, pauseB, muteB,
      btn("maximize", "نمایش بزرگ", () => big()), btn("x", "بستن", () => leave()))), where),
    h("div", { class: "st-low" }, over, bar));
  const prevB = btn("chev-r", "آیتم قبلی", () => step(-1), "st-nav st-prev"), nextB = btn("chev-l", "آیتم بعدی", () => step(1), "st-nav st-next");
  const before = h("div", { class: "st-side" }), after = h("div", { class: "st-side" });
  const layer = h("div", { class: "st-layer", role: "dialog", "aria-modal": "true", "aria-label": hl ? "هایلایت" : "استوری", tabindex: "-1", "data-msg": "" },
    h("div", { class: "st-stage" }, before, h("div", { class: "st-col" }, frame, prevB, nextB), after));

  const rtl = () => getComputedStyle(layer).direction === "rtl";
  const relock = () => { if (!S.closed) document.documentElement.setAttribute("data-overlay", ""); };
  // Leaving = close (ctx.dismiss, main.js goes back) or hop to another highlight; it happens once.
  const leave = (t) => { if (S.leaving || S.closed) return; S.leaving = true; S.video?.pause();
    if (t) ctx.navigate(`/u/${u}/hl/${encodeURIComponent(t.id)}`, { replace: true }); else ctx.dismiss(); };
  const near = (d) => { const k = hl ? S.tray.findIndex((t) => String(t.id) === hl) : -1; return k < 0 ? null : S.tray[k + d] || null; };
  const msg = (title, text, action, art) => { S.items = []; layer.setAttribute("data-msg", ""); mount(bars); mount(over); mount(bar);
    mount(box, h("div", { class: "st-msg" }, art, title ? h("p", { class: "st-msg-t", text: title }) : null, text ? h("p", { class: "st-msg-x", text }) : null, action)); };
  const jobBtn = (label, kind, body) => { const b = button({ label, kind: "primary", onClick: async () => { setBusy(b, true);
    const r = await startJob(kind, { username: u, ...body }, { lines: cost(kind, { profile: S.d?.profile, ids: body.ids }) });
    relock(); if (!r.ok) setBusy(b, false); } }); return b; };
  // Picture priority: downloaded file → live Instagram address → saved thumbnail (api.media decides).
  const pick = (it, id = hl) => { const k = keysOf(it, id), still = media(u, { fileKey: k.p, remote: it.image, thumbKey: k.t, files: S.files }).src;
    const v = it.type === "video" || it.video ? media(u, { fileKey: k.v, remote: it.video, files: S.files, video: true }).src : null;
    return v ? { kind: "video", src: v, still } : { kind: "image", src: still, still, cover: it.type === "video" }; };
  const cover = (t) => { const it = S.d?.reels?.highlights?.[t.id]?.items?.[0];
    return (it && pick(it, t.id).still) || (t.has_cover ? thumbUrl(u, `hl_${t.id}`) : alive(t.cover) ? t.cover : null); };

  async function load(force = false) {
    if (!S.items.length) msg(null, null, null, spinner(32));
    const [d, f] = await Promise.all([getDossier(u, { force }), getFiles(u, { force })]);
    if (S.closed) return; S.d = d; S.files = f?.files || null;
    if (!d) return msg("پروندهٔ این حساب باز نشد", "سرور برنامه جواب نداد؛ روشن بودنش را چک کن و دوباره امتحان کن.",
      button({ label: "دوباره امتحان کن", kind: "primary", onClick: () => load(true) }));
    const reels = d.reels?.highlights || {}, tray = d.highlights?.items || [];
    const t = hl && tray.find((x) => String(x.id) === hl), reel = hl ? reels[hl] : d.stories?.reel;
    S.tray = tray.filter((x) => reels[x.id]?.items?.length); S.title = hl ? reel?.title || t?.title || "" : "";
    S.av = d.profile?.has_avatar ? avatarUrl(u, d.profile.fetched_at) : null;
    layer.setAttribute("aria-label", hl ? `هایلایت ${S.title}` : `استوری ${u}`); sides();
    if (!reel?.items?.length) return empty(d, t);
    const keep = S.items.length ? Math.min(S.i, reel.items.length - 1) : 0;
    S.reel = reel; S.items = reel.items; layer.removeAttribute("data-msg");
    mount(bars, S.items.map(() => h("span", { class: "st-seg" }, h("span", { class: "st-fill" }))));
    downloads(); show(keep);
  }

  function empty(d, t) {
    if (hl) return msg("آیتم‌های این هایلایت هنوز خوانده نشده", "هر هایلایت جدا خوانده می‌شود و بعد همین‌جا پخش می‌شود.",
      jobBtn("خواندن آیتم‌های هایلایت", "highlights", { ids: [hl] }), t ? avatar({ u, src: cover(t), size: 96, ring: "seen" }) : null);
    const art = avatar({ u, src: S.av, size: 96, ring: d.stories ? "seen" : "story" });
    if (!d.stories) return msg("استوری فعالش هنوز خوانده نشده", "استوری‌ها ۲۴ ساعت می‌مانند؛ تا هست بخوانش تا اینجا بماند.",
      jobBtn("خواندن استوری فعال", "stories", {}), art);
    msg("الان استوری فعالی ندارد", d.stories.read_at ? `آخرین بررسی ${ago(d.stories.read_at)}` : null, jobBtn("دوباره بخوان", "stories", {}), art);
  }

  // Desktop: up to two read highlights on each side, dimmed; a click hops to one.
  function sides() {
    const k = hl ? S.tray.findIndex((x) => String(x.id) === hl) : -1;
    const mini = (t) => { const src = cover(t);
      return h("button", { type: "button", class: "st-mini", "aria-label": `هایلایت ${t.title || ""}`, onclick: () => leave(t) },
        src ? h("img", { src, alt: "", loading: "lazy", decoding: "async" }) : null,
        h("span", { class: "st-mini-in" }, avatar({ u, src: S.av, size: 56, zoom: false }), h("bdi", { class: "st-mini-t", text: t.title || "" }))); };
    mount(before, k < 0 ? null : S.tray.slice(Math.max(0, k - 2), k).map(mini)); mount(after, k < 0 ? null : S.tray.slice(k + 1, k + 3).map(mini));
  }
  const picture = (src, fit, it) => (src
    ? h("img", { class: ["st-img", fit], src, alt: it.alt || it.caption || "", decoding: "async", draggable: "false",
      onload: () => { S.ready = true; }, onerror: (e) => { S.ready = true; e.currentTarget.replaceWith(picture(null, fit, it)); } })
    : (S.ready = true) && h("div", { class: "st-none" }, ic(it.type === "video" ? "film" : "image", "lg"),
      h("p", { text: "عکس این آیتم ذخیره نشده و لینکش منقضی شده؛ دوباره بخوانش." })));

  function show(i) {
    const it = S.items[i]; if (!it) return;
    S.i = i; S.spent = 0; S.ready = false; S.want = null; S.video?.pause(); S.video = null;
    [...bars.children].forEach((b, k) => { b.firstChild.style.transform = `scaleX(${k < i ? 1 : 0})`; });
    const m = pick(it), fit = it.width && it.height && Math.abs(it.width / it.height - 9 / 16) < 0.09 ? "st-cover" : "st-fit";
    if (m.kind === "video") {
      const v = h("video", { class: ["st-img", fit], src: m.src, poster: m.still, playsinline: true, preload: "auto",
        onloadeddata: () => { S.ready = true; }, onended: () => step(1),
        onerror: () => { if (S.video === v) { S.video = null; muteB.hidden = true; v.replaceWith(picture(m.still, fit, it)); } } });
      v.muted = S.muted; S.video = v; mount(box, v);
    } else mount(box, picture(m.src, fit, it));
    mount(who, avatar({ u, src: S.av, size: 32 }), h("a", { class: "st-user", href: `#/u/${u}` }, ltr(u)),
      S.title ? h("bdi", { class: "st-title", text: S.title }) : null, it.taken_at ? h("span", { class: "st-ago", text: ago(it.taken_at) }) : null);
    mount(over, it.caption ? h("p", { class: "st-cap", dir: "auto", text: it.caption }) : null, h("div", { class: "st-tags" }, chips(it, m)));
    placeSpot(it);
    where.textContent = `آیتم ${faNum(i + 1)} از ${faNum(S.items.length)}`;
    prevB.hidden = i === 0 && !near(-1); muteB.hidden = !S.video;
    const nx = S.items[i + 1] && pick(S.items[i + 1]); if (nx?.kind === "image" && nx.src) h("img", { src: nx.src });   // warm the next one
    sync();
  }

  function chips(it, m) {
    const tag = (name, label, href) => { const ext = /^https?:/.test(href || "");
      return h(href ? "a" : "span", { class: "chip chip-dark st-tag", href, target: ext ? "_blank" : null, rel: ext ? "noopener noreferrer" : null }, ic(name, "sm"), h("span", null, label)); };
    const out = [];
    for (const l of it.links || []) { const url = txt(l, "url", "href"); if (/^https?:\/\//i.test(url)) out.push(tag("link", ltr(txt(l, "title", "text") || host(url)), url)); }
    for (const x of it.mentions || []) { const n = txt(x, "username", "name").replace(/^@/, ""); if (n) out.push(tag("at", ltr(n), `#/u/${n.toLowerCase()}`)); }
    for (const x of it.hashtags || []) { const n = txt(x, "name", "tag").replace(/^#/, ""); if (n) out.push(tag("hash", bdi(n), igUrl(`/explore/tags/${encodeURIComponent(n)}/`))); }
    for (const x of it.places || []) { const n = txt(x, "name", "title"), id = x?.id || x?.pk; if (n) out.push(tag("pin-map", bdi(n), id ? igUrl(`/explore/locations/${id}/`) : null)); }
    if (it.music?.title) out.push(tag("music", ["آهنگ: ", bdi(it.music.title), it.music.artist ? [" از ", bdi(it.music.artist)] : null]));
    for (const x of it.stickers || []) { const [label, name] = STICKER[txt(x, "kind", "type")] || ["استیکر", "tag"], q = typeof x === "object" ? txt(x, "question", "text", "title") : ""; out.push(tag(name, [label, q ? [": ", bdi(q)] : null])); }
    if (it.shared_post) out.push(h("button", { type: "button", class: "chip chip-dark st-tag", onclick: () => goPost(it.shared_post) }, ic("image", "sm"), h("span", null, "مشاهدهٔ پست")));
    if (m.cover) out.push(tag("film", "فقط عکس جلد این ویدیو ذخیره شده"));
    return out;
  }

  // A shared post: our own copy when any saved page has it, else Instagram in a new tab.
  async function goPost(code) {
    if ((S.d?.posts?.items || []).some((p) => p.code === code)) return ctx.navigate(`/u/${u}/p/${code}`);
    const r = await api(`/api/find-post/${encodeURIComponent(code)}`).catch(() => null);
    if (r?.ok) return ctx.navigate(`/u/${r.data.username}/p/${code}`);
    window.open(igUrl(`/p/${code}/`), "_blank", "noopener");
  }
  function closeBubble() { if (!S.bubble) return; S.bubble.remove(); S.bubble = null; S.held = false; }
  function placeSpot(it) {
    closeBubble();
    spot.hidden = !it.shared_post;
    if (!it.shared_post) return;
    const b = it.shared_box || { x: 0.5, y: 0.5, width: 0.62, height: 0.42, rotation: 0 };   // older reads have no position
    spot.style.cssText = `left:${(b.x - b.width / 2) * 100}%;top:${(b.y - b.height / 2) * 100}%;width:${b.width * 100}%;height:${b.height * 100}%;transform:rotate(${b.rotation || 0}deg)`;
    spot.onclick = (e) => {
      e.stopPropagation();
      if (S.bubble) return closeBubble();
      S.held = true;
      S.bubble = h("div", { class: "st-bubble" }, h("button", { type: "button", class: "st-bubble-btn", onclick: (ev) => { ev.stopPropagation(); closeBubble(); goPost(it.shared_post); } },
        ic("image", "sm"), h("span", null, "مشاهدهٔ پست")));
      spot.append(S.bubble);
      enter(S.bubble, "pop");
    };
  }

  function downloads() {
    const scope = hl ? { target: "highlights", ids: [hl] } : { target: "story" }, total = S.reel.items_total || 0;
    const dl = (label, kind, extra) => { const b = button({ label, kind, onClick: async () => {
      await startJob("download", { username: u, videos: true, ...scope, ...extra() }, { lines: cost("download") }); relock(); } }); b.prepend(ic("download", "sm")); return b; };
    mount(bar, h("div", { class: "st-dl" }, dl("دانلود این آیتم", "primary", () => ({ items: [S.items[S.i]?.id] })), dl(hl ? "دانلود کل هایلایت" : "دانلود کل استوری", "secondary", () => ({}))),
      total > S.items.length ? h("p", { class: "st-count" }, bdi(faNum(S.items.length)), " از ", bdi(faNum(total)), " آیتم خوانده شده") : null,
      h("p", { class: "st-note", text: "این نسخهٔ ذخیره‌شده است؛ اینستاگرام از دیدنش خبردار نمی‌شود." }));
  }

  function sync() { setBtn(pauseB, S.paused ? "play" : "pause", S.paused ? "پخش" : "توقف"); setBtn(muteB, S.muted ? "volume-x" : "volume", S.muted ? "صدادار" : "بی‌صدا"); }

  // One clock for the bars: pictures count 5s while shown and not held; videos report their own time.
  function tick(now) {
    S.raf = requestAnimationFrame(tick);
    const fill = bars.children[S.i]?.firstChild, v = S.video, dt = Math.min(100, now - (S.last || now)); S.last = now;
    if (!fill || S.leaving) return;
    const run = !S.paused && !S.held && !covered() && !document.hidden;
    if (v && run !== S.want) { S.want = run; if (!run) v.pause(); else v.play().catch((e) => {   // sound needs a gesture: fall back to muted
      if (e.name === "NotAllowedError" && !v.muted) { S.muted = v.muted = true; sync(); v.play().catch(() => {}); } }); }
    if (!v && run && S.ready) S.spent += dt;
    const p = v ? (v.duration ? v.currentTime / v.duration : 0) : S.spent / IMAGE_MS;
    fill.style.transform = `scaleX(${Math.min(1, p)})`;
    if (!v && p >= 1) step(1);
  }
  function step(dir) {
    if (S.leaving || !S.items.length) return;
    const n = S.i + dir;
    if (n < 0) return near(-1) ? leave(near(-1)) : show(0);
    return n >= S.items.length ? leave(near(1)) : show(n);
  }
  function big() {
    const list = S.items.map((it) => { const m = pick(it); return { kind: m.kind, src: m.src || m.still, poster: m.still || undefined, title: `@${u}`, sub: S.title || ago(it.taken_at), caption: it.caption || "" }; });
    const ok = list.filter((x) => x.src); if (ok.length) gallery(ok, Math.max(0, ok.indexOf(list[S.i])));
  }

  // Tap: the inline-start third goes back (the right third in RTL), the rest goes on. Hold pauses, a pull down closes.
  let down = null, holdT = 0;
  const release = () => { clearTimeout(holdT); S.held = false; layer.removeAttribute("data-hold"); frame.classList.remove("st-drag"); frame.style.transform = ""; };
  offs.push(on(hit, "pointerdown", (e) => { if (e.button) return; down = { x: e.clientX, y: e.clientY, moved: false }; hit.setPointerCapture?.(e.pointerId);
    holdT = setTimeout(() => { S.held = true; layer.setAttribute("data-hold", ""); }, HOLD_MS); }));
  offs.push(on(hit, "pointermove", (e) => { const dy = down ? e.clientY - down.y : 0;
    if (!down || (!down.moved && Math.hypot(e.clientX - down.x, dy) < 10)) return; down.moved = true; clearTimeout(holdT); S.held = true;
    if (dy > 0) { frame.classList.add("st-drag"); frame.style.transform = `translateY(${dy}px) scale(${Math.max(0.85, 1 - dy / 1500)})`; } }));
  offs.push(on(hit, "pointerup", (e) => { if (S.bubble) { down = null; clearTimeout(holdT); closeBubble(); return; } const d = down, held = S.held; down = null;
    if (d?.moved && e.clientY - d.y > 110) return leave(); release(); if (!d || held || d.moved) return;
    const r = hit.getBoundingClientRect(), fromStart = rtl() ? r.right - e.clientX : e.clientX - r.left; step(fromStart < r.width / 3 ? -1 : 1); }));
  offs.push(on(hit, "pointercancel", () => { down = null; release(); }));
  offs.push(on(document, "keydown", (e) => {
    if (e.defaultPrevented || covered() || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Escape") { e.preventDefault(); leave(); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); step((e.key === "ArrowLeft") === rtl() ? 1 : -1); }
    else if (e.key === " " && !e.target.closest?.("button, a")) { e.preventDefault(); pauseB.click(); }
  }));
  offs.push(subscribe("job-end", (s) => { if ((s.result?.profile?.username || s.username || "").toLowerCase() === u) load(true); }));

  function close() {
    if (S.closed) return; S.closed = true; lastClose = Date.now(); layer.classList.add("st-gone");
    cancelAnimationFrame(S.raf); clearTimeout(holdT); offs.forEach((off) => off()); S.video?.pause();
    const alone = !document.querySelector(".st-layer:not(.st-gone)");
    if (alone && !document.querySelector(".ov-layer")) document.documentElement.removeAttribute("data-overlay");
    if (alone && from?.focus && document.contains(from)) from.focus({ preventScroll: true });
    exit(layer, "fade").then(() => layer.remove());
  }

  document.body.append(layer); relock(); layer.focus({ preventScroll: true });
  if (Date.now() - lastClose > 600) {   // a fresh open grows out of the ring that was pressed; a hop between highlights swaps in place
    const r = from && from !== document.body ? from.getBoundingClientRect() : null, f = frame.getBoundingClientRect(); enter(layer, "fade");
    if (r?.width && r.width < 240 && f.width) animate(frame, [{ opacity: 0, transform: `translate(${r.left + r.width / 2 - f.left - f.width / 2}px, ${r.top + r.height / 2 - f.top - f.height / 2}px) scale(${r.width / f.width})` }, { opacity: 1, transform: "none" }], { dur: DUR.enter });
    else enter(frame, "scale");
  }
  S.raf = requestAnimationFrame(tick); load();
  return { close };
}
