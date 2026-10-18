import { useCallback, useEffect, useState } from "react";

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
import { Product } from "../../types";

/**
 * اتوماسیون و زمان‌بندی تولید محتوا — بند ۱ و بند آخرِ صفحه ۴.
 *
 * تا امروز هیچ‌جا نبود. `StoreProfile.publishing_preferences` یک ستون
 * JSON بود که هیچ‌کس نمی‌خواندش — یعنی چیزی که شبیه قابلیت است تا وقتی
 * دنبالش بگردی.
 *
 * دو چیز اینجا عمدی است:
 *
 * **پیش‌فرض، منتظر تأیید است.** کسی که ببیند در اینستاگرامش پستی رفته که
 * ندیده بود، تنظیمات را عوض نمی‌کند؛ محصول را کنار می‌گذارد.
 *
 * **«روشن» با «زمان‌بندی‌شده» یکی نیست.** اگر روشن باشد ولی هیچ روزی
 * انتخاب نشده باشد، صفحه همین را می‌گوید — وگرنه کسی یک هفته منتظر پستی
 * می‌ماند که قرار نبوده بیاید.
 *
 * جمله‌ی «یعنی چه» از بک‌اند می‌آید، نه از اینجا: برچسب و رفتار نباید دو
 * جا نوشته شوند.
 */

type Choice = { value: string; label: string };

type Settings = {
  enabled: boolean;
  mode: string;
  make_video: boolean;
  make_image: boolean;
  make_caption: boolean;
  image_mode: string;
  video_seconds: number;
  language: string;
  subtitles: boolean;
  owner_photo_ending: boolean;
  extra_prompt: string;
  publish_days: number[];
  publish_time: string;
  posts_per_run: number;
  product_ids: number[];
  approval: string;
  notify: boolean;
  last_run_at: string | null;
  segment_count: number;
  is_scheduled: boolean;
  summary: string;
  next_run: string | null;
};

type Payload = {
  settings: Settings;
  weekdays: { value: number; label: string }[];
  approvals: Choice[];
  image_modes: Choice[];
  modes: Choice[];
  video: { step: number; min: number; max: number; note: string };
  products: { id: number; name: string }[];
};

export default function AutomationSettings({
  storeId,
  products,
}: {
  storeId: string;
  /** Already loaded by the page; used so the picker is not a second request. */
  products: Product[];
}) {
  const [data, setData] = useState<Payload | null>(null);
  const [form, setForm] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get<Payload>(`/stores/${storeId}/content-automation/`);
      setData(res.data);
      setForm(res.data.settings);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data || !form) return error ? <ErrorBox message={error} /> : <Spinner />;

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setForm({ ...form, [key]: value });
    setSaved(false);
  };

  const toggleDay = (day: number) => {
    const days = form.publish_days.includes(day)
      ? form.publish_days.filter((d) => d !== day)
      : [...form.publish_days, day];
    set("publish_days", days);
  };

  const toggleProduct = (id: number) => {
    const ids = form.product_ids.includes(id)
      ? form.product_ids.filter((p) => p !== id)
      : [...form.product_ids, id];
    set("product_ids", ids);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const { data: fresh } = await api.patch<Settings>(
        `/stores/${storeId}/content-automation/`,
        form,
      );
      setForm(fresh);
      setData({ ...data, settings: fresh });
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const lengths: number[] = [];
  for (let s = data.video.min; s <= data.video.max; s += data.video.step) lengths.push(s);

  return (
    <div className="grid gap-4">
      <ErrorBox message={error} />

      {/* ----------------------------------------------- یعنی چه می‌شود */}
      <Alert tone={form.enabled ? (form.is_scheduled ? "ok" : "warn") : "neutral"}>
        {data.settings.summary}
        {data.settings.next_run && (
          <>
            {" "}
            نوبت بعدی: {new Date(data.settings.next_run).toLocaleString("fa-IR")}
          </>
        )}
      </Alert>

      {/* ------------------------------------------------------- روشن؟ */}
      <Card>
        <label className="flex cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => set("enabled", e.target.checked)}
            className="mt-1"
          />
          <span>
            <span className="font-bold">اتوماسیون روشن باشد</span>
            <span className="mt-1 block text-xs" style={{ color: "var(--text-3)" }}>
              خاموش که باشد هیچ‌چیز خودکار ساخته نمی‌شود — دکمه‌های همین صفحه دستی کار می‌کنند.
            </span>
          </span>
        </label>
      </Card>

      {/* --------------------------------------------------- چه چیزی */}
      <Card>
        <SectionTitle>چه چیزی ساخته شود</SectionTitle>
        <div className="mb-4 flex flex-wrap gap-4">
          {(
            [
              ["make_video", "ویدیو"],
              ["make_image", "عکس و پوستر"],
              ["make_caption", "کپشن"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form[key]}
                onChange={(e) => set(key, e.target.checked)}
              />
              {label}
            </label>
          ))}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Field label="حالت">
            <Select value={form.mode} onChange={(e) => set("mode", e.target.value)}>
              {data.modes.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
          </Field>

          {form.make_image && (
            <Field label="نوع تصویر">
              <Select
                value={form.image_mode}
                onChange={(e) => set("image_mode", e.target.value)}
              >
                {data.image_modes.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            </Field>
          )}

          {form.make_video && (
            <>
              <Field label="طول ویدیو" hint={data.video.note}>
                <Select
                  value={String(form.video_seconds)}
                  onChange={(e) => set("video_seconds", Number(e.target.value))}
                >
                  {lengths.map((s) => (
                    <option key={s} value={s}>
                      {fa(s)} ثانیه — {fa(s / data.video.step)} قطعه
                    </option>
                  ))}
                </Select>
              </Field>

              <Field label="زبان نریشن">
                <Select
                  value={form.language}
                  onChange={(e) => set("language", e.target.value)}
                >
                  <option value="fa">فارسی</option>
                  <option value="en">انگلیسی</option>
                </Select>
              </Field>
            </>
          )}
        </div>

        {form.make_video && (
          <div className="mt-4 flex flex-wrap gap-4">
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.subtitles}
                onChange={(e) => set("subtitles", e.target.checked)}
              />
              زیرنویس
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.owner_photo_ending}
                onChange={(e) => set("owner_photo_ending", e.target.checked)}
              />
              عکس واقعی خودم آخر ویدیو
            </label>
          </div>
        )}

        <div className="mt-4">
          <Field
            label="پرامپت تکمیلی"
            hint="هر بار به همه‌ی تولیدها اضافه می‌شود — مثلاً «زمینه‌ی روشن، بدون آدم»."
          >
            <TextArea
              rows={2}
              value={form.extra_prompt}
              onChange={(e) => set("extra_prompt", e.target.value)}
            />
          </Field>
        </div>
      </Card>

      {/* -------------------------------------------------------- کِی */}
      <Card>
        <SectionTitle>کِی</SectionTitle>
        <div className="mb-4">
          <span className="mb-2 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
            روزهای هفته
          </span>
          <div className="flex flex-wrap gap-2">
            {data.weekdays.map((d) => (
              <button
                key={d.value}
                type="button"
                onClick={() => toggleDay(d.value)}
                className="u-badge"
                style={{
                  cursor: "pointer",
                  background: form.publish_days.includes(d.value)
                    ? "var(--brand)"
                    : "var(--surface-2)",
                  color: form.publish_days.includes(d.value) ? "#fff" : "var(--text-2)",
                  border: "1px solid var(--line)",
                }}
                aria-pressed={form.publish_days.includes(d.value)}
              >
                {d.label}
              </button>
            ))}
          </div>
          {form.enabled && form.publish_days.length === 0 && (
            <p className="mt-2 text-xs" style={{ color: "var(--warn)" }}>
              هیچ روزی انتخاب نشده — با این تنظیم چیزی زمان‌بندی نمی‌شود.
            </p>
          )}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Field label="ساعت">
            <Input
              type="time"
              value={form.publish_time.slice(0, 5)}
              onChange={(e) => set("publish_time", `${e.target.value}:00`)}
            />
          </Field>
          <Field label="هر نوبت، چند محصول">
            <Input
              type="number"
              min={1}
              max={20}
              value={form.posts_per_run}
              onChange={(e) => set("posts_per_run", Number(e.target.value))}
            />
          </Field>
        </div>
      </Card>

      {/* --------------------------------------------- کدام محصول‌ها */}
      <Card>
        <SectionTitle
          action={
            form.product_ids.length > 0 && (
              <Button variant="ghost" onClick={() => set("product_ids", [])}>
                همه
              </Button>
            )
          }
        >
          کدام محصول‌ها
        </SectionTitle>
        <p className="mb-3 text-xs" style={{ color: "var(--text-3)" }}>
          {form.product_ids.length === 0
            ? "هیچ‌کدام انتخاب نشده، یعنی همه‌ی محصول‌ها — و محصولی که فردا اضافه کنید هم خودش وارد می‌شود."
            : `${fa(form.product_ids.length)} محصول انتخاب شده.`}
        </p>
        <div className="flex flex-wrap gap-2">
          {(data.products.length ? data.products : products).map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => toggleProduct(p.id)}
              className="u-badge"
              style={{
                cursor: "pointer",
                background: form.product_ids.includes(p.id)
                  ? "var(--brand)"
                  : "var(--surface-2)",
                color: form.product_ids.includes(p.id) ? "#fff" : "var(--text-2)",
                border: "1px solid var(--line)",
              }}
              aria-pressed={form.product_ids.includes(p.id)}
            >
              {p.name}
            </button>
          ))}
        </div>
      </Card>

      {/* ------------------------------------------------ بعدش چه شود */}
      <Card>
        <SectionTitle>وقتی آماده شد</SectionTitle>
        <div className="grid gap-3">
          {data.approvals.map((a) => (
            <label key={a.value} className="flex cursor-pointer items-start gap-3 text-sm">
              <input
                type="radio"
                name="approval"
                checked={form.approval === a.value}
                onChange={() => set("approval", a.value)}
                className="mt-1"
              />
              <span>
                {a.label}
                {a.value === "AUTO" && (
                  <span className="mr-2">
                    <Badge tone="warn">بدون دیدن شما منتشر می‌شود</Badge>
                  </span>
                )}
              </span>
            </label>
          ))}
        </div>
        <label className="mt-4 flex cursor-pointer items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.notify}
            onChange={(e) => set("notify", e.target.checked)}
          />
          وقتی آماده شد خبرم کن
        </label>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={saving}>
          <Icon name="check" /> {saving ? "ذخیره…" : "ذخیره‌ی تنظیمات"}
        </Button>
        {saved && <Badge tone="ok">ذخیره شد</Badge>}
        {form.last_run_at && (
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            آخرین اجرا: {new Date(form.last_run_at).toLocaleString("fa-IR")}
          </span>
        )}
      </div>
    </div>
  );
}
