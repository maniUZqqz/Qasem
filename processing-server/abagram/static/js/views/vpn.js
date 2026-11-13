// «VPN و نشانی» in settings: the office gateway's exit country for this computer = the address Instagram sees.
// Change it (new connections only; the next job's browser opens fresh ones) and check the address the internet sees.
import { h, icon, ltr, bdi, mount } from "../core/dom.js";
import { getVpn, setVpnCountry, vpnLogin, getExitIp } from "../core/api.js";
import { faNum, faDateTime } from "../core/format.js";
import { state } from "../core/store.js";
import { button, empty, skeleton, field, setBusy, toast } from "../core/ui.js";

const FA = { CA: "کانادا", DE: "آلمان", FI: "فنلاند", FR: "فرانسه", NL: "هلند", SE: "سوئد", US: "آمریکا", GB: "انگلستان",
  TR: "ترکیه", AE: "امارات", CH: "سوئیس", AT: "اتریش", PL: "لهستان", IT: "ایتالیا", ES: "اسپانیا", JP: "ژاپن", SG: "سنگاپور", IR: "ایران" };
const land = (c) => FA[c] || c || "نامعلوم";
const BUSY = "صبر کن کار در حال اجرا تمام شود؛ عوض شدنِ نشانی وسطِ کار برای اینستاگرام مشکوک است.";
const isolate = (s) => `⁦${s}⁩`;   // a Latin address inside Persian text

// Why the gateway (or the server) said no, in his words.
function why(r) {
  const d = r?.data || {};
  if (!r) return "برنامه جواب نداد؛ دوباره امتحان کن.";
  if (d.detail === "busy") return BUSY;
  if (d.detail === "invalid") return "این کشور درست نیست.";
  if (!d.reachable) return "گیت‌وی VPN جواب نداد؛ شبکه را بررسی کن و دوباره امتحان کن.";
  if (d.status === 401) return "ورودِ VPNِ این کامپیوتر تمام شده؛ دوباره وارد شو.";
  if (/turned off/i.test(d.message)) return "انتخابِ کشور روی گیت‌وی خاموش است.";
  if (/not allowed/i.test(d.message)) return "این حساب اجازهٔ VPN ندارد.";
  if (d.status === 400 || d.status === 422) return "این کشور الان سرورِ سالمی ندارد؛ کشورِ دیگری انتخاب کن.";
  return d.message ? `گیت‌وی نپذیرفت: ${d.message}` : "گیت‌وی نپذیرفت.";
}

export function vpnView() {
  const box = h("div", { class: "sg-stack" }, skeleton("line", 5));
  const show = (r, recheck = 0) => mount(box, body(r, show, load, recheck));
  const load = () => getVpn().then((r) => show(r), () => show(null));
  load();
  return box;
}

function body(r, show, load, recheck) {
  const d = r?.data;
  const retry = button({ label: "دوباره امتحان کن", icon: "refresh", onClick: load });
  if (!d?.reachable) return empty({ icon: "alert", title: "گیت‌وی VPN جواب نداد",
    text: `گیت‌وی در ${isolate(d?.gateway || "VPN")} در دسترس نبود. شبکهٔ شرکت را بررسی کن.`, action: retry });
  if (!d.ok) return empty({ icon: "alert", title: "گیت‌وی VPN نپذیرفت", text: why(r), action: retry });
  if (!d.identified) return empty({ icon: "alert", title: "گیت‌وی این کامپیوتر را نشناخت",
    text: d.reason || "نشانیِ این کامپیوتر در شبکه برای گیت‌وی آشنا نیست.", action: retry });
  if (!d.logged_in) return loginForm(show);
  const p = d.person || {}, s = d.session || {};
  const exit = exitCard(recheck);
  return h("div", { class: "sg-stack" },
    h("p", { class: "sg-intro", text: "اینستاگرام ما را از کشورِ VPNِ این کامپیوتر می‌بیند. عوض کردنِ کشور نشانیِ بیرونی را عوض می‌کند؛ فقط اتصال‌های تازه از کشورِ تازه می‌روند و کارِ بعدی با همان شروع می‌شود." }),
    h("div", { class: "sg-card" }, h("span", { class: "sg-card-ic" }, icon("pin-map")),
      h("div", { class: "sg-grow" }, h("p", { class: "strong" }, ltr(p.name || p.username || "")),
        h("p", { class: "sg-muted" }, "این کامپیوتر: ", ltr(d.device || ""), d.via === "admin" ? "، واردشده به دستِ مدیرِ شبکه" : ""),
        s.expires ? h("p", { class: "sg-muted" }, "ورودِ VPN تا ", bdi(faDateTime(s.expires)), " می‌ماند.") : null)),
    p.vpn_allowed === false ? h("p", { class: "sg-muted", text: "این حساب اجازهٔ VPN ندارد؛ کشور را فقط مدیرِ شبکه می‌تواند باز کند." })
      : choices(d.location || {}, show),
    exit.el,
    h("p", { class: "sg-muted" }, "گیت‌وی: ", ltr(d.gateway), "؛ عوض کردنش با متغیرِ ", ltr("IGS_VPN_API"), " روی سرور است."));
}

function choices(loc, show) {
  const cur = loc.current || "";
  const opts = [{ country: "", available: true }, ...(loc.options || [])];
  if (cur && !opts.some((o) => o.country === cur)) opts.push({ country: cur, available: false });
  async function pick(code, btn) {
    if (state.status?.busy) return toast(BUSY, { tone: "danger" });
    list.querySelectorAll("button").forEach((b) => (b.disabled = true));
    setBusy(btn, true);
    const r = await setVpnCountry(code).catch(() => null);
    if (r?.ok) {
      toast(code ? `از این به بعد اتصال‌های تازه از ${land(code)} می‌روند.` : "کشور روی «خودکار» رفت؛ گیت‌وی خودش انتخاب می‌کند.", { tone: "ok" });
      return show(r, 2500);   // the gateway moves the computer at once; a breath later the address shows it
    }
    toast(why(r), { tone: "danger" });
    show(await getVpn().catch(() => null));
  }
  const list = h("div", { class: "vp-list", role: "radiogroup", "aria-label": "کشورِ خروج" }, opts.map((o) => {
    const on = o.country === cur;
    const btn = h("button", { type: "button", role: "radio", class: "vp-opt", "aria-checked": String(on), disabled: !o.available && !on,
      onclick: () => (on ? null : pick(o.country, btn)) },
      h("span", { class: "vp-name", text: o.country ? land(o.country) : "خودکار" }),
      h("span", { class: "vp-sub" }, !o.country ? "گیت‌وی انتخاب می‌کند"
        : o.available ? [bdi(faNum(o.alive)), " از ", bdi(`${faNum(o.total)} سرور`), " سالم"] : "سرورِ سالمی ندارد"));
    return btn;
  }));
  const used = loc.effective;
  return h("fieldset", { class: "sg-set" }, h("legend", { class: "sg-h3", text: "کشورِ خروج" }),
    h("div", { class: "sg-stack" }, list,
      h("p", { class: "sg-muted" }, "همین حالا: ", used ? h("b", { text: land(used) })
        : "خودکار؛ هر اتصال از یکی از سرورهای سالم می‌رود", used && cur && used !== cur ? `، چون ${land(cur)} الان در دسترس نیست` : "")));
}

// The address the internet sees, through the same way the jobs go (the saved proxy, when there is one).
function exitCard(delay) {
  const ip = h("p", { class: "sg-big vp-ip" }, skeleton("line")), sub = h("p", { class: "sg-muted" });
  const again = button({ label: "بررسیِ نشانی", icon: "refresh", size: "sm", onClick: () => check() });
  async function check() {
    setBusy(again, true);
    mount(ip, skeleton("line"));
    sub.replaceChildren();
    const d = (await getExitIp().catch(() => null))?.data;
    setBusy(again, false);
    if (!d?.ok) {
      mount(ip, h("span", { class: "sg-muted", text: "نشانی خوانده نشد" }));
      sub.textContent = "اینترنت یا VPN جواب نداد؛ کمی بعد دوباره امتحان کن.";
      return;
    }
    mount(ip, ltr(d.ip));
    mount(sub, "کشور: ", h("b", { text: land(d.loc) }),
      d.via === "proxy" ? "؛ از راهِ پراکسیِ ذخیره‌شده، پس کشورِ VPN فقط وقتی اثر دارد که پراکسی هم از همین اینترنت برود." : "");
  }
  setTimeout(check, delay || 0);
  return { check, el: h("div", { class: "sg-card vp-exit" }, h("span", { class: "sg-card-ic" }, icon("globe")),
    h("div", { class: "sg-grow" }, h("p", { class: "sg-muted", text: "نشانی‌ای که اینستاگرام می‌بیند" }), ip, sub), again) };
}

// Only when the gateway has no one signed in on this computer: its own portal login; the password is not kept anywhere.
function loginForm(show) {
  const user = h("input", { class: "input", type: "text", dir: "ltr", autocomplete: "username", autocapitalize: "none", spellcheck: "false" });
  const pass = h("input", { class: "input", type: "password", dir: "ltr", autocomplete: "current-password" });
  const fu = field({ id: "vp-user", label: "نام کاربریِ VPN", input: user });
  const fp = field({ id: "vp-pass", label: "رمزِ VPN", input: pass, help: "رمز مستقیم به گیت‌وی می‌رود و هیچ‌جا ذخیره نمی‌شود." });
  const go = button({ label: "ورود به VPN", icon: "login", kind: "primary", type: "submit" });
  async function submit(e) {
    e.preventDefault();
    fu.setError(""); fp.setError("");
    if (!user.value.trim()) return fu.setError("نام کاربری را بنویس."), user.focus();
    if (!pass.value) return fp.setError("رمز را بنویس."), pass.focus();
    setBusy(go, true);
    const r = await vpnLogin(user.value.trim(), pass.value).catch(() => null);
    setBusy(go, false);
    pass.value = "";
    if (r?.ok) { toast("این کامپیوتر وارد VPN شد", { tone: "ok" }); return show(r); }
    const d = r?.data || {};
    fp.setError(d.reachable && (d.status === 400 || d.status === 401) ? "نام کاربری یا رمز درست نیست." : why(r));
    pass.focus();
  }
  return h("form", { class: "sg-stack", novalidate: true, onsubmit: submit },
    h("p", { class: "sg-intro", text: "گیت‌وی هنوز کسی را روی این کامپیوتر وارد نکرده. با حسابِ VPNی که برای همین کامپیوتر است وارد شو." }),
    fu, fp, h("div", { class: "sg-acts" }, go));
}
