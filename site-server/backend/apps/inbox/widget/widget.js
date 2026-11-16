/*
 * ویجت گفتگوی سایت - یک اسکریپت، بدون وابستگی.
 *
 * نصب:  <script src="https://<نشانی-سرویس>/api/v1/widget/<کلید>.js" async></script>
 *
 * همهٔ چیزهایی که لازم دارد از همین آدرس اسکریپت و از /config/ می‌آید؛
 * هیچ کوکی‌ای نمی‌گذارد و فقط یک نشانهٔ گفتگو را در localStorage نگه می‌دارد.
 * متن فارسی و راست‌به‌چپ است و روی موبایل تمام‌صفحه باز می‌شود.
 */
(function () {
  "use strict";
  if (window.__nmInboxWidget) return;
  window.__nmInboxWidget = true;

  var script = document.currentScript || (function () {
    var all = document.getElementsByTagName("script");
    for (var i = all.length - 1; i >= 0; i--) {
      if (/\/widget\/[^/]+\.js/.test(all[i].src || "")) return all[i];
    }
    return null;
  })();
  if (!script || !script.src) return;

  var match = script.src.match(/^(https?:\/\/[^/]+)(.*)\/widget\/([^/?#]+)\.js/);
  if (!match) return;
  var API = match[1] + match[2] + "/widget/" + match[3];
  var KEY = match[3];
  var STORE_KEY = "nm_widget_" + KEY;

  var state = { open: false, token: "", last: 0, cfg: null, unread: 0, timer: null, seen: {} };
  try { state.token = localStorage.getItem(STORE_KEY) || ""; } catch (e) {}

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    for (var k in (attrs || {})) {
      if (k === "text") node.textContent = attrs[k];
      else if (k === "class") node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(function (c) { node.appendChild(c); });
    return node;
  }

  function toFa(n) {
    return String(n).replace(/\d/g, function (d) { return "۰۱۲۳۴۵۶۷۸۹"[d]; });
  }

  function request(method, path, body) {
    var opts = { method: method, headers: {} };
    if (body) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(API + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) { var e = new Error((data.error && data.error.message) || "خطا"); e.status = r.status; throw e; }
        return data;
      });
    });
  }

  // ---------------------------------------------------------------- UI
  var host = el("div", { id: "nm-widget-root", dir: "rtl", lang: "fa" });
  var shadow = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;

  var css = [
    ":host,*{box-sizing:border-box;font-family:Vazirmatn,Tahoma,'Segoe UI',sans-serif}",
    ".fab{position:fixed;bottom:20px;left:20px;width:58px;height:58px;border-radius:50%;border:0;cursor:pointer;",
    "background:var(--c);color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.28);display:flex;align-items:center;justify-content:center;z-index:2147483000}",
    ".fab svg{width:28px;height:28px;fill:#fff}",
    ".badge{position:absolute;top:-4px;inset-inline-end:-4px;min-width:20px;height:20px;border-radius:10px;background:#e53935;color:#fff;font-size:12px;",
    "display:none;align-items:center;justify-content:center;padding:0 5px}",
    ".panel{position:fixed;bottom:90px;left:20px;width:360px;max-width:calc(100vw - 24px);height:520px;max-height:calc(100vh - 110px);",
    "background:#fff;color:#1a1a1a;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.3);display:none;flex-direction:column;overflow:hidden;z-index:2147483000}",
    ".panel.open{display:flex}",
    ".head{background:var(--c);color:#fff;padding:14px 16px;display:flex;align-items:center;gap:10px}",
    ".head b{font-size:15px;flex:1}.head small{display:block;font-size:12px;opacity:.85;font-weight:400}",
    ".x{background:transparent;border:0;color:#fff;font-size:22px;cursor:pointer;line-height:1}",
    ".log{flex:1;overflow-y:auto;padding:14px;background:#f6f7f9;display:flex;flex-direction:column;gap:8px}",
    ".m{max-width:82%;padding:9px 12px;border-radius:14px;font-size:14px;line-height:1.7;white-space:pre-wrap;word-break:break-word}",
    ".m.me{align-self:flex-start;background:var(--c);color:#fff;border-end-start-radius:4px}",
    ".m.them{align-self:flex-end;background:#fff;border:1px solid #e3e6ea;border-end-end-radius:4px}",
    ".m time{display:block;font-size:11px;opacity:.65;margin-top:2px}",
    ".sys{align-self:center;font-size:12px;color:#6b7280;text-align:center;padding:4px 10px}",
    ".form{display:flex;gap:8px;padding:10px;border-top:1px solid #e3e6ea;background:#fff}",
    ".form textarea{flex:1;resize:none;border:1px solid #d5d9df;border-radius:12px;padding:9px 12px;font-size:14px;height:42px;max-height:110px;outline:none}",
    ".form textarea:focus{border-color:var(--c)}",
    ".send{background:var(--c);color:#fff;border:0;border-radius:12px;padding:0 16px;cursor:pointer;font-size:14px}",
    ".send:disabled{opacity:.5;cursor:default}",
    ".pre{padding:16px;display:flex;flex-direction:column;gap:10px;background:#f6f7f9;flex:1;overflow-y:auto}",
    ".pre input{border:1px solid #d5d9df;border-radius:10px;padding:10px 12px;font-size:14px}",
    ".pre p{margin:0;font-size:13px;color:#4b5563;line-height:1.8}",
    "@media(max-width:520px){.panel{inset:0;width:100%;max-width:none;height:100%;max-height:none;border-radius:0}.fab{bottom:14px;left:14px}.panel.open~.fab{display:none}}"
  ].join("");

  var styleEl = el("style", { text: css });
  var fab = el("button", { class: "fab", type: "button", "aria-label": "گفتگو با ما" });
  fab.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-5 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/></svg>';
  var badge = el("span", { class: "badge" });
  fab.appendChild(badge);

  var title = el("b", { text: "گفتگو با ما" });
  var sub = el("small", { text: "" });
  var closeBtn = el("button", { class: "x", type: "button", "aria-label": "بستن", text: "×" });
  var head = el("div", { class: "head" }, [el("div", { style: "flex:1" }, [title, sub]), closeBtn]);
  var log = el("div", { class: "log", role: "log", "aria-live": "polite" });
  var input = el("textarea", { placeholder: "پیامتان را بنویسید…", rows: "1", maxlength: "2000" });
  var sendBtn = el("button", { class: "send", type: "button", text: "ارسال" });
  var form = el("div", { class: "form" }, [input, sendBtn]);
  var panel = el("div", { class: "panel", role: "dialog", "aria-label": "گفتگو" }, [head, log, form]);

  shadow.appendChild(styleEl);
  shadow.appendChild(panel);
  shadow.appendChild(fab);

  function paint(cfg) {
    host.style.setProperty("--c", cfg.color || "#2563eb");
    if (shadow !== host) shadow.host.style.setProperty("--c", cfg.color || "#2563eb");
    title.textContent = cfg.title || "گفتگو با ما";
    sub.textContent = cfg.open_now ? (cfg.subtitle || "معمولاً در چند دقیقه پاسخ می‌دهیم") : (cfg.offline_subtitle || "خارج از ساعت کاری هستیم؛ پیام بگذارید");
    // «چپ/راست» همان چپ و راستِ واقعیِ صفحه است، نه ابتدا/انتهای متن (در صفحهٔ راست‌به‌چپ این دو برعکس‌اند).
    if (cfg.position === "right") { fab.style.left = "auto"; fab.style.right = "20px"; panel.style.left = "auto"; panel.style.right = "20px"; }
  }

  function bubble(m) {
    if (state.seen[m.id]) return;
    state.seen[m.id] = true;
    var mine = m.role === "CUSTOMER";
    var d = new Date(m.at);
    var hh = toFa(("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2));
    var node = el("div", { class: "m " + (mine ? "me" : "them") }, [el("span", { text: m.text }), el("time", { text: hh })]);
    log.appendChild(node);
    log.scrollTop = log.scrollHeight;
    if (m.id > state.last) state.last = m.id;
    if (!mine && !state.open) { state.unread++; showBadge(); }
  }

  function showBadge() {
    badge.textContent = toFa(state.unread);
    badge.style.display = state.unread ? "flex" : "none";
  }

  function note(text) { log.appendChild(el("div", { class: "sys", text: text })); log.scrollTop = log.scrollHeight; }

  // ------------------------------------------------------------ logic
  function ensureSession(extra) {
    if (state.token) return Promise.resolve();
    return request("POST", "/session/", extra || {}).then(function (data) {
      state.token = data.token;
      try { localStorage.setItem(STORE_KEY, state.token); } catch (e) {}
    });
  }

  function loadHistory() {
    if (!state.token) return Promise.resolve();
    return request("GET", "/messages/?token=" + encodeURIComponent(state.token) + "&after=0").then(function (data) {
      (data.messages || []).forEach(bubble);
    }).catch(function (e) {
      if (e.status === 404) { state.token = ""; try { localStorage.removeItem(STORE_KEY); } catch (x) {} }
    });
  }

  function poll() {
    if (!state.token) return;
    request("GET", "/messages/?token=" + encodeURIComponent(state.token) + "&after=" + state.last).then(function (data) {
      (data.messages || []).forEach(bubble);
    }).catch(function () {});
  }

  function startPolling() {
    stopPolling();
    state.timer = setInterval(poll, state.open ? 3000 : 15000);
  }
  function stopPolling() { if (state.timer) { clearInterval(state.timer); state.timer = null; } }

  function send() {
    var text = input.value.trim();
    if (!text) return;
    sendBtn.disabled = true;
    ensureSession().then(function () {
      return request("POST", "/send/", { token: state.token, text: text });
    }).then(function (data) {
      input.value = ""; input.style.height = "42px";
      if (data.message) bubble(data.message);
      if (data.notice) note(data.notice);
    }).catch(function (e) {
      note(e.message || "ارسال نشد؛ دوباره امتحان کنید.");
    }).then(function () { sendBtn.disabled = false; input.focus(); });
  }

  function openPanel() {
    state.open = true; state.unread = 0; showBadge();
    panel.classList.add("open");
    var chain = state.token ? loadHistory() : Promise.resolve();
    chain.then(function () {
      if (!log.childNodes.length && state.cfg && state.cfg.welcome) note(state.cfg.welcome);
      input.focus();
    });
    startPolling();
  }
  function closePanel() { state.open = false; panel.classList.remove("open"); startPolling(); }

  fab.addEventListener("click", function () { state.open ? closePanel() : openPanel(); });
  closeBtn.addEventListener("click", closePanel);
  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  input.addEventListener("input", function () {
    input.style.height = "42px";
    input.style.height = Math.min(110, input.scrollHeight) + "px";
  });

  request("GET", "/config/").then(function (cfg) {
    if (!cfg.enabled) return;
    state.cfg = cfg;
    document.body.appendChild(host);
    paint(cfg);
    if (state.token) { loadHistory().then(function () { startPolling(); }); } else { startPolling(); }
    if (cfg.auto_open) setTimeout(openPanel, 1500);
  }).catch(function () { /* a chat widget must never break the host page */ });
})();
