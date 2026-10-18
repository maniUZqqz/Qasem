import { FormEvent, useEffect, useState } from "react";

import Icon from "../../../components/Icon";
import { openTool } from "../../../components/Layout";
import { Alert, Badge, Button, Card, ErrorBox, Field, Input, Select } from "../../../components/ui";
import { api, studioError } from "./api";
import { Check, Help, Loading, SectionHead } from "./common";
import type { AiSettingsResp, AiSettingsT } from "./types";

const STEPS = [
  <>یک بار <b>فرانتِ اولیه</b> از توضیحِ فروشگاه ساخته می‌شود (هدر، فوتر، CSS، بدنهٔ صفحه‌ها).</>,
  <>بعد هر <b>صفحه جدا</b> ویرایش می‌شود؛ AI فقط همان بدنه را می‌بیند و می‌تواند عوض کند.</>,
  <>خروجی <b>وارسی</b> می‌شود (قالبِ جنگو سالم، تگِ ممنوع نه، نامِ URL درست).</>,
  <><b>Diff</b> و پیش‌نمایشِ قبل/بعد را می‌بینی و تأیید/رد می‌کنی.</>,
  <>بعد از اعمال، نسخه ثبت می‌شود و هر وقت خواستی <b>بازگردانی</b> می‌کنی.</>,
];

/** تنظیماتِ هوشِ مصنوعی — سرویس، نشانیِ پایه، کلید، مدل */
export default function AiSettingsPage() {
  const [data, setData] = useState<AiSettingsResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [temperature, setTemperature] = useState("0.3");
  const [maxTokens, setMaxTokens] = useState("6000");
  const [timeout, setTimeoutS] = useState("120");
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  function fill(s: AiSettingsT) {
    setProvider(s.provider);
    setModel(s.model);
    setBaseUrl(s.base_url);
    setTemperature(String(s.temperature));
    setMaxTokens(String(s.max_tokens));
    setTimeoutS(String(s.timeout_s));
    setApiKey("");
    setClearKey(false);
  }

  useEffect(() => {
    api
      .get<AiSettingsResp>("/studio/ai/settings/")
      .then((r) => {
        setData(r.data);
        fill(r.data);
      })
      .catch((err) => setError(studioError(err)));
  }, []);

  if (!data) return <Loading error={error} />;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy("save");
    setError(null);
    setNotice(null);
    try {
      const { data: d } = await api.post<AiSettingsT & { message: string }>("/studio/ai/settings/", {
        provider,
        model,
        base_url: baseUrl,
        api_key: apiKey,
        clear_key: clearKey,
        temperature,
        max_tokens: maxTokens,
        timeout_s: timeout,
      });
      setData({ ...data!, ...d });
      fill(d);
      setNotice({ ok: true, text: d.message });
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    setError(null);
    setNotice(null);
    try {
      const { data: d } = await api.post<{ ok: boolean; message: string }>("/studio/ai/settings/test/", {});
      setNotice({ ok: d.ok, text: d.message });
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
      <Card>
        <form onSubmit={save} className="space-y-4">
          <Alert
            tone="info"
            action={
              <Button type="button" variant="ghost" size="sm" onClick={() => openTool(data.admin_url)}>
                باز کردن در جنگو ادمین
              </Button>
            }
          >
            همین تنظیمات در <b>جنگو ادمین</b> هم هست (نشانیِ پایه، کلید/توکن، نامِ مدل).
          </Alert>
          <SectionHead
            title="سرویسِ هوشِ مصنوعی (کتابخانهٔ openai)"
            action={data.is_ready ? <Badge tone="ok">آماده</Badge> : <Badge tone="warn">کلید لازم است</Badge>}
          />
          <ErrorBox message={error} />
          {notice && <Alert tone={notice.ok ? "ok" : "bad"}>{notice.text}</Alert>}

          <div>
            <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
              سرویسِ آماده
            </span>
            <div className="flex flex-wrap gap-2">
              {data.presets.map(([name, prov, url, mdl]) => (
                <Button
                  key={name}
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setProvider(prov);
                    setBaseUrl(url);
                    setModel(mdl);
                  }}
                >
                  {name}
                </Button>
              ))}
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="نوعِ سرویس">
              <Select value={provider} onChange={(e) => setProvider(e.target.value)}>
                {data.providers.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="مدل">
              <Input value={model} onChange={(e) => setModel(e.target.value)} dir="ltr" />
            </Field>
          </div>
          <Field label="نشانیِ پایه (Base URL)">
            <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} dir="ltr" placeholder="https://api.openai.com/v1" />
          </Field>
          <Field label="کلیدِ API">
            <Input
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              dir="ltr"
              placeholder={data.has_key ? `ذخیره شده: ${data.masked_key} — خالی بگذار تا همان بماند` : "sk-…"}
            />
          </Field>
          {data.has_key && <Check label="کلیدِ ذخیره‌شده پاک شود" checked={clearKey} onChange={setClearKey} />}
          <Help>کلید فقط در دیتابیسِ استودیو روی همین سرور ذخیره می‌شود و هیچ‌جا کامل نمایش داده نمی‌شود.</Help>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="خلاقیت (0 تا 2)">
              <Input type="number" step="0.1" min={0} max={2} value={temperature} onChange={(e) => setTemperature(e.target.value)} dir="ltr" />
            </Field>
            <Field label="حداکثر توکنِ پاسخ">
              <Input type="number" min={256} value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} dir="ltr" />
            </Field>
            <Field label="مهلت (ثانیه)">
              <Input type="number" min={10} value={timeout} onChange={(e) => setTimeoutS(e.target.value)} dir="ltr" />
            </Field>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={busy !== null}>
              {busy === "save" ? "…" : "ذخیره"}
            </Button>
            <Button type="button" variant="secondary" onClick={test} disabled={busy !== null} title="با تنظیماتِ ذخیره‌شده">
              <Icon name="refresh" size={14} />
              {busy === "test" ? "در حالِ آزمون…" : "آزمونِ اتصال"}
            </Button>
          </div>
        </form>
      </Card>

      <div className="space-y-4">
        <Card>
          <SectionHead title="چطور کار می‌کند" />
          <ol className="space-y-2 text-sm leading-7" style={{ color: "var(--text-2)" }}>
            {STEPS.map((s, i) => (
              <li key={i} className="flex gap-3">
                <span
                  className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold"
                  style={{ background: "var(--brand-soft)", color: "var(--brand-strong)" }}
                >
                  {i + 1}
                </span>
                <span>{s}</span>
              </li>
            ))}
          </ol>
        </Card>
        <Card>
          <SectionHead title="سرویسِ آزمایشی" />
          <p className="text-sm leading-7" style={{ color: "var(--text-3)" }}>
            «آزمایشی» بدونِ اینترنت و کلید جواب‌های ثابت می‌دهد تا کلِ چرخه (پیشنهاد ⇒ Diff ⇒ اعمال ⇒ بازگردانی) را
            امتحان کنی. برای طراحیِ واقعی یک سرویسِ واقعی انتخاب کن.
          </p>
        </Card>
      </div>
    </div>
  );
}
