// Login page: Instagram's centered card, mirrored for RTL. The password goes only into the /api/login body.
import { h, icon, ltr, mount, qs, uid } from "../core/dom.js";
import { submitCode, cancelJob, shotUrl } from "../core/api.js";
import { state, subscribe, pref, pokePolling } from "../core/store.js";
import { button, field, setBusy, spinner, toast } from "../core/ui.js";
import { startJob, KIND, STEP_TITLE } from "../core/jobs.js";
import { enter } from "../core/motion.js";
import { liveWindow } from "../core/livewindow.js";

const LOGIN = new Set(["login", "check"]);
const PROXY_RE = /^(https?|socks5):\/\//i;
const STEP_IC = { done: "check", failed: "x", waiting: "hourglass" };
const OFFLINE = { tone: "bad", icon: "globe", title: "سرور محلی در دسترس نیست", text: "برنامه را دوباره اجرا کن و بعد وارد شو." };
const toLatin = (s) => s.replace(/[۰-۹]/g, (d) => d.charCodeAt(0) - 0x6f0).replace(/[٠-٩]/g, (d) => d.charCodeAt(0) - 0x660);

const busy = (btn, on) => { if ((btn.getAttribute("aria-busy") === "true") !== on) setBusy(btn, on); };
const cancelLogin = () => cancelJob().catch(() => null).then(() => pokePolling());

/** A field with Instagram's floating label; `extra` sits inside the box at the inline end. */
function floatField({ label, input, extra }) {
  const err = h("p", { class: "lg-err", id: uid("lg-err"), role: "alert", hidden: true });
  input.classList.add("lg-in");
  input.placeholder = " ";
  input.setAttribute("aria-describedby", err.id);
  const box = h("div", { class: "lg-box" }, h("label", { class: "lg-fl" }, input, h("span", { class: "lg-fl-t", text: label })), extra);
  const el = h("div", { class: "lg-f" }, box, err);
  el.input = input;
  el.setError = (msg) => { err.textContent = msg || ""; err.hidden = !msg; input.setAttribute("aria-invalid", msg ? "true" : "false"); };
  input.addEventListener("input", () => el.setError(""));
  return el;
}

// The screenshot of the browser window opens large in the shared viewer (data-zoom).
const shotButton = (n) => h("button", { type: "button", class: "lg-shot", "data-zoom": "", "data-zoom-title": "عکس صفحهٔ اینستاگرام",
  "aria-label": "باز کردن عکس صفحه در اندازهٔ بزرگ" }, h("img", { src: shotUrl(n), alt: "عکس صفحهٔ اینستاگرام در پنجرهٔ مرورگر", loading: "lazy" }));
const quote = (text) => (text ? h("blockquote", { class: "lg-q", dir: "auto", text }) : null);

/** The red (or amber) block under the button: our sentence, then Instagram's own, verbatim. */
const failBlock = (k, o = {}) => h("div", { class: "lg-fail", "data-tone": k.tone, role: "alert" },
  h("p", { class: "lg-fail-t" }, icon(k.icon, { size: "sm" }), h("span", { text: k.title })),
  k.text ? h("p", { class: "lg-fail-x", text: k.text }) : null, quote(o.ig_message), Number.isFinite(o.shot) ? shotButton(o.shot) : null);

const stepRow = (st) => h("li", { class: "lg-step", "data-s": st.state }, h("span", { class: "lg-step-ic", "aria-hidden": "true" },
  st.state === "active" ? spinner(16) : STEP_IC[st.state] ? icon(STEP_IC[st.state], { size: "sm" }) : null),
h("span", { text: STEP_TITLE[st.key] || st.key }));

/** The gradient ring around a step icon (code / manual cards). */
const badge = (ic) => h("span", { class: "lg-badge", "aria-hidden": "true" }, h("span", { class: "lg-badge-in" }, icon(ic, { size: "lg" })));

/** need_code: Instagram sent a code (SMS, email or an authenticator app). */
function codeCard() {
  const input = h("input", { class: "input lg-code-in", type: "text", dir: "ltr", name: "code", inputmode: "numeric",
    autocomplete: "one-time-code", maxlength: "8", enterkeyhint: "done", spellcheck: "false" });
  const f = field({ label: "کد ۶ رقمی", input });
  const hint = h("p", { class: "lg-hint", dir: "auto" });
  const go = button({ label: "تأیید کد", kind: "primary", full: true, type: "submit", disabled: true });
  const clean = () => toLatin(input.value).replace(/\D/g, "");
  let sentAt = -1;
  input.addEventListener("input", () => { go.disabled = clean().length < 6; f.setError(""); });
  const el = h("form", { class: "lg-step-card", novalidate: true, "aria-label": "کد تأیید", onsubmit: async (e) => {
    e.preventDefault();
    const code = clean();
    if (code.length < 6) { f.setError("کد را کامل بنویس؛ دست‌کم ۶ رقم است."); input.focus(); return; }
    busy(go, true);
    const r = await submitCode(code).catch(() => null);
    if (!r?.ok) {
      busy(go, false);
      f.setError(!r ? OFFLINE.title : typeof r.data?.detail === "string" ? r.data.detail : "کد فرستاده نشد؛ دوباره امتحان کن.");
      return input.focus();
    }
    sentAt = state.log.length;
    pokePolling();
  } }, badge("key"), h("h2", { class: "lg-h", text: "کد تأیید را وارد کن" }), hint, f, go,
  button({ label: "لغو ورود", kind: "ghost", full: true, onClick: cancelLogin }));
  el.focusFirst = () => input.focus();
  el.update = (s) => {
    const o = s.outcome || {};
    hint.textContent = o.page_text || "کدی را که اینستاگرام با پیامک، ایمیل یا اپ احراز هویت فرستاده بنویس.";
    // A wrong code keeps the job waiting; the server says so in the outcome or a new log line.
    if (sentAt < 0 || (o.kind !== "bad_code" && state.log.length <= sentAt)) return;
    sentAt = -1;
    busy(go, false);
    if (o.kind === "bad_code") { f.setError(`${KIND.bad_code.title}. ${KIND.bad_code.text}`); input.select(); }
  };
  return el;
}

/** need_manual: Instagram asked for something only a person can do in the open window. */
function manualCard() {
  const q = h("div", { class: "lg-q-box" });
  const shot = h("div", { class: "lg-shot-box" });
  let shown;
  const el = h("div", { class: "lg-step-card" }, badge("window"),
    h("h2", { class: "lg-h", text: "اینستاگرام یک کار از خودت خواسته" }),
    h("p", { class: "lg-hint", text: "مثلاً «I'm not a robot» یا «این تو بودی؟». صفحه‌اش همین‌جا باز می‌شود؛ همان‌جا انجامش بده. بعد از آن، این صفحه خودش جلو می‌رود." }),
    q, liveWindow(), shot, button({ label: "لغو ورود", kind: "ghost", full: true, onClick: cancelLogin }));
  el.update = (s) => {
    const o = s.outcome || {};
    mount(q, quote(o.ig_message));
    if (o.shot !== shown) { shown = o.shot; mount(shot, Number.isFinite(o.shot) ? shotButton(o.shot) : null); }
  };
  return el;
}

export function render(params, ctx) {
  const userIn = h("input", { type: "text", name: "username", dir: "ltr", autocomplete: "username", autocapitalize: "none",
    autocorrect: "off", spellcheck: "false", enterkeyhint: "next" });
  const prefill = pref("login.prefill");          // «حساب‌های اینستاگرام» in the monitoring tab: a new account's name, once
  if (prefill) { userIn.value = prefill; pref("login.prefill", null); }
  let second = pref("login.account");             // ... and whether this login is for his OTHER account (the active one stays as it is)
  if (second) pref("login.account", null);
  const pwIn = h("input", { type: "password", name: "password", dir: "ltr", autocomplete: "current-password",
    autocapitalize: "none", spellcheck: "false", enterkeyhint: "go" });
  const eye = h("button", { type: "button", class: "lg-eye", hidden: true, "aria-label": "نمایش پسورد", text: "نمایش", onclick: () => {
    const show = pwIn.type === "password"; pwIn.type = show ? "text" : "password";
    eye.textContent = show ? "پنهان" : "نمایش"; eye.setAttribute("aria-label", show ? "پنهان کردن پسورد" : "نمایش پسورد"); } });
  const user = floatField({ label: "یوزرنیم، ایمیل یا شماره موبایل", input: userIn });
  const pass = floatField({ label: "پسورد", input: pwIn, extra: eye });
  const go = button({ label: "ورود", kind: "primary", full: true, type: "submit", disabled: true, cls: "lg-go" });
  const other = h("p", { class: "lg-other", hidden: true, text: "یک کار دیگر در حال اجراست؛ وقتی تمام شد وارد شو." });
  const secondNote = h("p", { class: "lg-second", hidden: !second }, icon("users", { size: "sm" }),
    h("span", {}, "ورود به حساب ", ltr(`@${second || ""}`), "؛ حساب فعال و کارهایش دست‌نخورده می‌مانند و بعد از ورود خودشان ادامه پیدا می‌کنند."));
  const failBox = h("div", { class: "lg-fail-box" });
  const form = h("form", { class: "lg-form", novalidate: true, "aria-label": "ورود به اینستاگرام" }, secondNote, user, pass, go, other, failBox);
  const savedU = h("span", { class: "lg-saved-u" });
  const saved = h("button", { type: "button", class: "btn link full lg-saved", onclick: () => job("check", {}, saved) },
    icon("login"), h("span", { text: "ادامه با نشست ذخیره‌شده" }), savedU);
  const alt = h("div", { class: "lg-alt", hidden: true }, h("p", { class: "lg-or" }, h("span", { text: "یا" })), saved);
  const pxIn = h("input", { class: "input", type: "text", dir: "ltr", inputmode: "url", autocomplete: "off", spellcheck: "false",
    placeholder: "socks5://127.0.0.1:1080", value: pref("proxy") || "" });
  const px = field({ label: "پراکسی", input: pxIn, help: "خالی بگذار تا بدون پراکسی وصل شود." });
  const pxOn = h("span", { class: "lg-net-on", text: "پراکسی روشن", hidden: !pref("proxy") });
  const net = h("details", { class: "lg-net" }, h("summary", { class: "lg-net-s" }, h("span", { text: "تنظیمات اتصال" }), pxOn,
    icon("chevron", { size: "sm", cls: "lg-chev" })), px);
  const stepsOl = h("ol", { class: "lg-steps", "aria-label": "مرحله‌های ورود" }), logP = h("p", { class: "lg-log", "aria-live": "polite" });
  const prog = h("div", { class: "lg-prog", hidden: true }, stepsOl, logP);
  const mark = icon("mark", { size: "lg", cls: "lg-mark" });
  const slot = h("div", { class: "lg-slot" }, form);
  const card = h("div", { class: "lg-card" }, h("h1", { class: "lg-brand" }, mark, h("span", { class: "lg-word", text: "آباگرام" })), slot, prog, alt, net);
  const note = h("p", { class: "lg-card lg-note" }, icon("shield"), h("span", { text: "رمز فقط در پنجرهٔ مرورگر تایپ می‌شود و هیچ‌جا ذخیره نمی‌شود." }));
  const el = h("section", { class: "lg" }, h("div", { class: "lg-col" }, card, note));

  const proxyOk = () => {
    if (!pxIn.value.trim() || PROXY_RE.test(pxIn.value.trim())) { px.setError(""); return true; }
    px.setError(" ");   // the message has Latin parts, each in its own <bdi>
    return !mount(qs(".error", px), "نشانی پراکسی باید با ", ltr("http://"), "، ", ltr("https://"), " یا ", ltr("socks5://"), " شروع شود.");
  };
  const saveProxy = () => {
    const v = pxIn.value.trim();
    if (!proxyOk() || v === (pref("proxy") || "")) return;
    pref("proxy", v); pxOn.hidden = !v;
    toast(v ? "پراکسی ذخیره شد" : "پراکسی برداشته شد", { tone: "ok" });
  };
  pxIn.addEventListener("change", saveProxy); pxIn.addEventListener("input", () => px.setError(""));
  // baseRun: the run before our start (undefined = none sent); seenRun: a login/check run we saw working.
  let autofilled = false, sending = false, activeBtn = null, baseRun, seenRun = null, failKey = "", view = "form", step = null;
  const live = () => !!(state.status?.busy && LOGIN.has(state.status.mode));
  function refresh() {
    const s = state.status || {}, otherJob = !!(s.busy && !LOGIN.has(s.mode) && !(second && s.queued));   // a queue unit makes room for the second login
    go.disabled = otherJob || (!live() && !((userIn.value.trim() && pwIn.value) || autofilled));
    saved.disabled = otherJob; other.hidden = !otherJob; eye.hidden = !pwIn.value;
  }
  form.addEventListener("input", () => { autofilled = false; refresh(); });
  form.addEventListener("animationstart", (e) => { if (e.animationName === "lg-af") { autofilled = true; refresh(); } });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (sending || live()) return;
    const u = userIn.value.trim(), p = pwIn.value, bad = [];
    if (!u) { user.setError("یوزرنیم، ایمیل یا شماره موبایل را بنویس."); bad.push(userIn); }
    if (!p) { pass.setError("پسورد را بنویس."); bad.push(pwIn); }
    if (!proxyOk()) { net.open = true; bad.push(pxIn); }
    if (bad.length) { bad[0].focus(); return; }
    saveProxy();
    job("login", { username: u, password: p, ...(second ? { account: second } : {}) }, go);
  });
  async function job(kind, body, btn) {
    const before = state.status?.run ?? null;
    sending = true; activeBtn = btn; failKey = ""; mount(failBox); busy(btn, true);
    const r = await startJob(kind, body, { confirm: false }).catch(() => null);   // null = the local server is down
    sending = false;
    if (r?.ok) { if (r.data?.other) second = r.data.other; baseRun = before; sync(); return; }   // a different account: added, the active one stays
    busy(btn, false);
    if (!r) { failKey = "offline"; mount(failBox, failBlock(OFFLINE)); return; }
    const bad = ((r.status === 422 && r.data?.fields) || []).map((k) => ({ username: user, password: pass })[k]).filter(Boolean);
    bad.forEach((f) => f.setError(r.data?.message || "سرور این خانه را قبول نکرد؛ دوباره بنویس."));
    bad[0]?.input.focus();
  }

  function sync() {
    const s = state.status || {}, mine = LOGIN.has(s.mode), on = !!(s.busy && mine);
    if (on) seenRun = s.run;
    const ours = mine && (s.run === seenRun || (baseRun !== undefined && (s.run ?? null) !== baseRun));
    if (ours && !s.busy && s.state === "success") {
      baseRun = undefined; seenRun = null; pwIn.value = "";
      if (second) { toast(`حساب @${second} وارد شد؛ حساب فعال همان قبلی ماند`, { tone: "ok" }); return ctx.navigate("/monitoring", { replace: true }); }
      toast("وارد شدی", { tone: "ok" });
      return ctx.navigate("/", { replace: true });
    }
    const want = on && s.state === "need_code" ? "code" : on && s.state === "need_manual" ? "manual" : "form";
    if (want !== view) {   // the form, the code card and the manual card take turns in the same card
      view = want; step = want === "code" ? codeCard() : want === "manual" ? manualCard() : null;
      mount(slot, step || form); enter(slot.firstChild, "fade");
      step?.focusFirst?.();
    }
    step?.update(s);
    const done = mine && !s.busy && s.outcome && (s.state === "failed" || (s.state === "cancelled" && ours));
    const key = done ? `${s.run}:${s.outcome.kind}` : "";
    if (key !== failKey) {   // a new failure: show it once; for our own run, focus the field it is about
      failKey = key;
      mount(failBox, done ? failBlock(KIND[s.outcome.kind] || KIND.other, s.outcome) : null);
      const f = done && ours && { bad_username: user, bad_credentials: user, bad_password: pass }[s.outcome.kind];
      if (f) { f.input.setAttribute("aria-invalid", "true"); f.input.focus(); f.input.select(); }
    }
    const wait = sending || (baseRun !== undefined && (s.run ?? null) === baseRun);   // started, run not seen yet
    busy(go, (wait && activeBtn === go) || (on && s.mode === "login"));
    busy(saved, (wait && activeBtn === saved) || (on && s.mode === "check"));
    mark.classList.toggle("lg-turn", on || wait);
    // a login Instagram threw out (session.lost_at) cannot be «continued»: only the form brings it back
    alt.hidden = view !== "form" || !s.profile_exists || !!second || !!s.session?.lost_at; net.hidden = view !== "form";
    mount(savedU, s.session?.username ? ltr(`@${s.session.username}`) : null);
    userIn.readOnly = pwIn.readOnly = on; prog.hidden = !on;
    const last = state.log[state.log.length - 1];
    if (on) mount(stepsOl, (s.steps || []).map(stepRow));
    if (on && logP.textContent !== (last?.msg || "")) { logP.textContent = last?.msg || ""; logP.dataset.level = last?.level || "info"; }
    refresh();
  }
  const offs = [subscribe("status", sync)];
  sync();
  return { el, update: () => sync(), destroy() { offs.forEach((off) => off()); pwIn.value = ""; } };
}
