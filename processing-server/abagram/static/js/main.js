// Boot: the shell, the routes, and which view shows where (page column, drawer panel, overlays on top).
import { h, mount } from "./core/dom.js";
import { route, start, navigate, back, currentRoute } from "./core/router.js";
import { subscribe, startPolling, stopPolling, pref, state } from "./core/store.js";
import { enter } from "./core/motion.js";
import { authMe } from "./core/api.js";
import "./core/zoom.js";
import { startNotify } from "./views/notify.js";   // every picture marked data-zoom opens in the image viewer

const app = document.getElementById("app");
const modules = {};
let shell = null;
let page = { name: null, key: null, inst: null, path: "/" };
let drawer = { name: null, inst: null };
let overlays = [];          // stack of {key, inst}

async function load(name) {
  if (!modules[name]) modules[name] = import(`./views/${name}.js`).catch((e) => { console.error(name, e); return null; });
  return modules[name];
}

const missing = (name) => h("div", { class: "missing", style: "padding:48px 16px;text-align:center;color:var(--text-2)" }, `بخش «${name}» در دست ساخت است.`);

function parentPath(r) {
  if (r.params?.name) return `/u/${r.params.name}`;
  return page.path || "/";
}

const ctx = {
  navigate, back,
  dismiss: () => back(parentPath(currentRoute())),
  get shell() { return shell; },
};

async function showPage(name, params, key, path) {
  page.path = path;
  if (page.name === name && page.key === key) { page.inst?.update?.(params); return; }
  if (page.name === name && page.inst?.update) {
    page.key = key;
    page.inst.update(params);
    return;
  }
  page.inst?.destroy?.();
  const mod = await load(name);
  const inst = mod?.render ? mod.render(params, ctx) : { el: missing(name) };
  page = { name, key, inst, path };
  mount(shell.main, inst.el);
  shell.setActive(name);
  window.scrollTo({ top: 0 });
  enter(inst.el, "rise");          // the next page arrives instead of cutting in
}

async function showDrawer(name, params) {
  if (drawer.name === name) return;
  drawer.inst?.destroy?.();
  drawer = { name: null, inst: null };
  if (!name) { shell.showDrawer(null); return; }
  const mod = await load(name);
  const inst = mod?.render ? mod.render(params, ctx) : { el: missing(name) };
  drawer = { name, inst };
  shell.showDrawer(inst.el);
  shell.setActive(name);
}

/** wanted: [{key, view, params}] bottom → top. Closes what is not wanted, opens what is missing.
 * The same view at the same depth with other params (the next post) is updated in place when it can. */
async function showOverlays(wanted) {
  wanted.forEach((w, i) => {
    const o = overlays[i];
    if (o && o.key !== w.key && o.view === w.view && o.inst?.update && i === overlays.length - 1) {
      o.inst.update(w.params);
      o.key = w.key;
    }
  });
  while (overlays.length && !wanted.some((w) => w.key === overlays[overlays.length - 1].key)) {
    overlays.pop().inst?.close?.();
  }
  overlays = overlays.filter((o) => wanted.some((w) => w.key === o.key));
  for (const w of wanted) {
    if (overlays.some((o) => o.key === w.key)) continue;
    const mod = await load(w.view);
    if (!mod?.open) continue;
    overlays.push({ key: w.key, view: w.view, inst: mod.open(w.params, ctx) });
  }
}

async function profileWith(params, wanted = []) {
  await showDrawer(null);
  load("search").then((m) => m?.remember?.({ username: params.name }));   // «اخیر» in search = profiles opened from anywhere
  // An overlay route keeps the tab that is showing (tab undefined); a new profile starts on its posts.
  const same = page.key === `profile:${params.name}`;
  const tab = params.tab || (same ? undefined : "posts");
  const path = same && !params.tab ? page.path : `/u/${params.name}${tab && tab !== "posts" ? `/${tab}` : ""}`;
  await showPage("profile", { name: params.name, tab }, `profile:${params.name}`, path);
  await showOverlays(wanted);
}

async function plain(name, params, key, path) {
  await showOverlays([]);
  await showDrawer(null);
  await showPage(name, params, key, path);
}

function routes() {
  route("home", "/", () => plain("home", {}, "home", "/"));
  route("login", "/login", () => plain("login", {}, "login", "/login"));
  route("settings", "/settings", () => plain("settings", { section: null }, "settings", "/settings"));
  route("monitors", "/monitors", () => plain("monitors", {}, "monitors", "/monitors"));
  route("monitoring", "/monitoring", () => plain("monitoring", {}, "monitoring", "/monitoring"));
  route("process", "/process", () => plain("process", {}, "process", "/process"));
  route("exchange", "/exchange", () => plain("exchange", {}, "exchange", "/exchange"));   // «تبادلِ JSON»
  route("settings-section", "/settings/:section", (p) => plain("settings", p, "settings", `/settings/${p.section}`));
  const drawerRoute = async (name) => {
    await showOverlays([]);
    if (!page.name) await showPage("home", {}, "home", "/");
    await showDrawer(name, {});
  };
  route("search", "/search", () => drawerRoute("search"));
  route("activity", "/activity", () => plain("activity", {}, "activity", "/activity"));   // a page in the middle, no longer a drawer
  route("profile", "/u/:name", (p) => profileWith({ name: p.name, tab: "posts" }));
  route("profile-reels", "/u/:name/reels", (p) => profileWith({ name: p.name, tab: "reels" }));
  route("profile-about", "/u/:name/about", (p) => profileWith({ name: p.name, tab: "about" }));
  const post = (p) => ({ key: `post:${p.name}:${p.code}`, view: "post", params: { name: p.name, code: p.code } });
  route("post", "/u/:name/p/:code", (p) => profileWith(p, [post(p)]));
  route("likers", "/u/:name/p/:code/likers", (p) => profileWith(p, [post(p), { key: `likers:${p.code}`, view: "people", params: { u: p.name, kind: "likers", code: p.code } }]));
  route("stories", "/u/:name/stories", (p) => profileWith(p, [{ key: `story:${p.name}`, view: "stories", params: { name: p.name } }]));
  route("highlight", "/u/:name/hl/:id", (p) => profileWith(p, [{ key: `hl:${p.name}:${p.id}`, view: "stories", params: { name: p.name, id: p.id } }]));
  route("followers", "/u/:name/followers", (p) => profileWith(p, [{ key: `followers:${p.name}`, view: "people", params: { u: p.name, kind: "followers" } }]));
  route("following", "/u/:name/following", (p) => profileWith(p, [{ key: `following:${p.name}`, view: "people", params: { u: p.name, kind: "following" } }]));
}

function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}

// The site's own door (views/gate.js): before anything loads, and again when a login runs out mid-way. A login reloads
// the page, so everything starts clean behind the door.
let gated = false;
async function showGate(expired) {
  if (gated) return;
  gated = true;
  stopPolling();
  shell?.destroy?.();
  const mod = await load("gate");
  if (!mod?.render) { mount(app, missing("ورود")); return; }
  const gate = mod.render({ expired, onIn: () => location.reload() });
  mount(app, gate.el);
  document.title = "ورود به آباگرام";
  enter(gate.el.querySelector(".lg-col"), "rise");
  gate.focus();
}

/** null: show the door. A server that does not answer at all boots the site as before (it says «not reachable»). */
async function whoAmI() {
  try {
    const r = await authMe();
    return r.ok ? r.data?.me || null : r.status === 401 ? null : undefined;
  } catch {
    return undefined;
  }
}

async function boot() {
  applyTheme(pref("theme"));
  subscribe("settings", ({ key, value }) => { if (key === "theme") applyTheme(value); });
  window.addEventListener("igs:login", () => showGate(true));
  const me = await whoAmI();
  if (me === null) return showGate(false);
  state.me = me || null;
  if (me?.role === "json") {     // «فقط JSON»: the pages and their JSON, nothing else (no Instagram, no queue, no polling)
    const mod = await load("exchange");
    mount(app, mod?.renderStandalone ? mod.renderStandalone(me).el : missing("تبادلِ JSON"));
    return;
  }
  const mod = await load("shell");
  shell = mod?.renderShell ? mod.renderShell(app) : (() => {
    const main = h("main", { id: "main" });
    const slot = h("aside", { class: "drawer-fallback" });
    mount(app, slot, main);
    return { main, setActive() {}, showDrawer: (el) => mount(slot, el) };
  })();
  routes();
  startNotify();
  startPolling();
  start();
}

boot();
