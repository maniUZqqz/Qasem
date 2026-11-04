import { useEffect, useRef, useState } from "react";

import Icon from "../../../../components/Icon";
import { Alert, Button, Card, fa } from "../../../../components/ui";
import { g, problem } from "../../api";
import { useMeta } from "../../MetaContext";
import type { CsvCheck, CsvUpload, DiscoveryJob } from "../../types";
import { splitList } from "../leads/hooks";
import CsvMappingStep, { MappingState } from "./CsvMappingStep";
import CsvUploadStep from "./CsvUploadStep";
import JobPanel from "./JobPanel";

const IDENTIFYING = ["business_name", "website", "instagram", "phone", "email"];
const STEPS = ["آپلودِ فایل", "وصل کردنِ ستون‌ها", "تأیید", "ورود و گزارش"];

function Stepper({ current }: { current: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-x-4 gap-y-2" data-testid="csv-stepper" aria-label="مراحلِ ورود">
      {STEPS.map((label, i) => {
        const n = i + 1;
        const active = n === current;
        const done = n < current;
        return (
          <li key={label} className="flex items-center gap-2 text-sm" aria-current={active ? "step" : undefined}>
            <span
              className="u-num grid h-6 w-6 place-items-center rounded-full text-xs font-bold"
              style={{
                background: active ? "var(--brand)" : done ? "var(--ok-soft)" : "var(--surface-2)",
                color: active ? "#fff" : done ? "var(--ok)" : "var(--text-3)",
                border: "1px solid var(--line)",
              }}
            >
              {done ? <Icon name="check" size={12} /> : fa(n)}
            </span>
            <span style={{ color: active ? "var(--text)" : "var(--text-3)", fontWeight: active ? 700 : 500 }}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The CSV import in four steps. `jobId` (from the page's URL) decides step 4: when a job is set the wizard
 * shows its live progress and report; «ورودِ فایلِ تازه» clears it.
 */
export default function CsvWizard({ jobId, onJobChange }: { jobId: number | null; onJobChange: (id: number | null) => void }) {
  const { meta } = useMeta();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [upload, setUpload] = useState<CsvUpload | null>(null);
  const [state, setState] = useState<MappingState>({ mapping: {}, country: meta?.csv.default_country || "IR", city: "", tagsText: "", extractAfter: false });
  const [check, setCheck] = useState<CsvCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const seq = useRef(0);

  const patch = (p: Partial<MappingState>) => setState((s) => ({ ...s, ...p }));

  const onUploaded = (u: CsvUpload) => {
    setUpload(u);
    setState((s) => ({ ...s, mapping: { ...u.suggested_mapping } }));
    setCheck(null);
    setCheckError(null);
    setStep(2);
  };

  // live dry-run of every row whenever the mapping or the defaults change (debounced)
  const mappingKey = JSON.stringify([state.mapping, state.country, state.city]);
  useEffect(() => {
    if (step !== 2 || !upload) return;
    const identifying = Object.values(state.mapping).some((t) => IDENTIFYING.includes(t));
    if (!identifying) {
      setCheck(null);
      setCheckError("دست‌کم یکی از ستون‌ها را به «نام کسب‌وکار»، «وب‌سایت»، «اینستاگرام»، «تلفن» یا «ایمیل» وصل کنید.");
      return;
    }
    const mine = ++seq.current;
    setChecking(true);
    const timer = setTimeout(() => {
      g.post<CsvCheck>("/discovery/csv/check/", {
        upload_id: upload.upload_id,
        mapping: state.mapping,
        default_country: state.country,
        default_city: state.city,
      })
        .then((result) => {
          if (mine !== seq.current) return;
          setCheck(result);
          setCheckError(null);
        })
        .catch((err) => {
          if (mine !== seq.current) return;
          setCheck(null);
          setCheckError(problem(err).message);
        })
        .finally(() => {
          if (mine === seq.current) setChecking(false);
        });
    }, 450);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, upload, mappingKey]);

  const start = async () => {
    if (!upload || starting) return;
    setStarting(true);
    setStartError(null);
    try {
      const job = await g.post<DiscoveryJob>("/discovery/csv/import/", {
        upload_id: upload.upload_id,
        mapping: state.mapping,
        default_country: state.country,
        default_city: state.city,
        tags: splitList(state.tagsText),
        extract_after: state.extractAfter,
      });
      onJobChange(job.id);
    } catch (err) {
      setStartError(problem(err).message);
    } finally {
      setStarting(false);
    }
  };

  const fresh = () => {
    setUpload(null);
    setCheck(null);
    setCheckError(null);
    setStep(1);
    setState({ mapping: {}, country: meta?.csv.default_country || "IR", city: "", tagsText: "", extractAfter: false });
    onJobChange(null);
  };

  if (jobId !== null) {
    return (
      <div className="space-y-4" data-testid="csv-step-4">
        <Stepper current={4} />
        <JobPanel key={jobId} jobId={jobId} />
        <div>
          <Button variant="secondary" size="sm" onClick={fresh} data-testid="csv-new">
            <Icon name="plus" size={14} />
            ورودِ فایلِ تازه
          </Button>
        </div>
      </div>
    );
  }

  return (
    <Card>
      <div className="space-y-5">
        <Stepper current={step} />
        {step === 1 && <CsvUploadStep onUploaded={onUploaded} />}
        {step === 2 && upload && (
          <CsvMappingStep
            upload={upload}
            state={state}
            onChange={patch}
            check={check}
            checking={checking}
            checkError={checkError}
            onBack={fresh}
            onNext={() => setStep(3)}
          />
        )}
        {step === 3 && upload && (
          <div className="space-y-4" data-testid="csv-step-3">
            <h3 className="text-base font-bold" style={{ color: "var(--text)" }}>
              تأیید و شروعِ ورود
            </h3>
            <ul className="space-y-1.5 text-sm leading-7" style={{ color: "var(--text-2)" }}>
              <li>
                فایل: <b dir="auto">{upload.file_name}</b> · {fa(upload.total_rows)} ردیف
              </li>
              {check && (
                <li>
                  {fa(check.valid_rows)} ردیفِ سالم ثبت می‌شود{check.error_rows > 0 ? `؛ ${fa(check.error_rows)} ردیفِ خطادار ثبت نمی‌شود و در گزارش می‌آید` : ""}.
                </li>
              )}
              <li>
                ستون‌های وصل‌شده:{" "}
                {Object.entries(state.mapping)
                  .filter(([, t]) => t)
                  .map(([h, t]) => `${h} ← ${upload.targets.find((x) => x.key === t)?.label ?? t}`)
                  .join(" ، ")}
              </li>
              <li>
                کشورِ پیش‌فرض: {meta?.countries.find((c) => c.code === state.country)?.name ?? (state.country || "نامشخص")}
                {state.city ? ` · شهرِ پیش‌فرض: ${state.city}` : ""}
                {splitList(state.tagsText).length ? ` · برچسب: ${splitList(state.tagsText).join("، ")}` : ""}
              </li>
              {state.extractAfter && <li>پس از پایانِ ورود، راه‌های تماسِ لیدهای دارای سایت از خودِ سایتشان خوانده می‌شود.</li>}
            </ul>
            <Alert tone="info">
              ورود در پس‌زمینه انجام می‌شود و پیشرفتش را همین‌جا می‌بینید. تکراری‌ها خودکار ادغام نمی‌شوند؛ برای هرکدام تصمیم با شماست.
            </Alert>
            {startError && (
              <Alert tone="bad">
                <span data-testid="csv-start-error">{startError}</span>
              </Alert>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Button variant="secondary" onClick={() => setStep(2)} disabled={starting}>
                بازگشت
              </Button>
              <Button onClick={start} disabled={starting} data-testid="csv-start">
                {starting ? "در حال شروع…" : "شروعِ ورود"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
