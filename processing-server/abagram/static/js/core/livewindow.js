// Instagram's page of a login that waits for him, when Chromium has no window (the server). The page is shown here, live:
// a big window opens by itself when Instagram asks for something (captcha, "was this you", a code); a click on the picture is a
// click on the page, the wheel scrolls it, and what he types while the picture has focus is typed there.
import { h } from "./dom.js";
import { api } from "./api.js";
import { state } from "./store.js";
import { dialog } from "./overlay.js";
import { button, setBusy } from "./ui.js";

const EVERY = 1000;
const KEYS = new Set(["Enter", "Backspace", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"]);
const views = new Set();          // every <img> that shows the page; one shared refresh feeds them all
const cards = new Set();          // the small boxes inside the login / activity cards
let timer = 0, url = "", polling = false, again = false, misses = 0, big = null, autoRun = null, lastState = null;
let chain = Promise.resolve();

const send = (body) => (chain = chain.then(() => api("/api/window", body)).catch(() => null).then(() => poll()));

async function poll() {
  if (polling) { again = true; return; }
  clearTimeout(timer);
  for (const img of views) { if (img.isConnected) img.dataset.seen = "1"; else if (img.dataset.seen) views.delete(img); }
  if (!views.size) return;
  polling = true;
  let ok = false;
  try {
    const r = await fetch("/api/window", { cache: "no-store" });
    if (r.ok) {
      const next = URL.createObjectURL(await r.blob()), old = url;
      url = next; ok = true;
      for (const img of views) img.src = next;
      if (old) setTimeout(() => URL.revokeObjectURL(old), 3000);
    }
  } catch { /* the server is restarting: try again on the next round */ }
  polling = false;
  shown(ok);
  timer = setTimeout(poll, again ? 50 : EVERY);
  again = false;
}

function shown(ok) {
  misses = ok ? 0 : misses + 1;
  const st = state.status?.state;
  if (st !== lastState) { if (st === "need_manual") autoRun = null; lastState = st; }   // a new request from Instagram: open again
  if (st === "need_code") { if (big) big.close(); return; }   // the site's own code box takes over
  for (const card of cards) card.classList.toggle("lw-on", ok || (misses < 3 && card.classList.contains("lw-on")));
  if (ok && !big && autoRun !== state.status?.run && [...cards].some((c) => c.isConnected)) {
    autoRun = state.status?.run;
    openBig();
  }
  if (big && misses >= 3) big.close();      // Instagram moved on (logged in, or the run ended): the window is not needed any more
}

/** Clicks, wheel and keys on `pic` go to Instagram's page; x, y are fractions of the picture. */
function control(pic, img) {
  let buf = "", flushAt = 0, dy = 0, wheelAt = 0;
  const flush = () => { clearTimeout(flushAt); if (buf) { send({ text: buf }); buf = ""; } };
  pic.addEventListener("click", (e) => {
    const r = img.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    if (r.width && x >= 0 && x <= 1 && y >= 0 && y <= 1) { flush(); send({ x, y }); }
    pic.focus({ preventScroll: true });
  });
  pic.addEventListener("wheel", (e) => {
    e.preventDefault();
    dy += e.deltaY; clearTimeout(wheelAt);
    wheelAt = setTimeout(() => { const d = Math.max(-2000, Math.min(2000, dy)); dy = 0; send({ dy: d }); }, 150);
  }, { passive: false });
  pic.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key.length === 1) { e.preventDefault(); buf += e.key; clearTimeout(flushAt); flushAt = setTimeout(flush, 150); }
    else if (KEYS.has(e.key)) { e.preventDefault(); flush(); send({ key: e.key }); }
  });
}

function picture(cls) {
  const img = h("img", { class: "lw-img", alt: "صفحهٔ اینستاگرام روی سرور", draggable: "false" });
  const pic = h("div", { class: ["lw-pic", cls], tabindex: "0", role: "application",
    "aria-label": "صفحهٔ اینستاگرام روی سرور؛ کلیک و تایپ تو مستقیم به همین صفحه می‌رود" }, img);
  if (url) img.src = url;
  control(pic, img);
  views.add(img);
  return pic;
}

/** The box under the picture: for longer text (a code) and the two keys people look for. */
function typeBox() {
  const input = h("input", { type: "text", class: "lw-in", dir: "ltr", autocomplete: "off", spellcheck: "false",
    "aria-label": "متنی که در صفحه تایپ شود", placeholder: "مثلاً کد تأیید" });
  const go = button({ label: "تایپ در صفحه", kind: "secondary", onClick: () => {
    if (!input.value) return input.focus();
    setBusy(go, true);
    send({ text: input.value }).then(() => { input.value = ""; setBusy(go, false); });
  } });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go.click(); } });
  return h("div", { class: "lw-tools" }, h("div", { class: "lw-type" }, input, go), h("div", { class: "lw-keys" },
    button({ label: "Enter", kind: "ghost", size: "sm", onClick: () => send({ key: "Enter" }) }),
    button({ label: "پاک کردن یک حرف", kind: "ghost", size: "sm", onClick: () => send({ key: "Backspace" }) })));
}

export function openBig() {
  if (big) return;
  const pic = picture("lw-pic-big");
  big = dialog({ title: "صفحهٔ اینستاگرام", size: "lg", cls: "lw-dlg",
    content: [h("p", { class: "lw-hint", text: "همان صفحه‌ای است که روی سرور باز است. هر جا لازم است کلیک کن (مثلاً «I'm not a robot» و عکس‌ها)، با چرخ ماوس بالا و پایین برو، و وقتی خانه‌ای را زدی همین‌جا تایپ کن." }),
      pic, typeBox()],
    onClose: () => { big = null; } });
  setTimeout(() => pic.focus({ preventScroll: true }), 250);
  poll();
}

/** For a "do it in the window" card: a small live preview and a button for the big window. */
export function liveWindow() {
  const el = h("div", { class: "lw" }, picture("lw-pic-small"),
    button({ label: "باز کردن صفحهٔ اینستاگرام", kind: "primary", full: true, onClick: openBig }));
  cards.add(el);
  setTimeout(poll, 0);
  return el;
}
