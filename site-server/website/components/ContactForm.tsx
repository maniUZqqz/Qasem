"use client";

import { useState } from "react";

import type { Locale } from "@/lib/i18n";
import { track } from "@/lib/track";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

/** Subject values are the backend's enum; only the labels are translated. */
const T = {
  fa: {
    subjects: [
      { value: "DEMO", label: "درخواست دمو" },
      { value: "PRICING", label: "سؤال درباره قیمت" },
      { value: "SUPPORT", label: "پشتیبانی" },
      { value: "PARTNERSHIP", label: "همکاری" },
      { value: "OTHER", label: "موضوع دیگر" },
    ],
    name: "نام",
    email: "ایمیل",
    phone: "شماره تماس",
    business: "نام کسب‌وکار",
    subject: "موضوع",
    message: "پیام",
    honeypot: "وب‌سایت",
    send: "ارسال پیام",
    sending: "در حال ارسال…",
    privacy: "اطلاعات شما فقط برای پاسخ به همین پیام استفاده می‌شود.",
    sentTitle: "پیام شما رسید",
    sentBody:
      "به‌زودی جواب می‌دهیم. اگر عجله دارید، حساب رایگان بسازید و همین حالا شروع کنید.",
    tooMany: "تعداد پیام‌ها زیاد بود. کمی بعد دوباره امتحان کنید.",
    failed: "ارسال نشد. دوباره تلاش کنید.",
    offline: "ارتباط برقرار نشد. اینترنت را بررسی کنید و دوباره بفرستید.",
  },
  en: {
    subjects: [
      { value: "DEMO", label: "Request a demo" },
      { value: "PRICING", label: "Question about pricing" },
      { value: "SUPPORT", label: "Support" },
      { value: "PARTNERSHIP", label: "Partnership" },
      { value: "OTHER", label: "Something else" },
    ],
    name: "Name",
    email: "Email",
    phone: "Phone",
    business: "Business name",
    subject: "Subject",
    message: "Message",
    honeypot: "Website",
    send: "Send message",
    sending: "Sending…",
    privacy: "We use your details only to answer this message.",
    sentTitle: "Your message arrived",
    sentBody:
      "We will reply shortly. If you are in a hurry, create a free account and start now.",
    tooMany: "That is a lot of messages. Try again in a little while.",
    failed: "It did not send. Please try again.",
    offline: "No connection. Check your internet and send again.",
  },
} as const;

type State = "idle" | "sending" | "sent" | "error";

/** Read the campaign parameters this visitor arrived with, if any. Done at
 *  submit time rather than on mount so it works for a visitor who lands on
 *  another page first and navigates here. */
function attribution() {
  if (typeof window === "undefined") return {};
  const q = new URLSearchParams(window.location.search);
  const utm: Record<string, string> = {};
  for (const key of ["source", "medium", "campaign", "term", "content"]) {
    const v = q.get(`utm_${key}`);
    if (v) utm[key] = v;
  }
  return {
    source_path: window.location.pathname,
    referrer: document.referrer || "",
    utm,
  };
}

export default function ContactForm({ locale }: { locale: Locale }) {
  const t = T[locale];
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string>("");

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setState("sending");
    setError("");

    const form = new FormData(e.currentTarget);
    const payload = {
      name: String(form.get("name") || ""),
      email: String(form.get("email") || ""),
      phone: String(form.get("phone") || ""),
      business: String(form.get("business") || ""),
      subject: String(form.get("subject") || "OTHER"),
      message: String(form.get("message") || ""),
      // Honeypot — hidden from people, irresistible to bots.
      website: String(form.get("website") || ""),
      ...attribution(),
    };

    try {
      const res = await fetch(`${API_BASE}/api/v1/leads/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        track("contact_submitted", { subject: payload.subject }, locale);
        setState("sent");
        return;
      }

      // Show the server's own field message when there is one — it is written
      // for the person, and guessing a friendlier wording here would only hide
      // what actually went wrong.
      if (res.status === 429) {
        setError(t.tooMany);
      } else {
        const data = await res.json().catch(() => null);
        const first =
          data && typeof data === "object"
            ? Object.values(data as Record<string, unknown>).flat()[0]
            : null;
        setError(typeof first === "string" ? first : t.failed);
      }
      setState("error");
    } catch {
      setError(t.offline);
      setState("error");
    }
  }

  if (state === "sent") {
    return (
      <div className="card" role="status" style={{ textAlign: "center" }}>
        <div className="icon-lg">✅</div>
        <h3 className="mt-sm">{t.sentTitle}</h3>
        <p className="muted mt-sm">
{t.sentBody}
        </p>
      </div>
    );
  }

  return (
    <form className="card" onSubmit={onSubmit} noValidate>
      <div className="grid g2">
        <label className="stack-sm">
          <span>{t.name} <span aria-hidden="true">*</span></span>
          <input name="name" required minLength={2} autoComplete="name" />
        </label>

        <label className="stack-sm">
          <span>{t.email} <span aria-hidden="true">*</span></span>
          <input name="email" type="email" required autoComplete="email" dir="ltr" />
        </label>

        <label className="stack-sm">
          <span>{t.phone}</span>
          <input name="phone" type="tel" autoComplete="tel" dir="ltr" />
        </label>

        <label className="stack-sm">
          <span>{t.business}</span>
          <input name="business" autoComplete="organization" />
        </label>
      </div>

      <label className="stack-sm mt-sm">
        <span>{t.subject}</span>
        <select name="subject" defaultValue="DEMO">
          {t.subjects.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </label>

      <label className="stack-sm mt-sm">
        <span>{t.message} <span aria-hidden="true">*</span></span>
        <textarea name="message" required minLength={10} rows={5} />
      </label>

      {/* Honeypot. Hidden from sight and from screen readers, and skipped by
          keyboard navigation — so no real person ever meets it. */}
      {/* تله‌ی ربات: انسان نمی‌بیندش، ربات پرش می‌کند. با `visually-hidden`
          نه `left:-9999px` — آن یکی در صفحه‌ی راست‌به‌چپ سند را ده هزار
          پیکسل پهن می‌کرد. */}
      <div aria-hidden="true" className="visually-hidden">
        <label>
          {t.honeypot}
          <input name="website" tabIndex={-1} autoComplete="off" />
        </label>
      </div>

      {state === "error" && (
        <p role="alert" className="mt-sm" style={{ color: "#dc2626" }}>
          {error}
        </p>
      )}

      <button
        type="submit"
        className="btn btn-primary mt-sm"
        disabled={state === "sending"}
      >
        {state === "sending" ? t.sending : t.send}
      </button>

      <p className="muted mt-sm" style={{ fontSize: ".85rem" }}>
        {t.privacy}
      </p>
    </form>
  );
}
