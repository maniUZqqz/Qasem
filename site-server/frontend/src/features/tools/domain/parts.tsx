import { useEffect, useRef, useState, type ReactNode } from "react";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, SectionTitle } from "../../../components/ui";
import {
  certKind,
  daysText,
  daysTone,
  dnsLabel,
  dnsTone,
  fmtDate,
  fmtDateTime,
  issuerName,
  MODE_TEXT,
  modeTone,
  toFa,
  type CheckResult,
  type DomainStatus,
} from "./model";

/** رونوشتِ متن. روی نشانیِ بدونِ https `navigator.clipboard` نیست، پس روشِ قدیمی هم دارد. */
export function CopyButton({ text, label = "رونوشت" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );
  const copy = async () => {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
      document.body.appendChild(ta);
      ta.select();
      try {
        ok = document.execCommand("copy");
      } catch {
        ok = false;
      }
      document.body.removeChild(ta);
    }
    if (ok) {
      setDone(true);
      timer.current = window.setTimeout(() => setDone(false), 1600);
    }
  };
  return (
    <Button type="button" size="sm" variant="secondary" onClick={copy} aria-label={`${label}: ${text}`}>
      <span className="inline-flex items-center gap-1">
        <Icon name={done ? "check" : "copy"} size={14} />
        {done ? "رونوشت شد" : label}
      </span>
    </Button>
  );
}

/** دستورِ ترمینال: چپ‌به‌راست، با دکمهٔ رونوشت. */
export function CommandLine({ command, hint }: { command: string; hint?: string }) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <code
          dir="ltr"
          className="u-num rounded-lg px-3 py-2 text-sm"
          style={{ background: "var(--surface-2)", border: "1px solid var(--line)", color: "var(--text)", wordBreak: "break-all" }}
        >
          {command}
        </code>
        <CopyButton text={command} />
      </div>
      {hint && (
        <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
          {hint}
        </div>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-1.5">
      <div className="w-full shrink-0 text-sm sm:w-40" style={{ color: "var(--text-3)" }}>
        {label}
      </div>
      <div className="min-w-0 flex-1 text-sm" style={{ color: "var(--text)" }}>
        {children}
      </div>
    </div>
  );
}

const Ltr = ({ children }: { children: ReactNode }) => (
  <span dir="ltr" className="u-num" style={{ wordBreak: "break-all" }}>
    {children}
  </span>
);

/** کارتِ «وضعیتِ فعلی»: فقط IP، یا دامنه + گواهی (تاریخِ انقضا) + DNS + هشدارها. */
export function StatusCard({ status }: { status: DomainStatus }) {
  const { mode, cert, domain } = status;
  return (
    <Card>
      <SectionTitle action={<Badge tone={modeTone(mode)}>{MODE_TEXT[mode]}</Badge>}>وضعیتِ فعلی</SectionTitle>
      <div className="divide-y" style={{ borderColor: "var(--line)" }}>
        <Row label="نشانیِ عمومیِ NM">
          <Ltr>{status.public_base_url || "—"}</Ltr>
          <span className="mr-2 text-xs" style={{ color: "var(--text-3)" }}>
            (ویجتِ چت، وب‌هوک‌ها و لینک‌ها روی همین ساخته می‌شوند)
          </span>
        </Row>
        <Row label="نشانیِ IP">
          <Ltr>{status.ip_url}</Ltr>
          <span className="mr-2 text-xs" style={{ color: "var(--text-3)" }}>
            {mode === "ip_only" ? "تنها راهِ دسترسی؛ بدونِ رمزگذاری" : "همچنان کار می‌کند؛ سرورهای پردازش (GPU) با همین‌اند"}
          </span>
        </Row>
        {domain && (
          <>
            <Row label="دامنه">
              <Ltr>{domain.canonical}</Ltr>
              {domain.aliases.length > 0 && (
                <span className="mr-2 text-xs" style={{ color: "var(--text-3)" }}>
                  (<Ltr>{domain.aliases.join("، ")}</Ltr> به آن می‌رسد)
                </span>
              )}
            </Row>
            <Row label="گواهیِ https">
              {cert ? (
                <span className="inline-flex flex-wrap items-center gap-2">
                  <Badge tone={cert.staging || cert.self_signed ? "warn" : daysTone(cert.days_left)}>{daysText(cert.days_left)}</Badge>
                  <span>تا {fmtDate(cert.not_after)}</span>
                  <span className="text-xs" style={{ color: "var(--text-3)" }}>
                    {certKind(cert)} · {issuerName(cert.issuer)}
                  </span>
                </span>
              ) : (
                <Badge tone="bad">خوانده نشد</Badge>
              )}
            </Row>
            <Row label="تمدیدِ خودکار">گواهی ۳۰ روز مانده به انقضا خودش تمدید می‌شود (certbot.timer)؛ نیازی به کاری از شما نیست.</Row>
            <Row label="DNS">
              {status.dns ? (
                <span className="inline-flex flex-wrap items-center gap-2">
                  <Badge tone={dnsTone(status.dns.status)}>{dnsLabel(status.dns.status)}</Badge>
                  {status.dns.found.length > 0 && <Ltr>{status.dns.found.join(" ")}</Ltr>}
                </span>
              ) : (
                "—"
              )}
            </Row>
            <Row label="تنظیم‌شده در">{fmtDateTime(domain.applied_at)}</Row>
          </>
        )}
      </div>
      {status.warnings.length > 0 && (
        <div className="mt-4 space-y-2">
          {status.warnings.map((w) => (
            <Alert key={w} tone="warn">
              {w}
            </Alert>
          ))}
        </div>
      )}
      {mode === "ip_only" && (
        <div className="mt-4">
          <Alert tone="info" title="هنوز دامنه‌ای وصل نشده">
            با نشانیِ IP ویجتِ چت روی سایت‌های https (مثل چغر) نشان داده نمی‌شود و ربات‌های بله، ایتا و روبیکا وب‌هوکِ http نمی‌پذیرند. با وصل‌کردنِ دامنه
            همه‌چیز خودکار درست می‌شود؛ پایین ببینید چه کنید.
          </Alert>
        </div>
      )}
      {status.configured && status.rollback_command && (
        <div className="mt-4 space-y-3">
          <CommandLine command={status.status_command ?? ""} hint="وضعیتِ کاملِ دامنه، گواهی و DNS روی سرور" />
          <CommandLine command={status.rollback_command} hint="برگرداندنِ همه‌چیز به حالتِ پیش از دامنه (گواهی می‌ماند)" />
        </div>
      )}
    </Card>
  );
}

/** نتیجهٔ «بررسیِ DNS»: برای هر نام یک ردیف، و اگر درست نیست چه رکوردی بسازید؛ اگر درست است دستورِ نهایی. */
export function CheckResultView({ result }: { result: CheckResult }) {
  return (
    <div className="mt-4 space-y-4">
      <div className="space-y-2">
        {result.reports.map((r) => (
          <div key={r.name} className="rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={dnsTone(r.status)}>{dnsLabel(r.status)}</Badge>
              <Ltr>{r.name}</Ltr>
            </div>
            <div className="mt-1 text-sm" style={{ color: "var(--text-2)" }}>
              {r.message}
            </div>
            {Object.keys(r.a).length > 0 && (
              <div className="mt-2 grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-2" style={{ color: "var(--text-3)" }}>
                {Object.entries(r.a).map(([src, ips]) => (
                  <div key={src} className="flex gap-2">
                    <span className="w-24 shrink-0">{src === "authoritative" ? "سرورِ اصلیِ DNS" : src === "system" ? "DNSِ سرور" : src}</span>
                    <Ltr>{ips.length ? ips.join(" ") : "—"}</Ltr>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      {result.ok ? (
        <Alert tone="ok" title="DNS آماده است">
          <div className="space-y-3">
            <div>همین یک دستور را روی سرور اجرا کنید (یا فقط نامِ دامنه را برای ما بفرستید تا اجرا کنیم). اول بدونِ تغییر امتحان کنید:</div>
            <CommandLine command={result.dry_command} hint="پیش‌نمایش؛ هیچ چیز عوض نمی‌شود" />
            <CommandLine command={result.command} hint="اجرای واقعی: گواهیِ https، تنظیمِ NM و سنجشِ نهایی؛ اگر چیزی خراب شود خودش همه‌چیز را برمی‌گرداند" />
          </div>
        </Alert>
      ) : (
        <Alert tone="warn" title="این رکوردها را در پنلِ DNS بسازید">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" style={{ minWidth: 360 }}>
              <thead>
                <tr style={{ color: "var(--text-3)" }}>
                  <th className="py-1 text-right font-medium">نوع</th>
                  <th className="py-1 text-right font-medium">نام (Host)</th>
                  <th className="py-1 text-right font-medium">مقدار</th>
                  <th className="py-1 text-right font-medium">TTL</th>
                </tr>
              </thead>
              <tbody>
                {result.records.map((rec) => (
                  <tr key={`${rec.type}-${rec.name}`}>
                    <td className="py-1">
                      <Ltr>{rec.type}</Ltr>
                    </td>
                    <td className="py-1">
                      <Ltr>{rec.name}</Ltr>
                    </td>
                    <td className="py-1">
                      <span className="inline-flex items-center gap-2">
                        <Ltr>{rec.value}</Ltr>
                        <CopyButton text={rec.value} />
                      </span>
                    </td>
                    <td className="py-1">{toFa(rec.ttl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Alert>
      )}
    </div>
  );
}

/** «چه کنم و چه بدهم؟» — قدم‌به‌قدمِ ثبت‌کنندهٔ دامنهٔ ایرانی (.ir). */
export function StepsCard({ ip }: { ip: string }) {
  const steps: { title: string; body: ReactNode }[] = [
    {
      title: "پنلِ ثبت‌کنندهٔ دامنه را باز کنید",
      body: "همان‌جایی که دامنهٔ .ir را گرفته‌اید (نمایندهٔ ثبتِ نیک‌.آی‌آر یا هر شرکتی که دامنه را از آن خریده‌اید) ⇐ «مدیریتِ DNS» یا «رکوردها».",
    },
    {
      title: "دو رکوردِ A بسازید",
      body: (
        <>
          نامِ <Ltr>@</Ltr> (یعنی خودِ دامنه) و نامِ <Ltr>www</Ltr>، هر دو با مقدارِ <Ltr>{ip}</Ltr>. اگر از قبل رکوردِ A یا AAAA دیگری برای این دو نام هست پاک
          یا عوضش کنید. TTL را کم (۳۶۰۰ یا کمتر) بگذارید تا زود پخش شود.
        </>
      ),
    },
    {
      title: "منتظر بمانید و بسنجید",
      body: "معمولاً ۵ تا ۶۰ دقیقه (گاهی تا ۲۴ ساعت). بالا نامِ دامنه را بنویسید و «بررسیِ DNS» را بزنید؛ وقتی سبز شد آماده‌اید.",
    },
    {
      title: "فقط نامِ دامنه را به ما بدهید",
      body: "چیزِ دیگری لازم نیست: نه رمز، نه فایل، نه سرویسِ خارجی. با یک دستور گواهیِ https گرفته می‌شود، NM و ویجت و وب‌هوک‌ها روی دامنه می‌روند و تمدیدِ گواهی خودکار می‌شود.",
    },
  ];
  return (
    <Card>
      <SectionTitle>چه کنم و چه بدهم؟</SectionTitle>
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={s.title} className="flex gap-3">
            <span
              className="u-num flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold"
              style={{ background: "var(--brand-soft, var(--surface-2))", color: "var(--brand)" }}
            >
              {toFa(i + 1)}
            </span>
            <div>
              <div className="text-sm font-bold" style={{ color: "var(--text)" }}>
                {s.title}
              </div>
              <div className="mt-0.5 text-sm" style={{ color: "var(--text-2)" }}>
                {s.body}
              </div>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-4 space-y-2 text-xs" style={{ color: "var(--text-3)" }}>
        <div>دامنهٔ ایرانی (.ir) به هیچ سرویسِ خارجی نیاز ندارد؛ گواهیِ رایگانِ Let&apos;s Encrypt مستقیم از همین سرور گرفته می‌شود.</div>
        <div>
          اختیاری: اگر می‌خواهید سایت از پشتِ CDNِ ایرانی (مثلِ آروان‌کلاود) بیاید، DNS را روی آروان بگذارید؛ ابتدا گواهی را بگیریم و بعد ابرِ CDN را روشن
          کنید (یا با گزینهٔ --self-signed پشتِ CDN راه بیندازیم).
        </div>
      </div>
    </Card>
  );
}
