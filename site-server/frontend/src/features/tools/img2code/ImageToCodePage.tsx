import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { errorMessage } from "../../../api/client";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, PageHeader, SectionTitle, Spinner, fa } from "../../../components/ui";
import { Item, Overview, StoreRow, i2cApi } from "./api";
import NewForm from "./NewForm";
import ResultView from "./ResultView";
import "./img2code.css";

const POLL_MS = 2000;

function when(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return "";
  }
}

function ActiveCard({ item, steps, onCancel }: { item: Item; steps: Overview["steps"]; onCancel: () => void }) {
  const shown = item.source_kind === "url" ? steps : steps.filter((s) => s.key !== "shot");
  const idx = Math.max(0, shown.findIndex((s) => s.key === item.step));
  return (
    <Card>
      <div data-testid="i2c-progress" data-id={item.id} data-state={item.state}>
        <div className="i2c-progress-head">
          <b>{item.title || `تبدیلِ ${fa(item.id)}`}</b>
          <Button size="sm" variant="ghost" onClick={onCancel} data-testid="i2c-cancel">لغو</Button>
        </div>
        <ol className="i2c-steps">
          {shown.map((s, i) => (
            <li key={s.key} className={i < idx ? "is-done" : i === idx ? "is-now" : ""}>{s.label}</li>
          ))}
        </ol>
        <div className="i2c-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(item.progress)}>
          <i style={{ width: `${Math.max(3, Math.min(100, item.progress))}%` }} />
        </div>
        <p className="i2c-note" data-testid="i2c-message">
          {item.message || "در صف"}
          {item.queue_position && item.queue_position > 1 ? ` — نوبتِ ${fa(item.queue_position)}` : ""} — {fa(Math.round(item.progress))}٪
        </p>
      </div>
    </Card>
  );
}

/** «تصویر به کد» — اسکرین‌شاتِ صفحه ⇒ HTML/CSSِ قابل‌ویرایش و پیش‌نویسِ صفحه در سایت‌ساز (پنل › ابزارها). */
export default function ImageToCodePage() {
  const [params, setParams] = useSearchParams();
  // وقتی صفحه زیرِ یک فروشگاه سوار شود (مثلاً داخلِ «استودیوی طراحی»: /stores/:id/design/image-to-code) همان فروشگاه است؛ در «ابزارها» انتخابگر دارد
  const { id: routeStore } = useParams<{ id: string }>();
  const [stores, setStores] = useState<StoreRow[] | null>(null);
  const [storeId, setStoreId] = useState("");
  const [data, setData] = useState<Overview | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    i2cApi
      .stores()
      .then((rows) => {
        setStores(rows);
        let last: string | null = null;
        try {
          last = localStorage.getItem("last-store");
        } catch {
          last = null;
        }
        const want = routeStore ?? params.get("store") ?? last;
        const pick = rows.find((r) => String(r.id) === want) ?? rows[0];
        setStoreId(pick ? String(pick.id) : "");
      })
      .catch((e) => setError(errorMessage(e)));
    // یک بار
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(
    (sid: string) => {
      setData(null);
      setError(null);
      i2cApi
        .overview(sid)
        .then((d) => {
          setData(d);
          setItems(d.items);
          const want = Number(params.get("open") || 0);
          setOpenId((cur) => cur ?? (want && d.items.some((i) => i.id === want) ? want : (d.items.find((i) => i.state === "READY")?.id ?? null)));
        })
        .catch((e) => setError(errorMessage(e)));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    if (!storeId) return;
    setOpenId(null);
    load(storeId);
  }, [storeId, load]);

  const activeIds = useMemo(() => items.filter((i) => i.active).map((i) => i.id).join(","), [items]);
  useEffect(() => {
    if (!activeIds || !storeId) return;
    const timer = window.setInterval(() => {
      activeIds.split(",").forEach((id) => {
        i2cApi
          .get(storeId, Number(id))
          .then((it) => setItems((cur) => cur.map((x) => (x.id === it.id ? it : x))))
          .catch(() => undefined);
      });
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [activeIds, storeId]);

  function changeStore(id: string) {
    setStoreId(id);
    const next = new URLSearchParams(params);
    next.set("store", id);
    next.delete("open");
    setParams(next, { replace: true });
    try {
      localStorage.setItem("last-store", id);
    } catch {
      /* حالتِ خصوصیِ مرورگر */
    }
  }

  function upsert(item: Item) {
    setItems((cur) => [item, ...cur.filter((x) => x.id !== item.id)]);
  }

  const active = items.filter((i) => i.active);
  const history = items.filter((i) => !i.active);
  const open = items.find((i) => i.id === openId) ?? null;

  if (!stores && !error) {
    return (
      <Card>
        <Spinner />
      </Card>
    );
  }

  return (
    <div className="i2c-page space-y-5" data-testid="img2code-page">
      <PageHeader
        title="تصویر به کد"
        subtitle="اسکرین‌شاتِ یک صفحه را بدهید؛ HTML/CSSِ قابل‌ویرایش می‌گیرید و می‌توانید آن را به‌صورتِ پیش‌نویسِ صفحه در سایت‌ساز بسازید. متن‌ها متنِ واقعی‌اند، نه عکسِ نوشته."
        actions={
          !routeStore && stores && stores.length > 1 ? (
            <select className="u-input i2c-store" value={storeId} onChange={(e) => changeStore(e.target.value)} aria-label="فروشگاه" data-testid="i2c-store">
              {stores.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          ) : undefined
        }
      />
      <ErrorBox message={error} />
      {stores && stores.length === 0 && <EmptyState title="هنوز فروشگاهی ندارید" description="اول یک فروشگاه بسازید؛ تاریخچهٔ تبدیل‌ها برای هر فروشگاه جدا نگه داشته می‌شود." />}

      {data && storeId && <NewForm storeId={storeId} options={data.options} engine={data.engine} onCreated={(it) => { upsert(it); setOpenId(it.id); }} />}
      {!data && storeId && !error && <Card><Spinner /></Card>}

      {active.map((it) => (
        <ActiveCard
          key={it.id}
          item={it}
          steps={data?.steps ?? []}
          onCancel={() => void i2cApi.cancel(storeId, it.id).then(upsert).catch((e) => setError(errorMessage(e)))}
        />
      ))}

      {open && data && !open.active && (
        <ResultView
          key={open.id}
          storeId={storeId}
          item={open}
          canDraft={data.can_draft}
          onChange={upsert}
          onAgain={(it) => {
            upsert(it);
            setOpenId(it.id);
          }}
          onDeleted={() => {
            setItems((cur) => cur.filter((x) => x.id !== open.id));
            setOpenId(null);
          }}
        />
      )}

      {data && (
        <div>
          <SectionTitle>تاریخچهٔ تبدیل‌ها{history.length ? ` (${fa(history.length)})` : ""}</SectionTitle>
          {history.length === 0 ? (
            <Alert tone="info">هنوز تبدیلی نکرده‌اید. بالا یک تصویر بدهید.</Alert>
          ) : (
            <ul className="i2c-history" data-testid="i2c-history">
              {history.map((it) => {
                const ssim = it.scores.find((s) => s.key === "ssim");
                return (
                  <li key={it.id} className={it.id === openId ? "is-open" : ""} data-testid="i2c-history-item" data-id={it.id}>
                    <button type="button" onClick={() => setOpenId(it.id)} className="i2c-history-btn">
                      <span className="i2c-history-title">{it.title || `تبدیلِ ${fa(it.id)}`}</span>
                      <span className="i2c-history-meta">
                        <Badge tone={it.state === "READY" ? "ok" : it.state === "FAILED" ? "bad" : "neutral"}>{it.state_label}</Badge>
                        <Badge>{it.mode_label}</Badge>
                        {ssim && <Badge tone={ssim.verdict === "good" ? "ok" : ssim.verdict === "ok" ? "warn" : "bad"}>شباهت {ssim.display}</Badge>}
                        {it.draft && <Badge tone="brand">پیش‌نویس در سایت‌ساز</Badge>}
                        <small>{when(it.created_at)}</small>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
