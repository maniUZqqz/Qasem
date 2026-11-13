// «ورود به آباگرام» (his order 2026-11-05): the site's own door, shown before anything else loads. An AbaOne username and
// password go to our server, which asks AbaOne's LoginApi; only the people the admin added come in. Nothing about any
// account is shown before its password is right. The Instagram login's look (login.css .lg-*), so the two doors match;
// the turning ring while the server checks is the one bold thing.
import { h, icon } from "../core/dom.js";
import { authLogin } from "../core/api.js";
import { button, setBusy } from "../core/ui.js";
import { enter } from "../core/motion.js";

const toLatin = (s) => s.replace(/[۰-۹]/g, (d) => d.charCodeAt(0) - 0x6f0).replace(/[٠-٩]/g, (d) => d.charCodeAt(0) - 0x660);

function floatField(label, input, extra) {
  input.classList.add("lg-in");
  input.placeholder = " ";             // :placeholder-shown moves the label up once there is text
  return h("div", { class: "lg-f" }, h("div", { class: "lg-box" },
    h("label", { class: "lg-fl" }, input, h("span", { class: "lg-fl-t", text: label })), extra));
}

/** expired: the login ran out while the site was open (say so). onIn(me): called once the server let him in. */
export function render({ expired = false, onIn } = {}) {
  const userIn = h("input", { type: "text", name: "username", dir: "ltr", autocomplete: "username", autocapitalize: "none",
    autocorrect: "off", spellcheck: "false", enterkeyhint: "next" });
  const pwIn = h("input", { type: "password", name: "password", dir: "ltr", autocomplete: "current-password",
    autocapitalize: "none", spellcheck: "false", enterkeyhint: "go" });
  const eye = h("button", { type: "button", class: "lg-eye", hidden: true, "aria-label": "نمایش رمز", text: "نمایش", onclick: () => {
    const show = pwIn.type === "password";
    pwIn.type = show ? "text" : "password";
    eye.textContent = show ? "پنهان" : "نمایش";
    eye.setAttribute("aria-label", show ? "پنهان کردن رمز" : "نمایش رمز");
  } });
  const go = button({ label: "ورود", kind: "primary", full: true, type: "submit", disabled: true, cls: "lg-go" });
  const err = h("p", { class: "lg-err gt-err", role: "alert", hidden: true });
  const form = h("form", { class: "lg-form", novalidate: true, "aria-label": "ورود به آباگرام" },
    floatField("نام کاربریِ آبا وان", userIn), floatField("رمز", pwIn, eye), go, err);
  const mark = icon("mark", { size: "lg", cls: "lg-mark" });
  const card = h("div", { class: "lg-card gt-card" },
    h("h1", { class: "lg-brand gt-brand" }, mark, h("span", { class: "lg-word", text: "آباگرام" })),
    h("p", { class: "gt-sub", text: "با نام کاربری و رمزِ آبا وانت وارد شو" }),
    expired ? h("p", { class: "gt-expired", role: "status" }, icon("clock", { size: "sm" }), h("span", { text: "ورودت تمام شده بود؛ دوباره وارد شو." })) : null,
    form);
  const note = h("p", { class: "lg-card lg-note" }, icon("shield"),
    h("span", { text: "فقط کسانی که مدیر اضافه کرده وارد می‌شوند. رمز مستقیم به سرورِ ورودِ آبا وان می‌رود و این‌جا ذخیره نمی‌شود." }));
  const el = h("section", { class: "lg gt" }, h("div", { class: "lg-col" }, card, note));

  const ready = () => { go.disabled = !userIn.value.trim() || !pwIn.value; eye.hidden = !pwIn.value; };
  const say = (text) => { err.textContent = text; err.hidden = !text; if (text) enter(err, "fade"); };
  userIn.addEventListener("input", () => { ready(); say(""); });
  pwIn.addEventListener("input", () => { ready(); say(""); });
  // the browser's saved password fills the boxes without an input event (login.css lg-af tells us)
  for (const i of [userIn, pwIn]) i.addEventListener("animationstart", (e) => { if (e.animationName === "lg-af") go.disabled = false; });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (go.getAttribute("aria-busy") === "true" || !userIn.value.trim() || !pwIn.value) return;
    setBusy(go, true);
    mark.classList.add("lg-turn");
    say("");
    const r = await authLogin(toLatin(userIn.value.trim()), pwIn.value).catch(() => null);
    if (r?.ok) { onIn?.(r.data?.me); return; }   // the page starts again, now behind the door
    setBusy(go, false);
    mark.classList.remove("lg-turn");
    say(r?.data?.message || "سرور آباگرام جواب نداد؛ اگر روشن است کمی بعد دوباره امتحان کن.");
    if (r?.status === 401) { pwIn.focus(); pwIn.select(); }
  });

  return { el, focus: () => userIn.focus({ preventScroll: true }) };
}
