// App state, events and the one poller of /api/status. Views subscribe; nothing else polls.
import { api, getDossier, getFiles } from "./api.js";

export const state = { status: null, log: [], online: true, settings: {}, me: null };   // me: who logged in to the site (ig_auth)

const topics = new Map();

export function subscribe(topic, fn) {
  if (!topics.has(topic)) topics.set(topic, new Set());
  topics.get(topic).add(fn);
  return () => topics.get(topic)?.delete(fn);
}

export function emit(topic, payload) {
  for (const fn of [...(topics.get(topic) || [])]) {
    try { fn(payload); } catch (e) { console.error(topic, e); }
  }
}

export function pref(key, value) {
  const full = `aine.${key}`;
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(full) ?? "null");
    if (value === null) localStorage.removeItem(full);
    else localStorage.setItem(full, JSON.stringify(value));
  } catch { /* private mode or blocked storage: keep going without it */ }
  if (value !== undefined) emit("settings", { key, value });
  return value;
}

// ---- saved data, cached per person ----
const dossiers = new Map();
const fileLists = new Map();

function cached(map, u, load, topic, force) {
  const key = String(u).toLowerCase();
  if (!force && map.has(key)) return map.get(key);
  const p = load(key).then((r) => {
    const data = r.ok ? r.data : null;
    emit(`${topic}:${key}`, data);
    return data;
  }).catch(() => {
    map.delete(key);
    return null;
  });
  map.set(key, p);
  return p;
}

export const dossier = (u, { force = false } = {}) => cached(dossiers, u, getDossier, "dossier", force);
export const files = (u, { force = false } = {}) => cached(fileLists, u, getFiles, "files", force);

export function invalidate(u) {
  if (!u) return;
  const key = String(u).toLowerCase();
  dossiers.delete(key);
  fileLists.delete(key);
}

// ---- polling ----
let cursor = 0;
let timer = 0;
let lastRun = null;
let wasBusy = false;

let stopped = false;   // the login screen took over: no more asking until the page starts again

async function poll() {
  clearTimeout(timer);
  if (stopped) return;
  let again = false;
  try {
    const r = await api(`/api/status?since=${cursor}`);
    if (!state.online) emit("online", (state.online = true));
    if (r.ok) again = apply(r.data);
  } catch {
    if (state.online) emit("online", (state.online = false));
  }
  const busy = state.status?.busy;
  timer = setTimeout(poll, again ? 0 : busy ? 700 : 2500);
}

let newRun = false;

function apply(s) {
  if (s.run !== lastRun) {
    const first = lastRun === null;
    lastRun = s.run;
    state.log = [];
    newRun = !first;
    if (cursor !== 0) { cursor = 0; return true; }     // a new run started mid-cursor: read its log from the start
  }
  state.log.push(...s.log);
  cursor = s.next;
  state.status = s;
  const started = newRun;
  newRun = false;
  if (started) emit("job-start", s);
  if (s.log.length) emit("log", s.log);
  emit("status", s);
  if ((wasBusy || started) && !s.busy) {               // a quick job may start and end between two polls
    const u = s.result?.profile?.username || s.username;
    invalidate(u);
    emit("job-end", s);
  }
  wasBusy = !!s.busy;
  return false;
}

export function startPolling() { stopped = false; poll(); }
export function pokePolling() { poll(); }
export function stopPolling() { stopped = true; clearTimeout(timer); }
