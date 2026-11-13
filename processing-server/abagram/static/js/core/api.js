// Talking to the local server (app.py). Never throws on HTTP errors; throws only when the server is unreachable.
import { proxied } from "./dom.js";

export { proxied };
export async function api(path, body, { method } = {}) {
  const opts = { method: method || (body === undefined ? "GET" : "POST"), headers: { "X-Igs": "1" } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  let data = null;
  try { data = await r.json(); } catch { data = null; }
  if (r.status === 401 && !path.startsWith("/api/auth/")) loggedOut();
  return { ok: r.ok, status: r.status, data };
}

// The site's own login ended (a day passed, or the admin removed the person): main.js shows the door again.
const loggedOut = () => window.dispatchEvent(new CustomEvent("igs:login"));

const enc = encodeURIComponent;

// ---- the site's own login (an AbaOne account the admin added) and «تبادلِ JSON» ----
export const authMe = () => api("/api/auth/me");
export const authLogin = (username, password) => api("/api/auth/login", { username, password });
export const authLogout = () => api("/api/auth/logout", {});
export const getUsers = () => api("/api/auth/users");
export const saveUser = (username, role) => api("/api/auth/users", { username, role });
export const removeUser = (username) => api(`/api/auth/users/${enc(username)}/remove`, {});
export const getExchange = () => api("/api/exchange");
export const exportUrl = (u) => `/api/export/${enc(u)}`;

/** One page's JSON file up to the server, with upload progress (fetch has none): resolves {ok, status, data}. */
export function importFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", "/api/import");
    x.setRequestHeader("X-Igs", "1");
    x.setRequestHeader("Content-Type", "application/json");
    x.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total); };
    x.upload.onload = () => onProgress?.(1);
    x.onload = () => {
      let data = null;
      try { data = JSON.parse(x.responseText); } catch { data = null; }
      if (x.status === 401) loggedOut();
      resolve({ ok: x.status >= 200 && x.status < 300, status: x.status, data });
    };
    x.onerror = () => reject(new Error("network"));
    x.send(file);
  });
}

export const getDossier = (u) => api(`/api/dossier/${enc(u)}`);
export const getFiles = (u) => api(`/api/files/${enc(u)}`);
export const getPeople = (u, which) => api(`/api/people/${enc(u)}/${enc(which)}`);   // a whole list (the dossier has only its head)
export const harvestList = (username, which, force) => api("/api/harvest", { username, which, ...(force ? { force: true } : {}) });
export const getMonitors = () => api("/api/monitors");
export const addMonitor = (username, harvest = true, force) => api("/api/monitors", { username, harvest, ...(force ? { force: true } : {}) });
export const monitorAct = (username, action, ids) => api(`/api/monitors/${enc(username)}/${enc(action)}`, ids ? { ids } : {});
export const getAccounts = () => api("/api/accounts");
export const addAccount = (username) => api("/api/accounts", { username });
export const accountAct = (username, action) => api(`/api/accounts/${enc(username)}/${enc(action)}`, {});
export const getHealth = () => api("/api/health");
export const getProcessLists = () => api("/api/process");                       // «پردازش»: saved lists + default words
export const getProcess = (u, which) => api(`/api/process/${enc(u)}/${enc(which)}`);
export const processAct = (u, which, action, words) => api(`/api/process/${enc(u)}/${enc(which)}/${enc(action)}`, words ? { words } : {});
const qs = (params) => new URLSearchParams(Object.entries(params || {}).filter(([, v]) => v !== "" && v !== null && v !== undefined && v !== false)).toString();
export const getProcessPage = (u, which, params) => api(`/api/process/${enc(u)}/${enc(which)}?${qs(params)}`);   // a page of results
export const processRank = (u, which, words, min_score) => api(`/api/process/${enc(u)}/${enc(which)}/rank`, { words, min_score });
export const processLabel = (u, which, username, label) => api(`/api/process/${enc(u)}/${enc(which)}/label`, { username, label });
export const processExportUrl = (u, which, params) => `/api/process/${enc(u)}/${enc(which)}/export.xlsx?${qs(params)}`;
export const testConnection = (proxy) => api("/api/health/test", proxy !== undefined ? { proxy } : {});
export const getVpn = () => api("/api/vpn");                                   // the office VPN gateway's view of this computer
export const setVpnCountry = (country) => api("/api/vpn/country", { country });  // "" = Auto
export const vpnLogin = (username, password) => api("/api/vpn/login", { username, password });
export const getExitIp = () => api("/api/vpn/ip");
export const getPrefs = () => api("/api/prefs");
export const setPrefs = (values) => api("/api/prefs", { values });
export const getProfiles = (offset = 0, limit = 5) => api(`/api/profiles?offset=${offset}&limit=${limit}`);
export const getLimits = () => api("/api/limits");
export const setLimits = (values) => api("/api/limits", { values });
export const resetLimits = () => api("/api/limits/reset", {});
export const clearCooldown = () => api("/api/cooldown/clear", {});
export const submitCode = (code) => api("/api/code", { code });
export const cancelJob = () => api("/api/cancel", {});
export const clearSession = () => api("/api/session/clear", {});
export const forgetProfile = (username) => api("/api/forget", { username });

export const avatarUrl = (u, stamp = "") => `/api/avatar/${enc(u)}?v=${enc(stamp || "")}`;
export const thumbUrl = (u, key, stamp = "") => `/api/media/${enc(u)}/${enc(key)}?v=${enc(stamp || "")}`;
export const fileUrl = (u, key) => `/api/file/${enc(u)}/${enc(key)}`;
export const shotUrl = (n) => `/api/shot?n=${enc(n ?? "")}`;
export const runPictureUrl = (id) => `/api/runs/${enc(id)}/picture`;   // a finished run's own last picture of its window
export const igUrl = (path = "/") => `https://www.instagram.com${path.startsWith("/") ? path : `/${path}`}`;

// Instagram's picture/video addresses stop working at their `oe` time (hex seconds).
export function alive(url) {
  if (!url || !/^https:\/\//.test(url)) return false;
  try {
    const oe = new URL(url).searchParams.get("oe");
    return !oe || parseInt(oe, 16) * 1000 > Date.now();
  } catch {
    return false;
  }
}

/**
 * The best source to show: a downloaded file, else a still-valid Instagram address, else the saved thumbnail.
 * files = the `files` map of getFiles(u).data (may be null).
 */
export function media(u, { fileKey, remote, thumbKey, thumbStamp, files, video = false } = {}) {
  if (fileKey && files && files[fileKey]) return { src: fileUrl(u, fileKey), kind: "file", type: files[fileKey].type };
  if (remote && alive(remote)) return { src: proxied(remote, video ? "vid" : "img"), kind: "remote" };
  if (thumbKey) return { src: thumbUrl(u, thumbKey, thumbStamp), kind: "thumb" };
  return { src: null, kind: null };
}

// Profile names: the same rule as the server (letters, digits, dot, underscore; up to 30).
const RESERVED = new Set(["p", "reel", "reels", "stories", "explore", "accounts", "direct", "tv", "web", "about", "legal", "api"]);

export function cleanUsername(raw) {
  let s = String(raw || "").trim();
  const m = s.match(/^(?:https?:\/\/)?(?:www\.)?instagram\.com\/([^/?#\s]+)/i);
  if (m) s = m[1];
  s = s.replace(/^@/, "").trim().replace(/^\/+|\/+$/g, "");
  return /^[A-Za-z0-9._]{1,30}$/.test(s) && !RESERVED.has(s.toLowerCase()) ? s.toLowerCase() : null;
}

export const isPostLink = (raw) => /instagram\.com\/(p|reel|reels|tv|stories)\//i.test(String(raw || ""));
