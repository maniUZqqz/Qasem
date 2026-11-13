// Persian numbers, dates and sizes. Every number the person reads goes through here.
const grouped = new Intl.NumberFormat("fa-IR");
const compact = new Intl.NumberFormat("fa-IR", { notation: "compact", maximumFractionDigits: 1 });
const oneDecimal = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
const dateFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { day: "numeric", month: "long", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
const timeFmt = new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit" });
const relative = new Intl.RelativeTimeFormat("fa", { numeric: "auto" });

const toMs = (t) => (typeof t === "number" ? (t < 1e12 ? t * 1000 : t) : Date.parse(t));

export const faNum = (n) => (n === null || n === undefined || Number.isNaN(Number(n)) ? "–" : grouped.format(Number(n)));
export const faCompact = (n) => (n === null || n === undefined ? "–" : Math.abs(n) >= 10000 ? compact.format(n) : grouped.format(n));
export const faDecimal = (n) => oneDecimal.format(n);

export function faDate(t) {
  const ms = toMs(t);
  return Number.isFinite(ms) ? dateFmt.format(new Date(ms)) : "";
}

export function faDateTime(t) {
  const ms = toMs(t);
  return Number.isFinite(ms) ? dateTimeFmt.format(new Date(ms)) : "";
}

export function faTime(t) {
  const ms = toMs(t);
  return Number.isFinite(ms) ? timeFmt.format(new Date(ms)) : "";
}

export function ago(t) {
  const ms = toMs(t);
  if (!Number.isFinite(ms)) return "";
  const sec = Math.round((ms - Date.now()) / 1000);
  const abs = Math.abs(sec);
  if (abs < 45) return "همین الان";
  if (abs < 3600) return relative.format(Math.round(sec / 60), "minute");
  if (abs < 86400) return relative.format(Math.round(sec / 3600), "hour");
  if (abs < 86400 * 30) return relative.format(Math.round(sec / 86400), "day");
  if (abs < 86400 * 365) return relative.format(Math.round(sec / (86400 * 30)), "month");
  return relative.format(Math.round(sec / (86400 * 365)), "year");
}

export function bytes(n) {
  if (!Number.isFinite(n)) return "–";
  if (n < 1024) return `${grouped.format(n)} بایت`;
  if (n < 1024 * 1024) return `${oneDecimal.format(n / 1024)} کیلوبایت`;
  if (n < 1024 ** 3) return `${oneDecimal.format(n / 1024 / 1024)} مگابایت`;
  return `${oneDecimal.format(n / 1024 ** 3)} گیگابایت`;
}

export function clock(sec) {
  const s = Math.max(0, Math.round(sec || 0));
  return `${grouped.format(Math.floor(s / 60))}:${grouped.format(s % 60).padStart(2, "۰")}`;
}

export const unit = (n, word) => `${faNum(n)} ${word}`;

export function fresh(t, hours = 24) {
  const ms = toMs(t);
  return Number.isFinite(ms) && Date.now() - ms < hours * 3600 * 1000;
}
