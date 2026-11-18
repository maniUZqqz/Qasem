import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { api, errorMessage, recentApiFailures } from "../../api/client";
import { Alert, Button, ErrorBox, Spinner, TextArea, fa } from "../../components/ui";
import { loadVersion } from "../../components/VersionBadge";
import { useAuth } from "../auth/AuthContext";
import { registryPageFor } from "../panel/tabTitle";
import { BUG_EVENT, type BugSection, loadBugSections } from "./api";
import "./marketing.css";

/**
 * «گزارشِ ایراد» — دکمهٔ کوچکِ کنارِ قرصِ نسخه در هر صفحهٔ پنل.
 *
 * مالک هنگامِ آزمونِ بخش‌ها هر ایرادی دید همین‌جا می‌فرستد: بخش (پیش‌انتخاب از روی صفحه)، نشانی، یادداشت و عکسِ اختیاری
 * (فایل، چسباندن با Ctrl+V یا «گرفتنِ عکسِ صفحه»). همراهش بی‌زحمتِ او نسخهٔ نرم‌افزار، اندازهٔ صفحه و آخرین خطاهای API و جاوااسکریپتِ
 * همان صفحه هم ثبت می‌شود؛ همه روی سرور (`BugReport`) و با `manage.py bug_reports` خواندنی است.
 */

type Boxed = { at: number; text: string };
const jsErrors: Boxed[] = [];
let installed = false;

function installErrorCapture() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  const push = (text: string) => {
    jsErrors.push({ at: Date.now(), text: text.slice(0, 300) });
    if (jsErrors.length > 15) jsErrors.shift();
  };
  window.addEventListener("error", (e) => push(`${e.message} @ ${(e.filename || "").split("/").pop()}:${e.lineno}`));
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason as { message?: string } | string | undefined;
    push(`unhandled: ${typeof r === "string" ? r : r?.message ?? "rejection"}`);
  });
}
installErrorCapture();

function storeIdOf(pathname: string): number | null {
  const m = pathname.match(/^\/stores\/(\d+)/);
  return m ? Number(m[1]) : null;
}

async function captureScreen(): Promise<Blob> {
  const md = navigator.mediaDevices as MediaDevices & { getDisplayMedia?: (o?: unknown) => Promise<MediaStream> };
  if (!md?.getDisplayMedia) throw new Error("مرورگرِ شما گرفتنِ عکسِ صفحه را پشتیبانی نمی‌کند؛ عکس را فایل کنید یا با Ctrl+V بچسبانید.");
  const stream = await md.getDisplayMedia({ video: true, preferCurrentTab: true });
  try {
    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    await new Promise((r) => window.setTimeout(r, 250));
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("عکس ساخته نشد."))), "image/png"));
  } finally {
    stream.getTracks().forEach((t) => t.stop());
  }
}

export default function BugReportButton() {
  const { user } = useAuth();
  const { pathname, search } = useLocation();
  const lift = /\/shoot(\/|$)/.test(pathname);
  const [open, setOpen] = useState(false);
  const [sections, setSections] = useState<BugSection[]>([]);
  const [section, setSection] = useState("");
  const [note, setNote] = useState("");
  const [shot, setShot] = useState<Blob | null>(null);
  const [shotUrl, setShotUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const page = useMemo(() => registryPageFor(pathname), [pathname]);
  const guessSection = useCallback(
    (list: BugSection[]) => list.find((s) => page && s.covers.includes(page.key))?.key ?? "other",
    [page],
  );

  const show = useCallback(
    (detail?: { section?: string; note?: string }) => {
      setDone(null);
      setError(null);
      setNote(detail?.note ?? "");
      setOpen(true);
      if (detail?.section) setSection(detail.section);
    },
    [],
  );

  useEffect(() => {
    const on = (e: Event) => show((e as CustomEvent<{ section?: string; note?: string }>).detail);
    window.addEventListener(BUG_EVENT, on);
    return () => window.removeEventListener(BUG_EVENT, on);
  }, [show]);

  useEffect(() => {
    if (!open || sections.length) return;
    loadBugSections()
      .then((s) => setSections(s))
      .catch(() => setSections([{ key: "other", title: "جای دیگر / نامشخص", phase_title: "", covers: [] }]));
  }, [open, sections.length]);

  useEffect(() => {
    if (open && sections.length) setSection((cur) => (cur && sections.some((s) => s.key === cur) ? cur : guessSection(sections)));
  }, [open, sections, guessSection]);

  useEffect(() => {
    if (!shot) {
      setShotUrl(null);
      return;
    }
    const url = URL.createObjectURL(shot);
    setShotUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [shot]);

  // چسباندنِ عکس با Ctrl+V وقتی پنجره باز است
  useEffect(() => {
    if (!open) return;
    const onPaste = (e: ClipboardEvent) => {
      const f = Array.from(e.clipboardData?.files ?? []).find((x) => x.type.startsWith("image/"));
      if (f) setShot(f);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [open]);

  if (!user) return null;

  const close = () => {
    setOpen(false);
    setShot(null);
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (note.trim().length < 3) {
      setError("یادداشت را بنویسید (دست‌کم چند کلمه).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const v = await loadVersion();
      const context = {
        version: v?.version ?? "",
        ua: navigator.userAgent,
        viewport: `${window.innerWidth}×${window.innerHeight}`,
        theme: document.documentElement.getAttribute("data-theme") ?? "",
        lang: navigator.language,
        api_failures: recentApiFailures().slice(-10),
        errors: jsErrors.slice(-10).map((x) => x.text),
      };
      const form = new FormData();
      form.append("section", section || "other");
      form.append("page_key", page?.key ?? "");
      form.append("page_url", window.location.pathname + search);
      form.append("note", note.trim());
      form.append("context", JSON.stringify(context));
      const sid = storeIdOf(pathname);
      if (sid) form.append("store", String(sid));
      if (shot) form.append("screenshot", new File([shot], "screenshot.png", { type: shot.type || "image/png" }));
      const { data } = await api.post<{ report: { id: number } }>("/bug-reports/", form);
      setDone(data.report.id);
      setNote("");
      setShot(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const grab = async () => {
    setError(null);
    try {
      setShot(await captureScreen());
    } catch (err) {
      setError(err instanceof Error ? err.message : "عکس گرفته نشد.");
    }
  };

  return (
    <>
      <button
        type="button"
        className={`nm-ver nm-bug${lift ? " nm-ver--lift" : ""}`}
        onClick={() => show()}
        title="ایرادی دیدید؟ بخش، نشانی و یادداشت (و عکس) را برای ما بفرستید"
        aria-label="گزارشِ ایراد"
        data-testid="bug-report-button"
      >
        ایراد؟
      </button>
      {open && (
        <div className="bug-overlay" role="dialog" aria-modal="true" aria-label="گزارشِ ایراد" onMouseDown={(e) => e.target === e.currentTarget && close()}>
          <form className="bug-dialog" onSubmit={send}>
            <h2>گزارشِ ایراد</h2>
            {done !== null ? (
              <>
                <Alert tone="ok" title={`ثبت شد (شمارهٔ ${done})`}>
                  گزارش روی سرور ذخیره شد و برای رفعِ ایراد خوانده می‌شود. مرسی!
                </Alert>
                <div className="tg-row">
                  <Button type="button" onClick={() => show()}>
                    گزارشِ دیگر
                  </Button>
                  <Button type="button" variant="secondary" onClick={close}>
                    بستن
                  </Button>
                </div>
              </>
            ) : (
              <>
                <label className="bug-field">
                  کدام بخش؟
                  <select className="u-input" value={section} onChange={(e) => setSection(e.target.value)}>
                    {sections.length === 0 && <option value="">در حالِ بارگیری…</option>}
                    {Array.from(new Set(sections.map((s) => s.phase_title))).map((ph) => (
                      <optgroup key={ph || "other"} label={ph || "جای دیگر"}>
                        {sections
                          .filter((s) => s.phase_title === ph)
                          .map((s) => (
                            <option key={s.key} value={s.key}>
                              {s.title}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <label className="bug-field">
                  چه دیدید؟ چه انتظاری داشتید؟
                  <TextArea rows={5} value={note} onChange={(e) => setNote(e.target.value)} placeholder="مثلاً: دکمهٔ «رندر» را زدم، پیامِ خطای … آمد. انتظار داشتم …" autoFocus />
                </label>
                <div className="bug-field">
                  عکس (اختیاری)
                  <div className="tg-row">
                    <Button type="button" size="sm" variant="secondary" onClick={() => fileRef.current?.click()}>
                      انتخابِ فایل
                    </Button>
                    <Button type="button" size="sm" variant="secondary" onClick={grab}>
                      گرفتنِ عکسِ صفحه
                    </Button>
                    <span className="bug-ctx">یا با Ctrl+V عکس را همین‌جا بچسبانید</span>
                    {shot && (
                      <Button type="button" size="sm" variant="ghost" onClick={() => setShot(null)}>
                        حذفِ عکس
                      </Button>
                    )}
                  </div>
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    hidden
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) setShot(f);
                      e.target.value = "";
                    }}
                  />
                  {shotUrl && <img className="bug-shot" src={shotUrl} alt="پیش‌نمایشِ عکس" />}
                </div>
                <p className="bug-ctx">
                  همراهِ گزارش خودکار ثبت می‌شود: نشانیِ این صفحه (<bdi dir="ltr">{pathname}</bdi>)، نسخهٔ نرم‌افزار، اندازهٔ صفحه و آخرین خطاهای صفحه ({fa(recentApiFailures().length + jsErrors.length)} مورد).
                </p>
                <ErrorBox message={error} />
                <div className="tg-row">
                  <Button type="submit" disabled={busy}>
                    {busy ? <Spinner size={14} /> : null} ارسال
                  </Button>
                  <Button type="button" variant="secondary" onClick={close}>
                    انصراف
                  </Button>
                </div>
              </>
            )}
          </form>
        </div>
      )}
    </>
  );
}
