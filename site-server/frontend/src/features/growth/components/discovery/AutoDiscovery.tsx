import { useEffect, useMemo, useState } from "react";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, Field, Input, Select, fa } from "../../../../components/ui";
import { g, problem, useGet } from "../../api";
import { fieldErrorsOf } from "../../outreach/api";
import type { DiscoveryJob, DiscoveryProvider, SearchCheck } from "../../types";
import { LoadState } from "../bits";
import { Flash } from "../outreach/shared";
import ProviderDialog from "./ProviderDialog";

const COUNTRY_DEFAULT = "IR";

/**
 * «کشفِ خودکار»: ask a FREE, permitted source for businesses - the OpenStreetMap map (a category in a city) or, once the operator
 * has pasted a key, an official search API. The answer goes through the same duplicate / merge / provenance flow as a CSV file.
 * Nothing is scraped from Google, Instagram or the marketplaces.
 */
export default function AutoDiscovery({ onJobChange }: { onJobChange: (id: number) => void }) {
  const providers = useGet<{ providers: DiscoveryProvider[] }>("/discovery/providers/");
  const list = providers.data?.providers ?? [];
  const [key, setKey] = useState("osm");
  const provider = useMemo(() => list.find((p) => p.key === key) ?? list[0] ?? null, [list, key]);
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [city, setCity] = useState("");
  const [maxResults, setMaxResults] = useState("100");
  const [requireContact, setRequireContact] = useState(true);
  const [extractAfter, setExtractAfter] = useState(false);
  const [check, setCheck] = useState<SearchCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<ReturnType<typeof problem> | null>(null);
  const [dialog, setDialog] = useState<DiscoveryProvider | null>(null);
  const errors = fieldErrorsOf(error);

  useEffect(() => {
    if (!provider) return;
    setCheck(null);
    setError(null);
    setMaxResults(String(Math.min(provider.kind === "map" ? 100 : 20, provider.max_results_limit)));
    if (provider.kind === "map" && !category) setCategory(provider.categories[0]?.key ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider?.key]);

  if (!provider) {
    return (
      <LoadState loading={providers.loading} error={providers.error} onRetry={providers.reload}>
        <span />
      </LoadState>
    );
  }

  const map = provider.kind === "map";
  const body = () => ({
    provider: provider.key,
    category: map ? category : query.trim(),
    city: city.trim(),
    country: COUNTRY_DEFAULT,
    max_results: Number(maxResults) || 0,
    require_contact: requireContact,
    extract_after: extractAfter,
  });

  const runCheck = async () => {
    setChecking(true);
    setError(null);
    setCheck(null);
    try {
      setCheck(await g.post<SearchCheck>("/discovery/search/check/", body()));
    } catch (err) {
      setError(problem(err));
    } finally {
      setChecking(false);
    }
  };

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const job = await g.post<DiscoveryJob>("/discovery/search/", body());
      onJobChange(job.id);
    } catch (err) {
      setError(problem(err));
    } finally {
      setStarting(false);
    }
  };

  const ready = provider.ready && (map ? !!category && !!city.trim() : query.trim().length >= 2);
  return (
    <div className="space-y-4" data-testid="auto-discovery">
      <Alert tone="info" title="فقط از منبع‌های رایگان و مجاز">
        این‌جا فقط از نقشهٔ آزادِ OpenStreetMap (و، اگر خودتان کلید بدهید، از API رسمیِ Brave یا گوگل) کسب‌وکار پیدا می‌شود. هیچ صفحهٔ نتیجهٔ گوگل یا بینگ خوانده نمی‌شود، سراغِ اینستاگرام نمی‌رود و باسلام، دیجی‌کالا، ترب و دیوار را نمی‌خزد. بعد از پیدا شدن، هر مورد مثلِ یک ردیفِ CSV از «تکراری‌یاب» می‌گذرد؛ هیچ پیامی فرستاده نمی‌شود.
      </Alert>

      <div className="grid gap-3 md:grid-cols-3" role="radiogroup" aria-label="منبعِ کشف">
        {list.map((p) => {
          const active = p.key === provider.key;
          return (
            <div
              key={p.key}
              className="rounded-xl p-3"
              style={{ border: `1px solid ${active ? "var(--brand)" : "var(--line)"}`, background: active ? "var(--brand-soft)" : "var(--surface-2)" }}
              data-testid={`provider-${p.key}`}
              data-ready={p.ready ? "1" : "0"}
            >
              <button type="button" role="radio" aria-checked={active} onClick={() => setKey(p.key)} className="block w-full text-start" data-testid={`provider-pick-${p.key}`}>
                <div className="mb-1 flex flex-wrap items-center gap-2 font-bold" style={{ color: "var(--text)" }}>
                  {p.label}
                  {p.ready ? <Badge tone="ok">آماده</Badge> : p.needs_key && !Object.values(p.secrets).every((s) => s.is_set) ? <Badge tone="warn">کلید لازم است</Badge> : <Badge tone="neutral">خاموش</Badge>}
                </div>
                <p className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
                  {p.description}
                </p>
              </button>
              <div className="mt-2">
                <Button variant="ghost" size="sm" onClick={() => setDialog(p)} data-testid={`provider-settings-${p.key}`}>
                  <Icon name="settings" size={14} /> {p.needs_key ? "کلید و تنظیمات" : "تنظیمات"}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      <Card>
        <div className="space-y-4">
          {!provider.ready && (
            <Alert tone="warn" title={`«${provider.label}» هنوز آماده نیست`} action={<Button size="sm" variant="secondary" onClick={() => setDialog(provider)}>تنظیمات</Button>}>
              {provider.not_ready_reason}
            </Alert>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            {map ? (
              <Field label="دستهٔ کسب‌وکار">
                <Select value={category} onChange={(e) => setCategory(e.target.value)} data-testid="auto-category">
                  {provider.categories.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label}
                    </option>
                  ))}
                </Select>
                {errors.category && <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }}>{errors.category}</span>}
              </Field>
            ) : (
              <Field label="عبارتِ جست‌وجو" hint="مثلاً «فروشگاه لباس زنانه». شهر جدا نوشته می‌شود.">
                <Input value={query} onChange={(e) => setQuery(e.target.value)} maxLength={120} data-testid="auto-query" />
                {errors.category && <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }}>{errors.category}</span>}
              </Field>
            )}
            <Field label={map ? "شهر" : "شهر (اختیاری)"} hint={map ? "نام را فارسی یا انگلیسی بنویسید؛ پیش از شروع بررسی می‌شود." : undefined}>
              <Input value={city} onChange={(e) => setCity(e.target.value)} maxLength={100} placeholder="مثلاً همدان" data-testid="auto-city" />
              {errors.city && <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }}>{errors.city}</span>}
            </Field>
            <Field label="حداکثرِ تعدادِ نتیجه" hint={`برای این منبع تا ${fa(provider.max_results_limit)}`}>
              <Input type="number" min={1} max={provider.max_results_limit} value={maxResults} onChange={(e) => setMaxResults(e.target.value)} data-testid="auto-max" />
              {errors.max_results && <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }}>{errors.max_results}</span>}
            </Field>
            <div className="space-y-2 self-end pb-1">
              {map && (
                <label className="flex items-start gap-2 text-sm" style={{ color: "var(--text-2)" }}>
                  <input type="checkbox" className="mt-1" checked={requireContact} onChange={(e) => setRequireContact(e.target.checked)} data-testid="auto-require-contact" />
                  <span>فقط مواردی که دست‌کم یک راهِ تماس (سایت، تلفن، ایمیل یا پیج) دارند</span>
                </label>
              )}
              <label className="flex items-start gap-2 text-sm" style={{ color: "var(--text-2)" }}>
                <input type="checkbox" className="mt-1" checked={extractAfter} onChange={(e) => setExtractAfter(e.target.checked)} data-testid="auto-extract" />
                <span>بعد از پایان، راه‌های تماسِ لیدهای دارای سایت را از خودِ سایتشان هم بخوان</span>
              </label>
            </div>
          </div>

          {error && !errors.category && !errors.city && !errors.max_results && <Flash tone="bad">{error.message}</Flash>}
          {error && errors.provider && <Flash tone="bad">{errors.provider}</Flash>}
          {check && (
            <Alert tone="ok" title="آماده است" >
              <div data-testid="auto-check">
                <p>{check.summary}</p>
                {check.place && (
                  <p>
                    شهر روی نقشه: <b>{check.place.name}</b>{" "}
                    <a href={check.place.osm_url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--brand-strong)" }}>
                      (دیدن روی نقشه)
                    </a>
                    {check.place.cached ? " · از حافظه" : ""}
                  </p>
                )}
                {check.notes.map((n) => (
                  <p key={n} className="text-xs" style={{ color: "var(--text-3)" }}>
                    {n}
                  </p>
                ))}
              </div>
            </Alert>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {map && (
              <Button variant="secondary" onClick={runCheck} disabled={checking || !category || !city.trim()} data-testid="auto-check-btn">
                {checking ? "در حال بررسی…" : "بررسیِ شهر"}
              </Button>
            )}
            <Button onClick={start} disabled={!ready || starting} data-testid="auto-start">
              <Icon name="search" size={16} /> {starting ? "در حال شروع…" : "شروعِ کشف"}
            </Button>
          </div>

          {provider.attribution && (
            <p className="text-xs" style={{ color: "var(--text-3)" }} data-testid="auto-attribution">
              منبع:{" "}
              {provider.attribution_url ? (
                <a href={provider.attribution_url} target="_blank" rel="noopener noreferrer" dir="auto" style={{ color: "var(--brand-strong)" }}>
                  {provider.attribution}
                </a>
              ) : (
                provider.attribution
              )}
              {" "}— این نام کنارِ هر لیدی که از این راه بیاید در «منبعِ لید» می‌ماند.
            </p>
          )}
        </div>
      </Card>

      <ProviderDialog
        provider={dialog}
        onClose={() => setDialog(null)}
        onSaved={() => {
          setDialog(null);
          providers.reload();
        }}
      />
    </div>
  );
}
