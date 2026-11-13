// Hash routes: deep links and the back button work everywhere.
// Entries we push carry {depth}; back() uses history.back() only while it stays inside the app.
import { emit } from "./store.js";

const routes = [];
let current = { name: null, path: "/", params: {} };

function compile(pattern) {
  const keys = [];
  const re = new RegExp("^" + pattern.replace(/\/:([a-z]+)/gi, (_, k) => { keys.push(k); return "/([^/]+)"; }) + "/?$");
  return { re, keys };
}

export function route(name, pattern, handler) {
  routes.push({ name, handler, ...compile(pattern) });
}

function resolve() {
  const path = decodeURIComponent(location.hash.replace(/^#/, "")) || "/";
  for (const r of routes) {
    const m = path.match(r.re);
    if (!m) continue;
    const params = Object.fromEntries(r.keys.map((k, i) => [k, m[i + 1]]));
    current = { name: r.name, path, params };
    r.handler(params, current);
    emit("route", current);
    return;
  }
  navigate("/", { replace: true });
}

const depth = () => (history.state && history.state.depth) || 0;

export function navigate(path, { replace = false } = {}) {
  const hash = `#${path}`;
  if (replace) history.replaceState({ depth: depth() }, "", hash);
  else if (location.hash !== hash) history.pushState({ depth: depth() + 1 }, "", hash);
  resolve();
}

export function back(fallback = "/") {
  if (depth() > 0) history.back();
  else navigate(fallback, { replace: true });
}

export const currentRoute = () => current;

export function start() {
  window.addEventListener("popstate", resolve);
  // A hash typed by hand (or a plain link) has no state yet; entries we pushed are handled by popstate.
  window.addEventListener("hashchange", () => {
    if (history.state) return;
    history.replaceState({ depth: 0 }, "", location.hash);
    resolve();
  });
  // In-app links (<a href="#/…">) go through navigate() so they get a depth and back() works.
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest('a[href^="#/"]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || a.target) return;
    e.preventDefault();
    navigate(a.getAttribute("href").slice(1));
  });
  if (!history.state) history.replaceState({ depth: 0 }, "", location.hash || "#/");
  resolve();
}
