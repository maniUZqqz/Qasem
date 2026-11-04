import { FormEvent, useEffect, useState } from "react";

import { Alert, Badge, Button, Field, Input } from "../../../../components/ui";
import { g } from "../../api";
import { useAction } from "../../outreach/api";
import type { DiscoveryProvider } from "../../types";
import Modal from "../Modal";
import { Flash } from "../outreach/shared";

/**
 * The settings of one discovery provider: on / off, its non-secret settings (mirrors, daily cap) and its API keys.
 * A key is written here and never shown again: the box stays empty and the badge says only that one is stored.
 */
export default function ProviderDialog({ provider, onClose, onSaved }: { provider: DiscoveryProvider | null; onClose: () => void; onSaved: (p: DiscoveryProvider) => void }) {
  const [enabled, setEnabled] = useState(false);
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [clear, setClear] = useState<string[]>([]);
  const save = useAction();

  useEffect(() => {
    if (!provider) return;
    setEnabled(provider.enabled);
    const values: Record<string, string> = {};
    for (const s of provider.settings_schema) {
      const v = provider.settings[s.name];
      values[s.name] = Array.isArray(v) ? v.join("\n") : v === undefined || v === null ? "" : String(v);
    }
    setSettings(values);
    setSecrets({});
    setClear([]);
    save.clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider]);

  if (!provider) return null;
  const secretNames = Object.keys(provider.secrets);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    // a key being removed (and not replaced) leaves nothing to run on: send "off" rather than a switch the server must refuse
    const keyless = clear.some((name) => !(secrets[name] ?? "").trim());
    const body: Record<string, unknown> = { enabled: provider.needs_key && keyless ? false : enabled, settings: {} as Record<string, unknown>, secrets: {} as Record<string, string> };
    for (const s of provider.settings_schema) {
      const raw = settings[s.name] ?? "";
      (body.settings as Record<string, unknown>)[s.name] = s.type === "lines" ? raw.split("\n").map((x) => x.trim()).filter(Boolean) : s.type === "int" ? Number(raw) : raw.trim();
    }
    for (const [name, value] of Object.entries(secrets)) if (value.trim()) (body.secrets as Record<string, string>)[name] = value.trim();
    if (clear.length) body.clear_secrets = clear;
    const done = await save.run(() => g.patch<DiscoveryProvider>(`/discovery/providers/${provider.key}/`, body));
    if (done) onSaved(done);
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`تنظیماتِ «${provider.label}»`}
      size="lg"
      busy={save.busy}
      testId="provider-dialog"
      footer={
        <>
          <Button variant="secondary" type="button" onClick={onClose} disabled={save.busy}>
            انصراف
          </Button>
          <Button type="submit" form="provider-form" disabled={save.busy} data-testid="provider-save">
            {save.busy ? "در حال ذخیره…" : "ذخیره"}
          </Button>
        </>
      }
    >
      <form id="provider-form" onSubmit={submit} className="space-y-4">
        <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
          {provider.description}
        </p>
        {provider.license_note && (
          <Alert tone="info" title="شرایطِ استفاده">
            {provider.license_note}
          </Alert>
        )}

        {provider.needs_key ? (
          <div className="space-y-3">
            {secretNames.map((name) => {
              const secret = provider.secrets[name];
              const cleared = clear.includes(name);
              return (
                <div key={name} className="space-y-1.5">
                  <Field label={secret.label} hint={secret.is_set && !cleared ? "کلید ذخیره شده است و هرگز دوباره نشان داده نمی‌شود. فقط برای عوض‌کردن چیزی بنویسید." : "کلید را از پنلِ همان سرویس کپی کنید و اینجا بچسبانید. فقط در پایگاه دادهٔ سرور می‌ماند."}>
                    <Input type="password" autoComplete="new-password" dir="ltr" value={secrets[name] ?? ""} onChange={(e) => setSecrets((s) => ({ ...s, [name]: e.target.value }))} placeholder={secret.is_set && !cleared ? "••••••••  (ذخیره شده)" : ""} data-testid={`secret-${name}`} />
                  </Field>
                  {secret.is_set && (
                    <label className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-2)" }}>
                      <input type="checkbox" checked={cleared} onChange={(e) => setClear((c) => (e.target.checked ? [...c, name] : c.filter((n) => n !== name)))} />
                      کلیدِ ذخیره‌شده پاک شود
                    </label>
                  )}
                </div>
              );
            })}
            <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} data-testid="provider-enabled" />
              روشن باشد (فقط وقتی کلید وارد شده باشد روشن می‌شود)
            </label>
            {provider.usage_today !== undefined && (
              <p className="text-xs" style={{ color: "var(--text-3)" }}>
                امروز {provider.usage_today} درخواست از سقفِ {provider.daily_cap} مصرف شد.
              </p>
            )}
          </div>
        ) : (
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} data-testid="provider-enabled" />
            روشن باشد
          </label>
        )}

        {provider.settings_schema.map((s) => (
          <Field key={s.name} label={s.label} hint={s.help}>
            {s.type === "lines" ? (
              <textarea className="u-input" rows={3} dir="ltr" value={settings[s.name] ?? ""} onChange={(e) => setSettings((v) => ({ ...v, [s.name]: e.target.value }))} data-testid={`setting-${s.name}`} />
            ) : (
              <Input type={s.type === "int" ? "number" : "text"} dir={s.type === "url" ? "ltr" : undefined} value={settings[s.name] ?? ""} onChange={(e) => setSettings((v) => ({ ...v, [s.name]: e.target.value }))} data-testid={`setting-${s.name}`} />
            )}
          </Field>
        ))}

        <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-3)" }}>
          وضعیتِ فعلی: <Badge tone={provider.ready ? "ok" : "warn"}>{provider.ready ? "آماده" : provider.not_ready_reason || "آماده نیست"}</Badge>
        </div>
        {save.error && <Flash tone="bad">{save.error.message}</Flash>}
      </form>
    </Modal>
  );
}
