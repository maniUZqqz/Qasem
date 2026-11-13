import { useState } from "react";

import { api, errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Alert, Button, Card, ErrorBox, Input, SectionTitle, Spinner } from "../../../components/ui";
import { sizeText, toFa, type AutoSettings } from "./nodeModels";

/**
 * «دانلودِ خودکار» — مدل‌هایی که قابلیتِ روشنِ پنل لازم دارد خودشان روی سرورِ پردازش می‌آیند (بی کلیک):
 * سایت می‌گوید چه چیزی، سرور تصمیم می‌گیرد کِی و جا می‌شود یا نه (دیسکِ آزاد منهای ذخیره؛ کوچک‌ها بلافاصله، بزرگ‌ها در بازهٔ شبانه؛
 * ادامه‌پذیر). فقط مدل‌های «تجاری مجاز» خودکار می‌شوند. هر سوئیچ همان لحظه ذخیره می‌شود (POST /compute/models/auto/).
 */
export default function AutoModelsCard({ auto, onChanged }: { auto: AutoSettings; onChanged: () => Promise<void> | void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reserve, setReserve] = useState<string>(String(auto.reserve_gb));

  const save = async (patch: Record<string, unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await api.post("/compute/models/auto/", patch);
      await onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const reserveNum = Number(reserve);
  const reserveOk = Number.isInteger(reserveNum) && reserveNum >= 5 && reserveNum <= 500;

  return (
    <Card>
      <SectionTitle>
        <span className="flex items-center gap-2" data-testid="auto-models">
          <Icon name="sparkle" size={16} /> دانلودِ خودکارِ مدل‌ها
        </span>
      </SectionTitle>
      <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
        قابلیتی را که می‌خواهید روشن کنید؛ مدل‌هایی که لازم دارد خودشان روی سرورِ پردازش می‌آیند. مدل‌های بزرگ (بیش از ۱٫۵ گیگابایت) فقط در
        بازهٔ شبانه گرفته می‌شوند، دانلود ادامه‌پذیر است و درستیِ هر فایل با sha256 سنجیده می‌شود. اگر دیسکِ سرور جا نداشته باشد دانلود
        شروع نمی‌شود و همین‌جا می‌گوید. مدل‌های «فقط غیرتجاری» و «با شرط» هرگز خودکار نیستند.
      </p>
      <ErrorBox message={error} />
      <div className="flex flex-col gap-3">
        <label className="flex cursor-pointer items-center gap-2 text-sm font-bold" style={{ color: "var(--text)" }}>
          <input
            type="checkbox"
            checked={auto.enabled}
            disabled={busy}
            onChange={(e) => void save({ enabled: e.target.checked })}
            data-testid="auto-master"
          />
          دانلودِ خودکار روشن باشد
          {busy && <Spinner size={13} />}
        </label>

        <ul className="flex flex-col gap-1.5">
          {auto.features.map((f) => (
            <li key={f.key} className="rounded-xl px-3 py-2" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
              <label className="flex cursor-pointer items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-1.5"
                  checked={f.on}
                  disabled={busy || !auto.enabled}
                  onChange={(e) => void save({ features: { [f.key]: e.target.checked } })}
                  data-testid={`auto-feature-${f.key}`}
                />
                <span className="min-w-0">
                  <span className="block font-bold" style={{ color: "var(--text)" }}>
                    {f.label}
                    {f.size_mb > 0 && (
                      <span className="mr-2 text-xs font-normal" style={{ color: "var(--text-3)" }}>
                        (حدودِ {sizeText(f.size_mb)})
                      </span>
                    )}
                  </span>
                  <span className="block text-xs leading-6" style={{ color: "var(--text-3)" }}>
                    {f.packages.length ? f.packages.map((p) => p.title).join(" · ") : "بستهٔ خودکاری ندارد"}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap items-end gap-2">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
              فضایی که همیشه روی دیسکِ سرور خالی بماند (گیگابایت)
            </span>
            <Input
              type="number"
              inputMode="numeric"
              min={5}
              max={500}
              value={reserve}
              onChange={(e) => setReserve(e.target.value)}
              style={{ width: 120 }}
              data-testid="auto-reserve"
            />
          </label>
          <Button
            variant="secondary"
            size="sm"
            disabled={busy || !reserveOk || reserveNum === auto.reserve_gb}
            onClick={() => void save({ reserve_gb: reserveNum })}
          >
            ذخیره
          </Button>
          {!reserveOk && (
            <span className="text-xs" style={{ color: "var(--warn)" }}>
              عددی بین ۵ و ۵۰۰ بنویسید.
            </span>
          )}
        </div>
        <Alert tone="info">
          الان {toFa(auto.wanted.length)} بسته خودکار خواسته شده است؛ وضعیتِ هر کدام کنارِ خودش در فهرستِ پایین نوشته می‌شود.
        </Alert>
      </div>
    </Card>
  );
}
