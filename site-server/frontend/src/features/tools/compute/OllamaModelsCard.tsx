import { useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, SectionTitle, Spinner } from "../../../components/ui";
import DownloadWhen from "./DownloadWhen";
import { activePulls, ollamaState, sizeText, toFa, type OllamaModel, type OllamaView } from "./nodeModels";
import { DEFAULT_WHEN, whenBody, whenError, whenValid, type WhenChoice } from "./schedule";

/**
 * «مدل‌های متن و بینایی (Ollama)» — همان فهرستِ مجازِ دانلودِ «موتورهای AI» اینجا کنارِ بسته‌های ComfyUI / Hugging Face
 * هم هست تا همهٔ دانلودها یک جا دیده شود. مدل‌هایی که مالک خودش نصب کرده (بیرون از فهرست) فقط نشان داده می‌شوند و دست‌نخورده می‌مانند.
 * دانلود: POST /ai/models/pull/ {tag, when} (فقط برچسب‌های فهرستِ مجاز)؛ لغو: POST /ai/models/pull/cancel/ {uid}.
 */
export default function OllamaModelsCard({
  ollama,
  onChanged,
  providersPage,
}: {
  ollama: OllamaView | undefined;
  onChanged: () => Promise<void> | void;
  providersPage: string;
}) {
  const [when, setWhen] = useState<WhenChoice>(DEFAULT_WHEN);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (!ollama) return null;
  const active = activePulls(ollama);
  const activeFor = (tag: string) => active.find((p) => p.tag === tag);
  const nodes = ollama.pull_nodes ?? [];
  const anyReady = nodes.some((n) => n.pull_ready);

  const pull = async (m: OllamaModel) => {
    if (!whenValid(when)) {
      setError(whenError(when));
      return;
    }
    const ask =
      `مدلِ ${m.label} حدود ${sizeText(m.size_mb)} است و روی سرورِ پردازش دانلود می‌شود.` +
      (nodes.some((n) => n.online) ? "" : "\nسرورِ پردازش الان خاموش است؛ دانلود در صف می‌ماند و همین که روشن شد شروع می‌شود.") +
      "\nشروع شود؟";
    if (!window.confirm(ask)) return;
    setBusy(`pull:${m.tag}`);
    setError(null);
    setNotice(null);
    try {
      const chosen = whenBody(when);
      const { data } = await api.post<{ message?: string }>("/ai/models/pull/", chosen ? { tag: m.tag, when: chosen } : { tag: m.tag });
      setNotice(data.message ?? "دانلود در صف گذاشته شد.");
      await onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const cancel = async (uid: string) => {
    setBusy(`cancel:${uid}`);
    setError(null);
    try {
      const { data } = await api.post<{ message?: string }>("/ai/models/pull/cancel/", { uid });
      setNotice(data.message ?? "لغو شد.");
      await onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <SectionTitle>
        <span className="flex items-center gap-2" data-testid="ollama-models" id="models-group-ollama" style={{ scrollMarginTop: 72 }}>
          <Icon name="chat" size={16} /> مدل‌های متن و بینایی (Ollama)
        </span>
      </SectionTitle>
      <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
        مدل‌های زبانی‌ای که چت، کپشن، تحلیل و کارگردانِ ویدیو با آن کار می‌کنند. انتخابِ مدلِ هر کار از{" "}
        <Link to={providersPage} className="underline" style={{ color: "var(--brand-strong)" }}>
          «موتورهای AI»
        </Link>{" "}
        است؛ دانلودشان اینجا هم هست. مدل‌های خودِ شما دست‌نخورده می‌مانند.
      </p>
      <ErrorBox message={error} />
      {ollama.error && <Alert tone="warn">{ollama.error}</Alert>}
      {nodes.length === 0 && <Alert tone="info">هنوز سرورِ پردازشی با Ollama ثبت نشده است.</Alert>}
      {nodes.length > 0 && !anyReady && (
        <Alert tone="warn" title="دانلودِ مدل هنوز روی سرور فعال نیست">
          نرم‌افزارِ سرور قدیمی است؛ Update.bat را روی آن اجرا کنید (یا از «سرورهای پردازش ▸ دستورها» به‌روزرسانی را بزنید).
        </Alert>
      )}

      <ul className="mt-3 flex flex-col gap-1.5">
        {ollama.models.map((m) => {
          const a = activeFor(m.tag);
          const v = ollamaState(m, a);
          return (
            <li
              key={m.tag}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2"
              style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
              data-testid={`ollama-row-${m.tag}`}
            >
              <span className="min-w-0 flex-1">
                <span className="block font-bold" style={{ color: "var(--text)" }}>
                  {m.label} {m.vision && <Badge tone="info">بینایی</Badge>}
                </span>
                {m.purpose && (
                  <span className="block text-xs leading-6" style={{ color: "var(--text-3)" }}>
                    {m.purpose}
                  </span>
                )}
                <span className="block text-xs" dir="ltr" style={{ color: "var(--text-3)", textAlign: "right" }}>
                  {m.tag}
                </span>
              </span>
              <span className="u-num text-xs" style={{ color: "var(--text-3)" }}>
                {sizeText(m.size_mb)}
              </span>
              <Badge tone={v.tone}>{v.label}</Badge>
              {a && !a.final && (
                <Button variant="ghost" size="sm" disabled={busy !== null} onClick={() => void cancel(a.uid)}>
                  لغو
                </Button>
              )}
              {!a && m.installed !== true && (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy !== null || nodes.length === 0 || !anyReady}
                  onClick={() => void pull(m)}
                  data-testid={`ollama-pull-${m.tag}`}
                >
                  {busy === `pull:${m.tag}` ? <Spinner size={13} /> : <Icon name="download" size={13} />} دانلود
                </Button>
              )}
            </li>
          );
        })}
        {(ollama.extra ?? []).map((m) => (
          <li
            key={m.tag}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2"
            style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
          >
            <span className="min-w-0 flex-1">
              <span className="block font-bold" dir="ltr" style={{ color: "var(--text)", textAlign: "right" }}>
                {m.label}
              </span>
              <span className="block text-xs leading-6" style={{ color: "var(--text-3)" }}>
                {m.purpose}
              </span>
            </span>
            <Badge tone="ok">نصب است</Badge>
          </li>
        ))}
      </ul>

      {active.length > 0 && (
        <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
          {toFa(active.length)} دانلود در راه است؛ پیشرفت در «صفِ پردازش» هم دیده می‌شود.
        </p>
      )}
      <div className="mt-3">
        <DownloadWhen value={when} onChange={setWhen} disabled={busy !== null} />
      </div>
      {notice && (
        <div className="mt-3">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}
    </Card>
  );
}
