import { useCallback, useEffect, useState } from "react";

import { Alert, Button, Card, ErrorBox } from "../../../components/ui";
import { api, studioError } from "./api";
import { Loading, SectionHead } from "./common";

type RouteResp = {
  mode: "qwen_first" | "metis_only";
  node: { model: string; online: boolean; ready: boolean; has_model: boolean | null; node: string; known_models: string[]; reason: string };
  recent: { task: string; model: string; via: string; fell_back: boolean; reason: string; seconds: number; at: string }[];
  claim_timeout: number;
  run_timeout: number;
};

/** کارهای متن و کد کجا انجام شوند: سرورِ پردازش یا Metis */
export default function AiRouteCard() {
  const [data, setData] = useState<RouteResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .get<RouteResp>("/studio/ai/route/")
      .then((r) => setData(r.data))
      .catch((err) => setError(studioError(err)));
  }, []);
  useEffect(load, [load]);

  if (!data) return <Card><Loading error={error} /></Card>;

  async function choose(mode: RouteResp["mode"]) {
    setBusy(true);
    setError(null);
    try {
      const { data: d } = await api.post<RouteResp>("/studio/ai/route/", { mode });
      setData(d);
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }
  async function pull() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data: d } = await api.post<{ message: string }>("/studio/ai/route/pull/", {});
      setNotice(d.message);
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  const n = data.node;
  const missing = n.has_model === false;
  return (
    <Card>
      <div className="space-y-3" data-testid="ai-route">
        <SectionHead title="کارهای متن و کد کجا انجام شوند؟" hint="ساختنِ سایت با هوشِ مصنوعی، کپشن و تحلیل. تشخیصِ تصویر همان تنظیمِ قبلی را دارد." />
        <ErrorBox message={error} />
        {notice && <Alert tone="ok">{notice}</Alert>}
        <div className="space-y-2">
          <label className="flex items-start gap-2" style={{ color: "var(--text)" }}>
            <input type="radio" name="ai-route" checked={data.mode === "qwen_first"} disabled={busy} data-testid="route-qwen" onChange={() => void choose("qwen_first")} />
            <span>
              <b>اول Qwen روی سرورِ پردازش</b>
              <span className="block text-sm" style={{ color: "var(--text-3)" }}>
                اگر سرور خاموش بود، مدل را نداشت یا تا {Math.round(data.run_timeout / 60).toLocaleString("fa-IR")} دقیقه جواب نداد، خودکار با Metis انجام می‌شود.
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2" style={{ color: "var(--text)" }}>
            <input type="radio" name="ai-route" checked={data.mode === "metis_only"} disabled={busy} data-testid="route-metis" onChange={() => void choose("metis_only")} />
            <span>
              <b>فقط Metis</b>
              <span className="block text-sm" style={{ color: "var(--text-3)" }}>سریع‌تر است ولی هزینه دارد و داده از سرور بیرون می‌رود.</span>
            </span>
          </label>
        </div>

        <Alert tone={n.ready ? "ok" : missing ? "warn" : "info"}>
          <span data-testid="route-state">
            {n.ready && n.has_model !== null && <>سرورِ پردازش «{n.node}» آنلاین است و مدلِ <b dir="ltr">{n.model}</b> را دارد.</>}
            {n.ready && n.has_model === null && <>سرورِ پردازش «{n.node}» آنلاین است؛ Ollama روی آن خاموش است و خودش روشن می‌شود. اگر مدل نبود، کار خودکار با Metis انجام می‌شود.</>}
            {!n.ready && !missing && <>{n.reason} تا وقتی روشن نشود کارها با Metis انجام می‌شوند و منتظرش نمی‌مانند.</>}
            {missing && <>مدلِ <b dir="ltr">{n.model}</b> روی سرورِ پردازش نیست و مدلِ دیگری به‌جایش استفاده نمی‌شود، پس کارها با Metis انجام می‌شوند.</>}
          </span>
          {n.known_models.length > 0 && <span className="mt-1 block text-xs" dir="ltr">{n.known_models.join("  ·  ")}</span>}
        </Alert>
        {missing && (
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" disabled={busy || !n.online} data-testid="route-pull" onClick={() => void pull()}>
              دانلودِ مدل روی سرورِ پردازش (حدودِ ۱۹ گیگابایت)
            </Button>
            {!n.online && <span className="text-xs" style={{ color: "var(--text-3)" }}>سرور خاموش است؛ بعد از روشن شدن این دکمه فعال می‌شود.</span>}
          </div>
        )}

        {data.recent.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm" style={{ color: "var(--text-2)" }}>آخرین پاسخ‌ها را چه کسی داد؟</summary>
            <ul className="mt-2 space-y-1 text-xs" data-testid="route-recent" style={{ color: "var(--text-2)" }}>
              {data.recent.map((r, i) => (
                <li key={i}>
                  {new Date(r.at).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" })} · <b dir="ltr">{r.model}</b> ({r.via === "node" ? "سرورِ پردازش" : "Metis"}){r.seconds ? ` · ${Math.round(r.seconds).toLocaleString("fa-IR")} ثانیه` : ""}
                  {r.fell_back && <span style={{ color: "var(--warn)" }}> · جایگزین شد: {r.reason}</span>}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Card>
  );
}
