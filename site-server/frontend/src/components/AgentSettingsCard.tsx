import { FormEvent, useEffect, useState } from "react";

import { api, errorMessage } from "../api/client";
import { Alert, Button, Card, Field, SectionTitle, Select, Skeleton, TextArea } from "./ui";

type Settings = {
  tone: string;
  tone_label: string;
  tone_instruction: string;
  custom_tone: string;
  always_say: string;
  never_say: string;
  sale_terms: string;
  limits: string;
  can_offer_discount: boolean;
  discount_policy: string;
  escalate_on_complaint: boolean;
};

type Payload = {
  settings: Settings;
  tones: { value: string; label: string }[];
  unbreakable: string[];
};

/**
 * How the sales agent talks for this store.
 *
 * The `unbreakable` list is shown before the fields, not after: an owner about
 * to type "always tell them the payment went through" should learn why that
 * will not happen while they are still deciding what to write.
 */
export default function AgentSettingsCard({ storeId }: { storeId: string | number }) {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [form, setForm] = useState<Settings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .get(`/stores/${storeId}/agent-settings/`)
      .then(({ data }) => {
        if (!alive) return;
        setPayload(data);
        setForm(data.settings);
      })
      .catch(() => alive && setPayload(null));
    return () => {
      alive = false;
    };
  }, [storeId]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const { data } = await api.patch(`/stores/${storeId}/agent-settings/`, form);
      setForm(data);
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (payload === null || form === null) return <Skeleton className="h-64" />;

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    setForm({ ...form, [key]: value });

  return (
    <Card>
      <SectionTitle>ایجنت فروش — لحن و قوانین</SectionTitle>

      <Alert tone="info" title="این‌ها را هیچ تنظیمی عوض نمی‌کند">
        {payload.unbreakable.map((line) => (
          <div key={line}>· {line}</div>
        ))}
      </Alert>

      <form onSubmit={save} className="mt-4 grid gap-4">
        <Field label="لحن">
          <Select value={form.tone} onChange={(e) => set("tone", e.target.value)}>
            {payload.tones.map((tone) => (
              <option key={tone.value} value={tone.value}>
                {tone.label}
              </option>
            ))}
          </Select>
        </Field>

        {form.tone === "CUSTOM" && (
          <Field label="لحن سفارشی را توضیح بده">
            <TextArea
              rows={2}
              value={form.custom_tone}
              onChange={(e) => set("custom_tone", e.target.value)}
              placeholder="مثلاً: کوتاه و بی‌تعارف، با اصطلاحات فنی."
            />
          </Field>
        )}

        <Field label="همیشه این‌ها را بگو">
          <TextArea
            rows={2}
            value={form.always_say}
            onChange={(e) => set("always_say", e.target.value)}
            placeholder="ارسال تهران همان‌روز · ضمانت اصالت کالا"
          />
        </Field>

        <Field label="هرگز این‌ها را نگو — هر خط یک عبارت">
          <TextArea
            rows={3}
            value={form.never_say}
            onChange={(e) => set("never_say", e.target.value)}
            placeholder={"ارزان‌ترین بازار\nتضمین می‌کنیم"}
          />
        </Field>
        <div className="-mt-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
          این عبارت‌ها فقط به مدل گفته نمی‌شوند — جواب تولیدشده هم بررسی می‌شود.
          اگر عبارت ممنوع در جواب بیاید، جواب رد می‌شود و اگر هیچ مدلی جواب سالم
          نداد، گفتگو به همکار انسانی می‌رسد.
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="شرایط فروش">
            <TextArea
              rows={2}
              value={form.sale_terms}
              onChange={(e) => set("sale_terms", e.target.value)}
            />
          </Field>
          <Field label="محدودیت‌ها">
            <TextArea
              rows={2}
              value={form.limits}
              onChange={(e) => set("limits", e.target.value)}
            />
          </Field>
        </div>

        <label className="flex items-start gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input
            type="checkbox"
            className="mt-1"
            checked={form.can_offer_discount}
            onChange={(e) => set("can_offer_discount", e.target.checked)}
          />
          <span>
            اجازه بده ایجنت تخفیف پیشنهاد کند
            <span className="block text-xs" style={{ color: "var(--text-3)" }}>
              خاموش یعنی سؤال تخفیف را به خودت ارجاع می‌دهد.
            </span>
          </span>
        </label>

        {form.can_offer_discount && (
          <Field label="سیاست تخفیف">
            <TextArea
              rows={2}
              value={form.discount_policy}
              onChange={(e) => set("discount_policy", e.target.value)}
              placeholder="بالای ۳ عدد، ۱۰٪"
            />
          </Field>
        )}

        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input
            type="checkbox"
            checked={form.escalate_on_complaint}
            onChange={(e) => set("escalate_on_complaint", e.target.checked)}
          />
          شکایت مشتری را به آدم ارجاع بده
        </label>

        {error && <Alert tone="bad">{error}</Alert>}
        {saved && <Alert tone="ok">ذخیره شد.</Alert>}

        <div>
          <Button type="submit" disabled={busy}>
            ذخیره‌ی قوانین
          </Button>
        </div>
      </form>
    </Card>
  );
}
