import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, SectionTitle, Select, Spinner } from "../../../components/ui";
import DownloadWhen from "./DownloadWhen";
import {
  countInstalled,
  missingIn,
  nodeNote,
  progressView,
  selectable,
  selectionText,
  sizeText,
  stateView,
  toFa,
  type ModelsListing,
  type NodeModels,
} from "./nodeModels";
import { DEFAULT_WHEN, whenBody, whenError, whenValid, type WhenChoice } from "./schedule";

/**
 * «مدل‌های سرورِ پردازش» — همهٔ مدل‌هایی که سرورِ پردازش لازم دارد، با یک دکمهٔ دانلود: حذفِ پس‌زمینهٔ عکس و ویدیو (و اجرای
 * آن روی کارتِ گرافیک)، صدا، ویدیوی هوش مصنوعی. مدل‌های متنیِ Ollama جای خودشان («موتورهای AI») را دارند.
 *
 * دانلود همان کارِ همیشگیِ «node.models» است (POST /compute/nodes/<id>/models/download/ {packages, when})؛ سرور در پس‌زمینه
 * دانلود می‌کند، ادامه‌پذیر است و «زمانِ دانلود» (الان / ساعتِ … / بازهٔ شبانه) را رعایت می‌کند.
 */
export default function NodeModelsCard() {
  const [data, setData] = useState<ModelsListing | null>(null);
  const [nodeId, setNodeId] = useState<number | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [when, setWhen] = useState<WhenChoice>(DEFAULT_WHEN);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<ModelsListing>("/compute/models/");
      setData(d);
      setError(null);
      setNodeId((cur) => (cur !== null && d.nodes.some((n) => n.node.id === cur) ? cur : d.nodes[0]?.node.id ?? null));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const current: NodeModels | undefined = data?.nodes.find((n) => n.node.id === nodeId);
  // دانلودِ در جریان: هر ۱۰ ثانیه تازه شود تا درصد جلو برود
  const live = Boolean(current?.running);
  useEffect(() => {
    if (!live) return undefined;
    const t = window.setInterval(() => void load(), 10000);
    return () => window.clearInterval(t);
  }, [live, load]);

  const toggle = (key: string) => {
    setNotice(null);
    setPicked((p) => (p.includes(key) ? p.filter((k) => k !== key) : [...p, key]));
  };

  const download = async (keys: string[]) => {
    if (!current || keys.length === 0) return;
    if (!whenValid(when)) {
      setError(whenError(when));
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const chosen = whenBody(when);
      await api.post(`/compute/nodes/${current.node.id}/models/download/`, chosen ? { packages: keys, when: chosen } : { packages: keys });
      setPicked([]);
      setNotice(
        current.node.online
          ? `${toFa(keys.length)} بسته برای دانلود به «${current.node.name}» فرستاده شد. پیشرفت همین‌جا و در «صفِ پردازش» دیده می‌شود.`
          : `${toFa(keys.length)} بسته در صف رفت؛ همین که «${current.node.name}» روشن شد دانلود شروع می‌شود.`,
      );
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const progress = current ? progressView(current) : null;
  const counts = current ? countInstalled(current.groups) : null;
  const note = current ? nodeNote(current) : "";

  return (
    <Card>
      <SectionTitle
        action={
          <Button variant="ghost" size="sm" onClick={() => void load()} aria-label="تازه‌سازی" title="تازه‌سازی" style={{ padding: 7 }}>
            <Icon name="refresh" size={16} />
          </Button>
        }
      >
        <span className="flex items-center gap-2" data-testid="node-models">
          <Icon name="download" size={16} /> مدل‌های سرورِ پردازش
        </span>
      </SectionTitle>
      <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
        همهٔ مدل‌هایی که سرورِ پردازش برای حذفِ پس‌زمینهٔ عکس و ویدیو، صدا و ویدیوی هوش مصنوعی لازم دارد. هر کدام را که نصب نیست
        انتخاب کنید و «دانلود» بزنید. مدل‌های متنی (Ollama) از{" "}
        <Link to={data?.ollama_page || "/admin/providers"} className="underline" style={{ color: "var(--brand-strong)" }}>
          «موتورهای AI»
        </Link>{" "}
        دانلود می‌شوند.
      </p>

      <ErrorBox message={error} />
      {!data && !error && <Spinner />}
      {data && data.nodes.length === 0 && (
        <p className="text-sm" style={{ color: "var(--text-3)" }}>
          هنوز سرورِ پردازشی ثبت نشده است.
        </p>
      )}

      {current && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
            {data && data.nodes.length > 1 ? (
              <Select
                aria-label="کدام سرور"
                value={String(current.node.id)}
                onChange={(e) => {
                  setNodeId(Number(e.target.value));
                  setPicked([]);
                }}
                className="w-auto"
              >
                {data.nodes.map((n) => (
                  <option key={n.node.id} value={n.node.id}>
                    {n.node.name} {n.node.online ? "(روشن)" : "(خاموش)"}
                  </option>
                ))}
              </Select>
            ) : (
              <b style={{ color: "var(--text)" }}>{current.node.name}</b>
            )}
            <Badge tone={current.node.online ? "ok" : "neutral"}>{current.node.online ? "روشن" : "خاموش"}</Badge>
            {counts && counts.total > 0 && (
              <span>
                {toFa(counts.installed)} از {toFa(counts.total)} بسته نصب است
              </span>
            )}
          </div>

          {note && <Alert tone="info">{note}</Alert>}
          {current.error && <Alert tone="warn" title="آخرین خطای دانلود روی سرور">{current.error}</Alert>}
          {progress && (
            <div>
              <p className="mb-1 text-sm" style={{ color: "var(--text-2)" }}>
                {progress.text}
              </p>
              <div className="u-meter" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.pct ?? undefined}>
                <span style={{ width: `${progress.pct ?? 8}%`, background: "var(--brand)" }} />
              </div>
            </div>
          )}

          {current.groups.map((g) => {
            const missing = missingIn(g);
            return (
              <section key={g.key} aria-label={g.title}>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-bold" style={{ color: "var(--text)" }}>
                    {g.title}
                  </h3>
                  {missing.length > 0 && (
                    <Button variant="secondary" size="sm" disabled={busy} onClick={() => void download(missing)} data-testid={`models-all-${g.key}`}>
                      <Icon name="download" size={13} /> دانلودِ همهٔ نصب‌نشده‌ها ({toFa(missing.length)})
                    </Button>
                  )}
                </div>
                {g.note && (
                  <p className="mb-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
                    {g.note}
                  </p>
                )}
                <ul className="flex flex-col gap-1.5">
                  {g.packages.map((p) => {
                    const v = stateView(p);
                    const can = selectable(p);
                    const size = sizeText(p.state === "missing" && p.missing_mb ? p.missing_mb : p.total_mb);
                    return (
                      <li
                        key={p.key}
                        className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2"
                        style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
                      >
                        <label className={`flex min-w-0 flex-1 items-start gap-2 ${can ? "cursor-pointer" : ""}`}>
                          <input
                            type="checkbox"
                            className="mt-1.5"
                            disabled={!can || busy}
                            checked={picked.includes(p.key)}
                            onChange={() => toggle(p.key)}
                            data-testid={`model-pick-${p.key}`}
                          />
                          <span className="min-w-0">
                            <span className="block font-bold" style={{ color: "var(--text)" }}>
                              {p.title}
                              {p.optional && (
                                <span className="mr-2 text-xs font-normal" style={{ color: "var(--text-3)" }}>
                                  (اختیاری)
                                </span>
                              )}
                            </span>
                            {p.note && (
                              <span className="block text-xs leading-6" style={{ color: "var(--text-3)" }}>
                                {p.note}
                              </span>
                            )}
                            {p.title_en && p.title_en !== p.title && (
                              <span className="block truncate text-xs" dir="ltr" style={{ color: "var(--text-3)", textAlign: "right" }} title={p.title_en}>
                                {p.title_en}
                              </span>
                            )}
                          </span>
                        </label>
                        {size && (
                          <span className="u-num text-xs" style={{ color: "var(--text-3)" }}>
                            {size}
                          </span>
                        )}
                        <Badge tone={v.tone}>{v.label}</Badge>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}

          <DownloadWhen value={when} onChange={setWhen} disabled={busy} />
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => void download(picked)} disabled={busy || picked.length === 0} data-testid="models-download">
              {busy ? <Spinner size={13} /> : <Icon name="download" size={13} />} دانلودِ انتخاب‌شده‌ها
            </Button>
            <span className="text-sm" style={{ color: "var(--text-3)" }}>
              {selectionText(current.groups, picked)}
            </span>
          </div>
          {notice && <Alert tone="ok">{notice}</Alert>}
        </div>
      )}
    </Card>
  );
}
