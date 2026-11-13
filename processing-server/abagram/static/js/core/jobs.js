// Starting reading jobs (each opens the Chromium window and asks Instagram), with their cost shown first.
import { h, ltr } from "./dom.js";
import { api, forgetProfile } from "./api.js";
import { faNum } from "./format.js";
import { sheet, confirm as ask } from "./overlay.js";
import { state, pref, pokePolling, invalidate, emit } from "./store.js";
import { toast, button } from "./ui.js";

export const JOB_TITLE = {
  login: "ورود به اینستاگرام", check: "بررسی نشست", profile: "خواندن پروفایل", posts: "خواندن پست‌های بیشتر",
  details: "خواندن کامنت و لایک‌کنندگان", stories: "خواندن استوری فعال", highlights: "خواندن آیتم‌های هایلایت",
  follow: "خواندن فالوورها و فالووینگ", download: "دانلود عکس و ویدیو", request: "فرستادن درخواست فالو", harvest: "خواندن همهٔ فهرست", lookup: "خواندن سریع پروفایل‌ها", browse: "خواندن پروفایل‌ها در یک پنجره",
};

export const STEP_TITLE = {
  browser: "باز کردن مرورگر", page: "رفتن به صفحه", read: "خواندن", save: "ذخیره", credentials: "یوزرنیم و پسورد",
  answer: "پاسخ اینستاگرام", plan: "برنامهٔ دانلود", download: "دانلود فایل‌ها",
};

// What each outcome means, in plain Persian (Instagram's own sentence is shown next to it, verbatim).
export const KIND = {
  ok: { tone: "ok", icon: "circle-check", title: "انجام شد", text: "" },
  bad_password: { tone: "bad", icon: "circle-x", title: "پسورد اشتباه است", text: "اینستاگرام می‌گوید این یوزرنیم حساب دارد، ولی پسورد را قبول نکرد." },
  bad_username: { tone: "bad", icon: "circle-x", title: "این یوزرنیم حسابی ندارد", text: "املای یوزرنیم را دوباره چک کن." },
  bad_credentials: { tone: "bad", icon: "circle-x", title: "یوزرنیم یا پسورد اشتباه است", text: "اینستاگرام نمی‌گوید کدام‌یک غلط است. هر دو را دوباره چک کن." },
  bad_code: { tone: "bad", icon: "circle-x", title: "کد قبول نشد", text: "کد را دوباره بخوان. کدها بعد از چند دقیقه منقضی می‌شوند." },
  rate_limit: { tone: "warn", icon: "hourglass", title: "اینستاگرام گفت صبر کن", text: "تا پایان مکث هیچ درخواستی فرستاده نمی‌شود. تلاش پشت‌سرهم وضع را بدتر می‌کند." },
  disabled: { tone: "bad", icon: "circle-x", title: "حساب محدود یا غیرفعال است", text: "وضعیت حساب را در خود اپ اینستاگرام ببین." },
  automated: { tone: "bad", icon: "circle-x", title: "اینستاگرام رفتار خودکار را تشخیص داد", text: "ورود را در پنجرهٔ مرورگر دستی انجام بده یا کمی بعد امتحان کن." },
  network: { tone: "bad", icon: "globe", title: "اینستاگرام باز نشد", text: "اتصال قطع است یا فیلتر شده. VPN را روشن کن یا در تنظیمات اتصال پراکسی بده." },
  timeout: { tone: "warn", icon: "alert", title: "جواب روشنی نیامد", text: "عکس صفحه پایین است. اگر می‌خواهی خود پنجره را ببینی، «تنظیمات › مرورگر» را روشن کن و دوباره امتحان کن." },
  session_invalid: { tone: "warn", icon: "alert", title: "نشست معتبر نیست", text: "اینستاگرام صفحهٔ ورود نشان داد. دوباره وارد شو." },
  browser: { tone: "bad", icon: "circle-x", title: "مرورگر باز نشد", text: "اگر پنجرهٔ دیگری از همین برنامه باز است ببندش و دوباره امتحان کن." },
  cancelled: { tone: "warn", icon: "alert", title: "لغو شد", text: "مرورگر بسته شد." },
  budget: { tone: "warn", icon: "gauge", title: "سقف ایمنی پر شده", text: "برای محافظت از حساب، کار شروع نشد یا همین‌جا ماند." },
  cooldown: { tone: "warn", icon: "hourglass", title: "در مکثِ بعد از «صبر کن»", text: "اینستاگرام چند دقیقه پیش گفت صبر کن." },
  not_found: { tone: "bad", icon: "circle-x", title: "این صفحه پیدا نشد", text: "اینستاگرام صفحه‌ای با این یوزرنیم ندارد؛ شاید پاک شده یا یوزرنیمش عوض شده." },
  unreadable: { tone: "warn", icon: "alert", title: "چیزی خوانده نشد", text: "صفحه باز شد ولی اطلاعاتی که بشناسم در آن نبود. عکس صفحه پایین است." },
  no_posts: { tone: "warn", icon: "image", title: "پستی ذخیره نشده", text: "اول پروفایل را بخوان." },
  no_profile: { tone: "warn", icon: "user", title: "پروفایل خوانده نشده", text: "اول پروفایل را بخوان." },
  no_highlights: { tone: "warn", icon: "circle-play", title: "هایلایتی برای خواندن نیست", text: "پروفایل را دوباره بخوان تا هایلایت‌ها ذخیره شوند." },
  no_selection: { tone: "warn", icon: "circle-play", title: "هایلایت انتخاب نشده", text: "هایلایت‌ها فقط با انتخاب خودت دانلود می‌شوند." },
  no_media: { tone: "warn", icon: "download", title: "چیزی برای دانلود نیست", text: "اول آیتم‌ها را بخوان (پروفایل، هایلایت یا استوری)." },
  expired: { tone: "warn", icon: "clock", title: "لینک فایل‌ها منقضی شده", text: "دوباره بخوان و بعد دانلود کن." },
  private: { tone: "warn", icon: "lock", title: "این حساب خصوصی است", text: "پست‌ها و فهرست‌هایش دیده نمی‌شود." },
  empty: { tone: "warn", icon: "image", title: "چیزی برای خواندن نیست", text: "این حساب هنوز پستی ندارد." },
  public: { tone: "warn", icon: "info", title: "این حساب عمومی است", text: "درخواست فالو لازم نیست؛ همه‌چیزش بدون فالو خوانده می‌شود." },
  no_button: { tone: "warn", icon: "alert", title: "دکمهٔ Follow پیدا نشد", text: "صفحهٔ این حساب دکمهٔ فالو نشان نداد؛ عکس صفحه پایین است." },
  no_limit: { tone: "warn", icon: "gauge", title: "سقف صفر است", text: "سقف این فهرست‌ها در محدودیت‌ها صفر است؛ بالا ببر." },
  other: { tone: "bad", icon: "circle-x", title: "اینستاگرام خطا داد", text: "متن اصلی پیامش پایین است." },
  error: { tone: "bad", icon: "circle-x", title: "خطای برنامه", text: "جزئیات در گزارش هست." },
};

const lim = () => state.status?.budget?.limits || {};
const left = (kind) => {
  const b = state.status?.budget;
  if (!b) return null;
  const cap = b.limits[`${kind}s_hour`];
  return Math.max(0, cap - b.used[kind].hour);
};

/** Lines that say what a job will ask of Instagram. ctx: {profile, codes, ids, which} */
export function cost(kind, ctx = {}) {
  const L = lim(), p = ctx.profile || {};
  const pages = { profile: 1, check: 1, login: 1, stories: 1, posts: 1, follow: 1, download: 0,
    details: (ctx.codes?.length || L.detail_posts || 5), highlights: (ctx.ids?.length || L.highlights || 3) }[kind] ?? 1;
  const per12 = (n) => Math.max(0, Math.ceil(n / 12));
  let scrolls = 0;
  if (kind === "posts") scrolls = per12(Math.min(L.posts || 36, p.posts || L.posts || 36) - 12);
  if (kind === "follow") scrolls = (ctx.which || ["followers", "following"]).reduce((a, w) => a + Math.max(1, per12(Math.min(L[w] || 24, p[w] ?? (L[w] || 24)))), 0);
  if (kind === "details") scrolls = pages * (1 + per12((L.comments || 20) - 15));
  const lines = [];
  if (pages) lines.push(`${faNum(pages)} صفحه از ${faNum(left("page") ?? 0)} صفحهٔ باقی‌ماندهٔ این ساعت`);
  if (scrolls) lines.push(`حدود ${faNum(scrolls)} ورق‌زدن از ${faNum(left("scroll") ?? 0)} ورق‌زدن باقی‌مانده`);
  if (kind === "download") lines.push(`بدون درخواست به اینستاگرام؛ تا ${faNum(L.media_files || 80)} فایل و ${faNum(L.media_job_mb || 400)} مگابایت`);
  if (kind === "stories" || kind === "highlights") lines.push("فقط صفحه خوانده می‌شود؛ دکمهٔ «View story» زده نمی‌شود.");
  return lines;
}

export function runningFor(u) {
  const s = state.status;
  return !!(s && s.busy && u && (s.username || "").toLowerCase() === String(u).toLowerCase());
}

/** Run the last job again (same kind and body) — for the «دوباره امتحان کن» buttons. */
export function retryLast(opts) {
  const last = state.lastJob;
  return last ? startJob(last.kind, last.body, opts) : Promise.resolve({ ok: false });
}

/** POST /api/<kind> after a short sheet that shows the cost. Returns {ok, data}. */
export function startJob(kind, body = {}, { confirm = true, title, lines, cta = "شروع" } = {}) {
  const send = async () => {
    let r;
    try {
      r = await api(`/api/${kind}`, { proxy: pref("proxy") || "", ...body });
    } catch {
      toast("سرور محلی جواب نمی‌دهد؛ app.py را اجرا کن.", { tone: "danger" });
      return { ok: false, status: 0, data: null };
    }
    if (r.ok && kind !== "login") state.lastJob = { kind, body: { ...body } };   // «دوباره امتحان کن» repeats it (never a password)
    if (r.status === 409) toast(r.data?.message || "یک کار دیگر در حال اجراست؛ صبر کن تمام شود.", { tone: "danger" });   // the server may say why
    else if (r.status === 422) toast("ورودی درست نیست: " + ((r.data && r.data.fields) || []).join("، "), { tone: "danger" });
    else if (r.ok) { toast(`${JOB_TITLE[kind] || "کار"} شروع شد`); pokePolling(); }
    return r;
  };
  if (!confirm) return send();
  return new Promise((resolve) => {
    let result = { ok: false };
    const go = button({ label: cta, kind: "primary", full: true, onClick: async () => { result = await send(); d.close(); } });
    const no = button({ label: "انصراف", kind: "ghost", full: true, onClick: () => d.close() });
    const items = (lines || cost(kind, body)).map((t) => h("li", { text: t }));
    const who = body.username ? h("p", { class: "jb-who" }, ltr(`@${body.username}`)) : null;
    const d = sheet({ title: title || JOB_TITLE[kind], content: h("div", { class: "jb-cost" }, who, h("ul", { class: "jb-lines" }, items)),
      actions: [go, no], onClose: () => resolve(result) });
  });
}

/** Delete everything saved about a person on this computer, after asking. Emits "profiles-changed". */
export async function forget(username) {
  const yes = await ask({ title: `حذف @${username} از ذخیره‌ها؟`, danger: true, cta: "حذف",
    text: "اطلاعات، پست‌ها، فهرست‌ها و فایل‌های دانلودشدهٔ این پروفایل از روی این کامپیوتر پاک می‌شود. از اینستاگرام چیزی پاک نمی‌شود." });
  if (!yes) return false;
  let r;
  try { r = await forgetProfile(username); } catch { toast("سرور محلی جواب نمی‌دهد.", { tone: "danger" }); return false; }
  if (r.status === 409) { toast("الان یک کار روی همین پروفایل در جریان است؛ اول لغوش کن.", { tone: "danger" }); return false; }
  if (!r.ok) { toast("حذف نشد.", { tone: "danger" }); return false; }
  invalidate(username);
  emit("profiles-changed", username);
  toast(`@${username} حذف شد`, { tone: "ok" });
  return true;
}
