import { useMemo, useState } from "react";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Field, Input, Select, TextArea, fa } from "../../../../components/ui";
import { g, problem } from "../../api";
import Modal from "../../components/Modal";
import { useFinder } from "../FinderLayout";
import type { Mission, MissionSpec, PresetInfo } from "../types";
import { joinList, splitList } from "./bits";

type FormState = {
  name: string;
  store_id: string;
  product: string;
  types: string[];
  keywords: string;
  cities: string;
  language: string;
  size: string;
  sources: Record<string, boolean>;
  directory_urls: string;
  execution: string;
  require_contact: boolean;
  min_score: string;
  max_results: string;
  exclude_words: string;
  tag: string;
  schedule_days: string;
  budget: { max_requests: string; max_sites: string; max_pages_per_site: string; max_minutes: string; domain_delay: string; max_search_queries: string };
  pitch: { brand: string; what: string; benefit: string; cta: string; sms: string };
};

const SCHEDULES = [
  { v: "0", l: "فقط وقتی خودم بزنم" },
  { v: "1", l: "هر روز" },
  { v: "7", l: "هر هفته" },
  { v: "14", l: "هر دو هفته" },
  { v: "30", l: "هر ماه" },
];

function fromSpec(spec: MissionSpec | undefined, mission?: Mission | null, preset?: PresetInfo | null, defaults?: Record<string, number>): FormState {
  const b = { ...(defaults ?? {}), ...(spec?.budget ?? {}) };
  return {
    name: mission?.name ?? preset?.name ?? "",
    store_id: String(mission?.store_id ?? preset?.store_id ?? ""),
    product: mission?.product ?? preset?.product ?? "nm",
    types: spec?.business_types ?? [],
    keywords: joinList(spec?.keywords),
    cities: joinList(spec?.cities),
    language: spec?.language ?? "fa",
    size: spec?.size ?? "any",
    sources: { osm: true, search: true, directory: true, website: true, instagram: false, neshan: false, ...(spec?.sources ?? {}) },
    directory_urls: (spec?.directory_urls ?? []).join("\n"),
    execution: spec?.execution ?? "auto",
    require_contact: spec?.require_contact ?? true,
    min_score: String(spec?.min_score ?? 0),
    max_results: String(spec?.max_results ?? 300),
    exclude_words: joinList(spec?.exclude_words),
    tag: spec?.tag ?? "",
    schedule_days: String(mission?.schedule_days ?? 0),
    budget: {
      max_requests: String(b.max_requests ?? 600),
      max_sites: String(b.max_sites ?? 60),
      max_pages_per_site: String(b.max_pages_per_site ?? 5),
      max_minutes: String(Math.round((b.max_seconds ?? 1500) / 60)),
      domain_delay: String(b.domain_delay ?? 2),
      max_search_queries: String(b.max_search_queries ?? 6),
    },
    pitch: { brand: spec?.pitch?.brand ?? "", what: spec?.pitch?.what ?? "", benefit: spec?.pitch?.benefit ?? "", cta: spec?.pitch?.cta ?? "", sms: spec?.pitch?.sms ?? "" },
  };
}

function toBody(f: FormState, extra: Record<string, unknown>) {
  const n = (s: string, d: number) => (Number.isFinite(Number(s)) && s.trim() !== "" ? Number(s) : d);
  const spec: Record<string, unknown> = {
    business_types: f.types,
    keywords: splitList(f.keywords),
    cities: splitList(f.cities),
    language: f.language,
    size: f.size,
    sources: f.sources,
    directory_urls: f.directory_urls.split("\n").map((s) => s.trim()).filter(Boolean),
    execution: f.execution,
    require_contact: f.require_contact,
    min_score: n(f.min_score, 0),
    max_results: n(f.max_results, 300),
    exclude_words: splitList(f.exclude_words),
    tag: f.tag.trim(),
    budget: {
      max_requests: n(f.budget.max_requests, 600),
      max_sites: n(f.budget.max_sites, 60),
      max_pages_per_site: n(f.budget.max_pages_per_site, 5),
      max_seconds: n(f.budget.max_minutes, 25) * 60,
      domain_delay: n(f.budget.domain_delay, 2),
      max_search_queries: n(f.budget.max_search_queries, 6),
    },
    pitch: Object.fromEntries(Object.entries(f.pitch).filter(([, v]) => v.trim())),
  };
  return { name: f.name.trim(), store_id: f.store_id ? Number(f.store_id) : null, product: f.product, schedule_days: n(f.schedule_days, 0), spec, ...extra };
}

/** Creating or editing a mission: whom to find (types, words, cities), from where, how big a crawl, how often, and what we say. */
export default function MissionForm({ open, mission, onClose, onSaved }: { open: boolean; mission: Mission | null; onClose: () => void; onSaved: (m: Mission, start: boolean) => void }) {
  const { meta } = useFinder();
  const [presetKey, setPresetKey] = useState("");
  const preset = meta?.presets.find((p) => p.key === presetKey) ?? null;
  const [form, setForm] = useState<FormState>(() => fromSpec(mission?.spec, mission, null, meta?.budget_defaults));
  const [typeQuery, setTypeQuery] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const pickPreset = (key: string) => {
    setPresetKey(key);
    const p = meta?.presets.find((x) => x.key === key);
    if (p) setForm(fromSpec(p.spec, null, p, meta?.budget_defaults));
  };
  const grouped = useMemo(() => {
    const q = typeQuery.trim();
    const groups: Record<string, { key: string; label: string }[]> = {};
    for (const t of meta?.types ?? []) {
      if (q && !t.label.includes(q) && !t.terms.some((x) => x.includes(q))) continue;
      (groups[t.group_label] ??= []).push({ key: t.key, label: t.label });
    }
    return groups;
  }, [meta, typeQuery]);

  const save = async (start: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const body = toBody(form, { preset_key: mission?.preset_key ?? presetKey });
      const saved = mission ? await g.patch<Mission>(`/finder/missions/${mission.id}/`, { name: body.name, schedule_days: body.schedule_days, spec: body.spec }) : await g.post<Mission>("/finder/missions/", body);
      onSaved(saved, start);
    } catch (err) {
      setError(problem(err).message);
    } finally {
      setBusy(false);
    }
  };

  const noNode = meta && !meta.node.crawl.known;
  return (
    <Modal
      open={open}
      title={mission ? "ویرایشِ مأموریت" : "مأموریتِ تازه"}
      onClose={onClose}
      size="xl"
      busy={busy}
      testId="mission-form"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            بستن
          </Button>
          <Button variant="secondary" onClick={() => save(false)} disabled={busy || !form.name.trim()} data-testid="mission-save">
            ذخیره
          </Button>
          {!mission && (
            <Button onClick={() => save(true)} disabled={busy || !form.name.trim()} data-testid="mission-save-run">
              <Icon name="play" size={14} />
              ذخیره و اجرا
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-5">
        {error && <Alert tone="bad">{error}</Alert>}
        {!mission && (
          <Field label="شروع از یک پیش‌تنظیم (اختیاری)" hint="پیش‌تنظیم همهٔ خانه‌ها را پر می‌کند؛ بعد می‌توانید هر چیز را عوض کنید.">
            <Select value={presetKey} onChange={(e) => pickPreset(e.target.value)} data-testid="preset-select">
              <option value="">— مأموریتِ دلخواه —</option>
              {meta?.presets.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="نامِ مأموریت">
            <Input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="مثلاً: باشگاه‌های تهران برای چغر" data-testid="mission-name" />
          </Field>
          <Field label="برای کدام فروشگاه؟" hint="فقط برای یادآوری؛ لحنِ پیام‌ها از «معرفیِ کوتاه» پایین می‌آید.">
            <Select value={form.store_id} onChange={(e) => set("store_id", e.target.value)}>
              <option value="">— هیچ‌کدام (عمومی) —</option>
              {meta?.stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <Field label="چه کسب‌وکاری را پیدا کنیم؟" hint="یک یا چند نوع؛ یا فقط کلیدواژه بنویسید.">
          <div className="space-y-2">
            <Input value={typeQuery} onChange={(e) => setTypeQuery(e.target.value)} placeholder="جست‌وجو در نوع‌ها: کافه، باشگاه، دندان…" data-testid="type-search" />
            <div className="max-h-52 space-y-2 overflow-auto rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid="type-picker">
              {Object.entries(grouped).map(([group, list]) => (
                <div key={group}>
                  <div className="mb-1 text-xs font-bold" style={{ color: "var(--text-3)" }}>
                    {group}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {list.map((t) => {
                      const on = form.types.includes(t.key);
                      return (
                        <button
                          key={t.key}
                          type="button"
                          className={`u-btn u-btn-sm ${on ? "u-btn-primary" : "u-btn-secondary"}`}
                          aria-pressed={on}
                          onClick={() => set("types", on ? form.types.filter((x) => x !== t.key) : [...form.types, t.key])}
                          data-testid={`type-${t.key}`}
                        >
                          {on && <Icon name="check" size={12} />}
                          {t.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
              {!Object.keys(grouped).length && (
                <span className="text-sm" style={{ color: "var(--text-3)" }}>
                  نوعی پیدا نشد؛ با کلیدواژه جست‌وجو می‌شود.
                </span>
              )}
            </div>
          </div>
        </Field>

        <div className="grid gap-4 md:grid-cols-2">
          <Field label="کلیدواژه‌ها" hint="با ویرگول جدا کنید؛ در جست‌وجو و در تطبیقِ نامِ سایت‌ها استفاده می‌شود.">
            <TextArea rows={2} value={form.keywords} onChange={(e) => set("keywords", e.target.value)} placeholder="مربی، برنامه تمرینی" data-testid="mission-keywords" />
          </Field>
          <Field label="شهرها (و محله‌ها)" hint="هر شهر جدا جست‌وجو می‌شود؛ مثلاً: تهران، اصفهان.">
            <TextArea rows={2} value={form.cities} onChange={(e) => set("cities", e.target.value)} placeholder="تهران" data-testid="mission-cities" />
          </Field>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Field label="زبانِ سایت/پیج">
            <Select value={form.language} onChange={(e) => set("language", e.target.value)}>
              <option value="fa">فارسی</option>
              <option value="en">انگلیسی</option>
              <option value="any">هر زبان</option>
            </Select>
          </Field>
          <Field label="اندازه" hint="فقط روی پیج‌های اینستاگرام (دنبال‌کننده) اثر دارد.">
            <Select value={form.size} onChange={(e) => set("size", e.target.value)}>
              <option value="any">مهم نیست</option>
              <option value="small">کوچک</option>
              <option value="large">بزرگ</option>
            </Select>
          </Field>
          <Field label="تکرارِ خودکار">
            <Select value={form.schedule_days} onChange={(e) => set("schedule_days", e.target.value)} data-testid="mission-schedule">
              {SCHEDULES.map((s) => (
                <option key={s.v} value={s.v}>
                  {s.l}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <Field label="منبع‌ها">
          <div className="grid gap-2 md:grid-cols-2">
            {meta?.sources.map((s) => (
              <label key={s.key} className="flex items-start gap-2 rounded-xl p-2.5 text-sm" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
                <input type="checkbox" className="mt-1" checked={!!form.sources[s.key]} onChange={(e) => set("sources", { ...form.sources, [s.key]: e.target.checked })} data-testid={`source-${s.key}`} />
                <span>
                  <span className="font-bold" style={{ color: "var(--text)" }}>
                    {s.label}
                  </span>
                  {s.needs_node && (
                    <span className="ms-1">
                      <Badge tone={meta.node.instagram.known ? "info" : "warn"}>سرورِ پردازش</Badge>
                    </span>
                  )}
                  {s.needs_key && (
                    <span className="ms-1">
                      <Badge tone="warn">کلید</Badge>
                    </span>
                  )}
                  <span className="block text-xs" style={{ color: "var(--text-3)" }}>
                    {s.help}
                  </span>
                </span>
              </label>
            ))}
          </div>
          {noNode && (
            <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
              {meta?.node.crawl.message}
            </p>
          )}
        </Field>

        <Field label="معرفیِ کوتاه برای پیام‌ها" hint="پیش‌نویس‌ها فقط از همین متن و نامِ خودِ کسب‌وکار ساخته می‌شوند؛ قیمت یا آمارِ ساختگی نمی‌آید. اگر خالی بماند از توضیحِ فروشگاه استفاده می‌شود.">
          <div className="grid gap-3 md:grid-cols-2">
            <Input value={form.pitch.brand} onChange={(e) => set("pitch", { ...form.pitch, brand: e.target.value })} placeholder="نامِ برند (مثلاً چغر)" data-testid="pitch-brand" />
            <Input value={form.pitch.sms} onChange={(e) => set("pitch", { ...form.pitch, sms: e.target.value })} placeholder="یک خطِ کوتاه برای پیامک" />
            <TextArea rows={3} value={form.pitch.what} onChange={(e) => set("pitch", { ...form.pitch, what: e.target.value })} placeholder="چیست؟ یک جمله" data-testid="pitch-what" />
            <TextArea rows={3} value={form.pitch.benefit} onChange={(e) => set("pitch", { ...form.pitch, benefit: e.target.value })} placeholder="چرا به درد این کسب‌وکار می‌خورد؟" />
            <TextArea rows={2} value={form.pitch.cta} onChange={(e) => set("pitch", { ...form.pitch, cta: e.target.value })} placeholder="یک درخواست از گیرنده" className="md:col-span-2" />
          </div>
        </Field>

        <div>
          <Button variant="ghost" size="sm" onClick={() => setAdvanced((v) => !v)} aria-expanded={advanced} data-testid="mission-advanced">
            <Icon name={advanced ? "up" : "down"} size={14} />
            تنظیماتِ پیشرفته (بودجه، فهرست‌ها، محلِ اجرا)
          </Button>
        </div>
        {advanced && (
          <div className="space-y-4 rounded-xl p-4" style={{ border: "1px solid var(--line)" }} data-testid="mission-advanced-body">
            <div className="grid gap-4 md:grid-cols-3">
              {(
                [
                  ["max_requests", "حداکثر درخواست"],
                  ["max_sites", "حداکثر سایت برای خواندن"],
                  ["max_pages_per_site", "صفحه از هر سایت"],
                  ["max_minutes", "حداکثر زمان (دقیقه)"],
                  ["domain_delay", "فاصلهٔ درخواست‌ها به یک سایت (ثانیه)"],
                  ["max_search_queries", "تعداد جست‌وجوی وب"],
                ] as const
              ).map(([k, label]) => (
                <Field key={k} label={label}>
                  <Input type="number" min={0} value={form.budget[k]} onChange={(e) => set("budget", { ...form.budget, [k]: e.target.value })} />
                </Field>
              ))}
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <Field label="محلِ اجرا" hint="خودکار: کارهای بزرگ و سایت‌های جاوااسکریپتی به سرورِ پردازش می‌روند.">
                <Select value={form.execution} onChange={(e) => set("execution", e.target.value)}>
                  <option value="auto">خودکار</option>
                  <option value="server">فقط همین سرور</option>
                  <option value="node">ترجیحاً سرورِ پردازش</option>
                </Select>
              </Field>
              <Field label="حداقلِ امتیازِ تناسب برای ساختنِ لید">
                <Input type="number" min={0} max={100} value={form.min_score} onChange={(e) => set("min_score", e.target.value)} />
              </Field>
              <Field label="حداکثرِ نتیجه">
                <Input type="number" min={10} max={2000} value={form.max_results} onChange={(e) => set("max_results", e.target.value)} />
              </Field>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.require_contact} onChange={(e) => set("require_contact", e.target.checked)} />
              فقط کسب‌وکارهایی که دست‌کم یک راهِ تماس دارند لید بشوند
            </label>
            <Field label="نشانیِ فهرست‌های دلخواه (هر خط یکی)" hint="صفحهٔ فهرستِ یک سایتِ عمومی؛ فقط اگر robots.txt اجازه بدهد خوانده می‌شود.">
              <TextArea rows={3} dir="ltr" value={form.directory_urls} onChange={(e) => set("directory_urls", e.target.value)} placeholder="https://example.ir/gyms" />
            </Field>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="کلمه‌های ردکننده در نام" hint="لیدی که نامش یکی از این‌ها را دارد ساخته نمی‌شود.">
                <Input value={form.exclude_words} onChange={(e) => set("exclude_words", e.target.value)} />
              </Field>
              <Field label="برچسبِ لیدها" hint="روی همهٔ لیدهای این مأموریت می‌نشیند.">
                <Input value={form.tag} maxLength={40} onChange={(e) => set("tag", e.target.value)} />
              </Field>
            </div>
          </div>
        )}
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          مأموریت فقط می‌خواند و لید می‌سازد؛ هیچ پیامی نمی‌فرستد. {meta ? `حداکثر ${fa(meta.budget_limits.max_requests?.max ?? 3000)} درخواست در هر اجرا.` : ""}
        </p>
      </div>
    </Modal>
  );
}
