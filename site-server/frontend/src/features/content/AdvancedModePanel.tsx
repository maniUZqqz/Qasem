import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import { Alert, Badge, Button, Card, ErrorBox, SectionTitle, Spinner } from "../../components/ui";

type Requirement = {
  key: string;
  title: string;
  why: string;
  blocking: boolean;
  input: string;
  options: string[];
};

type Readiness = {
  kind: string;
  ready: boolean;
  blocking: Requirement[];
  improvements: Requirement[];
  advanced_worth_it: boolean;
};

const KINDS = [
  { key: "VIDEO", title: "ویدیو" },
  { key: "POSTER", title: "پوستر" },
  { key: "PRODUCT_SHOT", title: "عکس محصول" },
  { key: "CAPTION", title: "کپشن" },
];

/**
 * «حالت تولید پیشرفته». §25.
 *
 * Simple mode takes what the shop has and makes something. This asks first —
 * and the whole value is in *what* it asks. So every line shows the reason
 * underneath it: "this needs a photo" is ignored, "this needs a photo of the
 * sole, because the scene we planned shows the shoe from below" gets answered.
 *
 * Blocking and non-blocking are kept visually apart because they mean opposite
 * things. One stops the work; the other is "it will come out better if…", and
 * presenting them as one list turns an assistant into a gatekeeper.
 */
export default function AdvancedModePanel({ productId }: { productId: number }) {
  const [kind, setKind] = useState("VIDEO");
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/products/${productId}/readiness/?kind=${kind}`);
      setReadiness(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [productId, kind]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Card>
      <SectionTitle>حالت پیشرفته — چه چیزی کم است؟</SectionTitle>
      <ErrorBox message={error} />

      <div className="mb-3 flex flex-wrap gap-2">
        {KINDS.map((option) => (
          <Button
            key={option.key}
            variant={kind === option.key ? "primary" : "secondary"}
            onClick={() => setKind(option.key)}
          >
            {option.title}
          </Button>
        ))}
        <Button variant="ghost" onClick={load} disabled={loading}>
          بررسی دوباره
        </Button>
      </div>

      {loading || !readiness ? (
        <Spinner size={18} />
      ) : !readiness.advanced_worth_it ? (
        <Alert tone="ok" title="همه‌چیز هست">
          برای این خروجی چیزی کم ندارید — حالت ساده همین حالا بهترین نتیجه‌ای را
          که می‌شود می‌دهد.
        </Alert>
      ) : (
        <div className="flex flex-col gap-3">
          {readiness.blocking.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-bold" style={{ color: "var(--bad)" }}>
                بدون این‌ها نمی‌شود شروع کرد
              </p>
              <div className="flex flex-col gap-2">
                {readiness.blocking.map((requirement) => (
                  <div
                    key={requirement.key}
                    className="rounded-xl p-3"
                    style={{
                      border: "1px solid color-mix(in srgb, var(--bad) 35%, transparent)",
                    }}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="bad">لازم</Badge>
                      <span className="font-bold" style={{ color: "var(--text)" }}>
                        {requirement.title}
                      </span>
                    </div>
                    <p className="mt-1 text-sm leading-7" style={{ color: "var(--text-2)" }}>
                      {requirement.why}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {readiness.improvements.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-bold" style={{ color: "var(--text-2)" }}>
                این‌ها اجباری نیستند، ولی نتیجه را بهتر می‌کنند
              </p>
              <div className="flex flex-col gap-2">
                {readiness.improvements.map((requirement) => (
                  <div
                    key={requirement.key}
                    className="rounded-xl p-3"
                    style={{ border: "1px solid var(--line)" }}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="neutral">اختیاری</Badge>
                      <span className="font-bold" style={{ color: "var(--text)" }}>
                        {requirement.title}
                      </span>
                    </div>
                    <p className="mt-1 text-sm leading-7" style={{ color: "var(--text-2)" }}>
                      {requirement.why}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {readiness.ready && (
            <Alert tone="info">
              می‌توانید همین حالا بسازید — موارد بالا فقط کیفیت را بالاتر می‌برند.
            </Alert>
          )}
        </div>
      )}
    </Card>
  );
}
