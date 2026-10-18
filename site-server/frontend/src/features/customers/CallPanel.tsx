import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
  ErrorBox,
  Field,
  Input,
  SectionTitle,
  Select,
  Spinner,
  TextArea,
  fa,
} from "../../components/ui";

/**
 * تماس‌های یک سرنخ — رضایت، ضبط، و آنچه از تماس درآمد.
 *
 * ترتیب اجزای این پنل خودش استدلال است: **اول رضایت، بعد فایل.** تا رضایت
 * ثبت نشود، دکمه‌ی آپلود اصلاً نیست — و اگر کسی مستقیم به API هم بزند،
 * `Recording.save` جلویش را می‌گیرد. قانون در مدل است نه در این صفحه، چون
 * قانونی که در صفحه باشد، قانونی است که تماس بعدی فراموشش می‌کند.
 *
 * «رضایت را دقیقاً چطور گرفتید» متن آزاد است و اجباری. یک تیکِ تنها چیزی
 * تولید می‌کند که از رضایتِ واقعاً گرفته‌شده قابل تشخیص نیست.
 */

type Consent = {
  granted: boolean;
  how: string;
  obtained_how: string;
  obtained_at: string;
  revoked_at: string | null;
  is_active: boolean;
};

/** How the call felt, as the analyser judged it. Worth a badge of its own:
 *  it is the one thing on a recording you can scan a whole week of calls by. */
const SENTIMENT: Record<string, { label: string; tone: "ok" | "bad" | "neutral" }> = {
  POSITIVE: { label: "مثبت", tone: "ok" },
  NEUTRAL: { label: "خنثی", tone: "neutral" },
  NEGATIVE: { label: "منفی", tone: "bad" },
};

type Recording = {
  id: number;
  happened_at: string;
  seconds: number;
  status: string;
  status_label: string;
  audio: string | null;
  transcript: string;
  summary: string;
  /** "POSITIVE" | "NEUTRAL" | "NEGATIVE", or "" when the analysis said nothing. */
  sentiment: string;
  objections: string[];
  commitments: string[];
  suggested_next: string;
  error: string;
};

type Prep = {
  prospect: Record<string, string | null>;
  objections: string[];
  commitments: string[];
  last_summary: string;
  call_count: number;
  known: { known: boolean; matches: { kind: string; name: string }[] };
};

export default function CallPanel({
  storeId,
  prospectId,
}: {
  storeId: string;
  prospectId: number;
}) {
  const base = `/stores/${storeId}/prospects/${prospectId}`;
  const [consent, setConsent] = useState<Consent | null>(null);
  const [hows, setHows] = useState<{ value: string; label: string }[]>([]);
  const [rule, setRule] = useState("");
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [mayRecord, setMayRecord] = useState(false);
  const [prep, setPrep] = useState<Prep | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ how: "VERBAL", obtained_how: "" });
  const file = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [c, r, p] = await Promise.all([
        api.get(`${base}/consent/`),
        api.get(`${base}/recordings/`),
        api.get<Prep>(`${base}/prep/`),
      ]);
      setConsent(c.data.consent);
      setHows(c.data.hows);
      setRule(c.data.rule);
      setRecordings(r.data.recordings);
      setMayRecord(r.data.may_record);
      setPrep(p.data);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [base]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!prep) return error ? <ErrorBox message={error} /> : <Spinner />;

  const grant = async () => {
    if (!form.obtained_how.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`${base}/consent/`, { granted: true, ...form });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    if (!window.confirm("رضایت پس گرفته شود؟ ضبط‌های قبلی می‌مانند ولی ضبط تازه‌ای انجام نمی‌شود.")) {
      return;
    }
    setBusy(true);
    try {
      await api.delete(`${base}/consent/`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const upload = async () => {
    const chosen = file.current?.files?.[0];
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("audio", chosen);
      await api.post(`${base}/recordings/`, body);
      if (file.current) file.current.value = "";
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 grid gap-4">
      <ErrorBox message={error} />

      {/* ------------------------------------------- قبل از شماره گرفتن */}
      <Card>
        <SectionTitle>قبل از تماس</SectionTitle>
        {prep.call_count === 0 && !prep.last_summary ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            هنوز تماسی ثبت نشده. بعد از اولین تماس، اینجا می‌نویسد چه گفت و به چه
            چیزی اعتراض داشت.
          </p>
        ) : (
          <div className="grid gap-3 text-sm">
            {prep.last_summary && (
              <div>
                <span style={{ color: "var(--text-3)" }}>آخرین تماس: </span>
                {prep.last_summary}
              </div>
            )}
            {prep.objections.length > 0 && (
              <div>
                <div className="mb-1" style={{ color: "var(--text-3)" }}>
                  قبلاً به این‌ها اعتراض داشت:
                </div>
                <ul className="grid gap-1">
                  {prep.objections.map((o) => (
                    <li key={o}>• {o}</li>
                  ))}
                </ul>
              </div>
            )}
            {prep.commitments.length > 0 && (
              <div>
                <div className="mb-1" style={{ color: "var(--text-3)" }}>
                  قول‌هایی که داده شد:
                </div>
                <ul className="grid gap-1">
                  {prep.commitments.map((c) => (
                    <li key={c}>• {c}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        {prep.known.known && (
          <p className="mt-3 text-xs" style={{ color: "var(--text-3)" }}>
            این شماره را از قبل می‌شناسیم:{" "}
            {prep.known.matches.map((m) => m.name).join("، ")}
          </p>
        )}
      </Card>

      {/* ------------------------------------------------------- رضایت */}
      <Card>
        <SectionTitle
          action={
            consent?.is_active ? (
              <Badge tone="ok">رضایت ثبت شده</Badge>
            ) : (
              <Badge tone="warn">رضایت ندارد</Badge>
            )
          }
        >
          رضایت ضبط
        </SectionTitle>

        {consent?.is_active ? (
          <div className="grid gap-2 text-sm">
            <div>
              <span style={{ color: "var(--text-3)" }}>چطور گرفته شد: </span>
              {consent.obtained_how}
            </div>
            <div style={{ color: "var(--text-3)" }}>
              {new Date(consent.obtained_at).toLocaleString("fa-IR")}
            </div>
            <div>
              <Button variant="ghost" onClick={revoke} disabled={busy}>
                پس گرفتن رضایت
              </Button>
            </div>
          </div>
        ) : (
          <>
            <Alert tone="info">{rule}</Alert>
            {consent?.revoked_at && (
              <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                رضایت در {new Date(consent.revoked_at).toLocaleDateString("fa-IR")} پس
                گرفته شد.
              </p>
            )}
            <div className="mt-4 grid gap-4">
              <Field label="چطور گرفته شد">
                <Select
                  value={form.how}
                  onChange={(e) => setForm({ ...form, how: e.target.value })}
                >
                  {hows.map((h) => (
                    <option key={h.value} value={h.value}>
                      {h.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field
                label="دقیقاً چطور"
                hint="مثلاً «اول تماس گفتم ضبط می‌کنم و گفت اشکالی ندارد». این متن می‌ماند."
              >
                <TextArea
                  rows={2}
                  value={form.obtained_how}
                  onChange={(e) => setForm({ ...form, obtained_how: e.target.value })}
                />
              </Field>
              <div>
                <Button onClick={grant} disabled={busy || !form.obtained_how.trim()}>
                  <Icon name="check" /> ثبت رضایت
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>

      {/* ------------------------------------------------------- تماس‌ها */}
      <Card>
        <SectionTitle>تماس‌های ضبط‌شده</SectionTitle>
        {mayRecord ? (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <input ref={file} type="file" accept="audio/*,video/*" className="text-sm" />
            <Button onClick={upload} disabled={busy}>
              <Icon name="upload" /> آپلود
            </Button>
            <span className="text-xs" style={{ color: "var(--text-3)" }}>
              متن و تحلیلش خودکار ساخته می‌شود.
            </span>
          </div>
        ) : (
          <p className="mb-4 text-sm" style={{ color: "var(--text-3)" }}>
            تا رضایت ثبت نشود، فایلی قابل آپلود نیست.
          </p>
        )}

        {recordings.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            هنوز تماسی ضبط نشده.
          </p>
        ) : (
          <div className="grid gap-3">
            {recordings.map((r) => (
              <div key={r.id} className="rounded-xl p-3" style={{ background: "var(--surface-2)" }}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm">
                    {new Date(r.happened_at).toLocaleString("fa-IR")}
                    {r.seconds > 0 && ` — ${fa(Math.round(r.seconds / 60))} دقیقه`}
                  </span>
                  <span className="flex items-center gap-2">
                    {SENTIMENT[r.sentiment] && (
                      <Badge tone={SENTIMENT[r.sentiment].tone}>{SENTIMENT[r.sentiment].label}</Badge>
                    )}
                    <Badge tone={r.status === "ANALYSED" ? "ok" : r.status === "FAILED" ? "bad" : "neutral"}>
                      {r.status_label}
                    </Badge>
                  </span>
                </div>
                {r.audio && (
                  <audio src={r.audio} controls className="mt-2 w-full" preload="none" />
                )}
                {r.error && (
                  <p className="mt-2 text-xs" style={{ color: "var(--warn)" }}>
                    {r.error}
                  </p>
                )}
                {r.summary && <p className="mt-2 text-sm">{r.summary}</p>}
                {r.objections.length > 0 && (
                  <p className="mt-2 text-xs" style={{ color: "var(--text-2)" }}>
                    اعتراض‌ها: {r.objections.join(" · ")}
                  </p>
                )}
                {r.commitments.length > 0 && (
                  <p className="mt-1 text-xs" style={{ color: "var(--text-2)" }}>
                    قول‌ها: {r.commitments.join(" · ")}
                  </p>
                )}
                {r.suggested_next && (
                  <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
                    پیشنهاد: {r.suggested_next}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
