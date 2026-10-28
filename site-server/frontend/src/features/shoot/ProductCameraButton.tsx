import { useEffect, useState } from "react";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Button, Card, Spinner } from "../../components/ui";
import CaptureFlow from "./CaptureFlow";
import Portal, { LAYER } from "./Portal";
import { Session, fa, shootApi } from "./api";

/**
 * «عکس‌برداری با دوربین» در تعریفِ محصول: کنارِ «آپلود تصویر». فهرستِ زاویه‌ها (از تحلیلِ محصول یا الگوی آماده)
 * را با راهنما جلو می‌برد، هر عکس را بررسی می‌کند و در آخر بهترین عکسِ هر زاویه را به ترتیب در عکس‌های محصول ثبت
 * می‌کند. جلسهٔ نیمه‌کاره می‌ماند و دفعهٔ بعد از همان‌جا ادامه پیدا می‌کند.
 */
export default function ProductCameraButton({
  product,
  onSaved,
  autoOpen = false,
}: {
  product: { id: number; store: number; name: string };
  onSaved: () => void | Promise<void>;
  autoOpen?: boolean;
}) {
  const [open, setOpen] = useState(autoOpen);
  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)} data-testid="camera-capture">
        <Icon name="camera" size={15} />
        عکس‌برداری با دوربین
      </Button>
      {open && (
        <Portal>
          <Sheet product={product} onClose={() => setOpen(false)} onSaved={onSaved} />
        </Portal>
      )}
    </>
  );
}

function Sheet({
  product,
  onClose,
  onSaved,
}: {
  product: { id: number; store: number; name: string };
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<number | null>(null);

  useEffect(() => {
    shootApi
      .create(product.store, { product: product.id, purpose: "photos", reuse: true, analyze: true })
      .then(setSession)
      .catch((err) => setError(errorMessage(err)));
  }, [product.id, product.store]);

  useEffect(() => {
    if (!session || session.state !== "ANALYZING") return;
    const t = window.setInterval(() => {
      shootApi.get(product.store, session.id).then(setSession).catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(t);
  }, [session?.state, session?.id, product.store]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  const shots = session?.plan.photos ?? [];
  const ready = shots.filter((s) => session?.takes.some((t) => t.shot === s.key && t.accepted)).length;
  const unsaved = shots.filter((s) =>
    session?.takes.some((t) => t.shot === s.key && t.accepted && !t.saved_image_id),
  ).length;

  const save = async () => {
    if (!session) return;
    setSaving(true);
    setError(null);
    try {
      const r = await shootApi.savePhotos(product.store, session.id);
      setSession(r.session);
      setSaved(r.created.length);
      await onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const saveButton = (
    <Button className="w-full" style={{ minHeight: 56 }} disabled={saving || unsaved === 0} onClick={() => void save()} data-testid="save-to-product">
      <Icon name="check" size={17} />
      {unsaved ? `ثبتِ ${fa(unsaved)} عکس در محصول (به ترتیبِ زاویه‌ها)` : "همهٔ عکس‌های قبول‌شده ثبت شده‌اند"}
    </Button>
  );

  return (
    <div className="fixed inset-0 overflow-y-auto" style={{ background: "var(--bg)", zIndex: LAYER.sheet }} data-testid="camera-sheet">
      <div className="sticky top-0 z-10 flex items-center justify-between gap-2 px-4 py-3" style={{ background: "var(--bg)", borderBottom: "1px solid var(--line-strong)" }}>
        <div className="min-w-0">
          <div className="truncate font-extrabold" style={{ color: "var(--text)" }}>
            عکس‌برداری: {product.name}
          </div>
          <div className="text-xs" style={{ color: "var(--text-3)" }}>
            {fa(ready)} از {fa(shots.length)} زاویه قبول شده
          </div>
        </div>
        <button onClick={onClose} className="grid h-12 w-12 place-items-center rounded-full" style={{ background: "var(--surface-2)" }} aria-label="بستن">
          <Icon name="x" size={20} />
        </button>
      </div>
      <div className="mx-auto max-w-xl space-y-4 p-4">
        {error && <Alert tone="bad">{error}</Alert>}
        {saved !== null && (
          <Alert tone="ok" title="ثبت شد">
            {fa(saved)} عکس به عکس‌های محصول اضافه شد.{" "}
            <button className="underline" onClick={onClose}>
              بستن
            </button>
          </Alert>
        )}
        {!session ? (
          !error && (
            <div className="flex items-center gap-2 py-10">
              <Spinner /> آماده‌سازی…
            </div>
          )
        ) : (
          <>
            {session.state === "ANALYZING" && (
              <Card>
                <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
                  <Spinner size={16} /> محصول تحلیل می‌شود تا زاویه‌های مناسبش پیشنهاد شود… تا آن موقع زاویه‌های
                  پایه آماده‌اند و می‌توانی شروع کنی.
                </div>
              </Card>
            )}
            {/* ثبتِ زودتر از تمام شدنِ همهٔ زاویه‌ها: بالای صفحه، تا زیرِ نوارِ پایین نرود */}
            {ready > 0 && ready < shots.length && unsaved > 0 && saved === null && <Card>{saveButton}</Card>}
            <CaptureFlow
              storeId={product.store}
              session={session}
              onSession={setSession}
              kinds={["photo"]}
              footer={<Card>{saveButton}</Card>}
            />
          </>
        )}
      </div>
    </div>
  );
}
