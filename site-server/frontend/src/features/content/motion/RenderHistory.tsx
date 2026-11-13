import { useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, EmptyState, fa } from "../../../components/ui";
import { RenderRow } from "./api";

const TONE: Record<RenderRow["state"], "neutral" | "info" | "warn" | "ok" | "bad"> = {
  QUEUED: "info",
  WAITING_NODE: "warn",
  RENDERING: "info",
  READY: "ok",
  FAILED: "bad",
  CANCELLED: "neutral",
};

function size(bytes: number): string {
  if (!bytes) return "";
  return bytes > 1048576 ? `${fa((bytes / 1048576).toFixed(1))} مگابایت` : `${fa(Math.round(bytes / 1024))} کیلوبایت`;
}

function Row({
  r,
  storeId,
  onAct,
  onDelete,
  onReuse,
  nodeWaiting,
}: {
  r: RenderRow;
  storeId: string;
  onAct: (r: RenderRow, a: "cancel" | "site" | "retry") => void;
  onDelete: (r: RenderRow) => void;
  onReuse: (r: RenderRow) => void;
  nodeWaiting: boolean;
}) {
  const [play, setPlay] = useState(false);
  const pct = Math.round((r.progress || 0) * 100);
  return (
    <Card>
      <div className="flex gap-3">
        <div className="relative shrink-0 overflow-hidden rounded-lg" style={{ width: 96, height: 128, background: "#0b0b0b" }}>
          {r.state === "READY" && r.video_url ? (
            play ? (
              <video src={r.video_url} poster={r.poster_url ?? undefined} controls autoPlay loop playsInline className="h-full w-full object-contain" />
            ) : (
              <button type="button" className="relative block h-full w-full" onClick={() => setPlay(true)} aria-label="پخش">
                {r.poster_url ? <img src={r.poster_url} alt="" className="h-full w-full object-cover" /> : null}
                <span className="absolute inset-0 flex items-center justify-center" style={{ color: "#fff", background: "rgba(0,0,0,0.25)" }}>
                  <Icon name="play" size={26} />
                </span>
              </button>
            )
          ) : (
            <div className="flex h-full w-full items-center justify-center text-xs" style={{ color: "#94a3b8" }}>
              {r.active ? `${fa(pct)}٪` : "—"}
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-bold" style={{ color: "var(--text)" }}>
              {r.title || "ویدیو"}
            </span>
            <Badge tone={TONE[r.state]}>{r.state_label}</Badge>
          </div>
          <div className="mt-1 text-xs leading-6" style={{ color: "var(--text-3)" }}>
            {r.mode_label}
            {r.style_name ? ` · ${r.style_name}` : ""}
            {r.aspect ? ` · ${fa(r.aspect)}` : ""} · {r.target_label}
            {r.state === "READY" ? ` · ${fa(r.width)}×${fa(r.height)} · ${fa(r.duration_s.toFixed(1))} ثانیه · ${size(r.bytes)}` : ""}
          </div>
          {r.active ? (
            <div className="mt-2">
              <div className="h-2 overflow-hidden rounded-full" style={{ background: "var(--surface-2)" }}>
                <div className="h-full rounded-full transition-all" style={{ width: `${Math.max(3, pct)}%`, background: "var(--brand)" }} />
              </div>
              <div className="mt-1 text-xs" style={{ color: "var(--text-2)" }}>
                {r.message}
              </div>
            </div>
          ) : null}
          {r.error ? (
            <div className="mt-1 text-xs leading-6" style={{ color: "var(--bad)" }}>
              {r.error}
            </div>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-2">
            {r.state === "READY" ? (
              <>
                <Link to={r.video_ref ? `/stores/${storeId}/editor?start=${encodeURIComponent(r.video_ref)}` : `/stores/${storeId}/editor`} className="u-btn u-btn-secondary u-btn-sm" title="کلیپ روی خطِ زمانِ ادیتور باز می‌شود (در سطلِ رسانه هم با نامِ «موشن — …» هست)">
                  <Icon name="film" size={14} /> باز کردن در ادیتورِ ویدیو
                </Link>
                {r.video_url ? (
                  <a href={r.video_url} download className="u-btn u-btn-secondary u-btn-sm">
                    <Icon name="download" size={14} /> دانلود
                  </a>
                ) : null}
              </>
            ) : null}
            <Button variant="ghost" size="sm" type="button" onClick={() => onReuse(r)}>
              <Icon name="edit" size={14} /> ویرایشِ دوباره
            </Button>
            {r.active && r.target === "node" && nodeWaiting ? (
              <Button variant="secondary" size="sm" type="button" onClick={() => onAct(r, "site")} title="کارِ منتظرِ سرورِ پردازش لغو و همین رندر روی سایت (با سقفِ ۶۰ ثانیه و ۱۰۸۰p) انجام می‌شود">
                <Icon name="cloud" size={14} /> رندر روی سایت
              </Button>
            ) : null}
            {r.active ? (
              <Button variant="ghost" size="sm" type="button" onClick={() => onAct(r, "cancel")}>
                <Icon name="x" size={14} /> لغو
              </Button>
            ) : null}
            {r.state === "FAILED" || r.state === "CANCELLED" ? (
              <Button variant="secondary" size="sm" type="button" onClick={() => onAct(r, "retry")}>
                <Icon name="refresh" size={14} /> تلاشِ دوباره
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" type="button" onClick={() => onDelete(r)}>
              <Icon name="trash" size={14} />
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function RenderHistory({
  renders,
  storeId,
  onAct,
  onDelete,
  onReuse,
  nodeWaiting,
}: {
  renders: RenderRow[];
  storeId: string;
  onAct: (r: RenderRow, a: "cancel" | "site" | "retry") => void;
  onDelete: (r: RenderRow) => void;
  onReuse: (r: RenderRow) => void;
  nodeWaiting: boolean;
}) {
  if (!renders.length) return <EmptyState title="هنوز ویدیویی نساخته‌اید" description="سبک را انتخاب کنید، متن را بنویسید و «رندر» را بزنید؛ ویدیوها این‌جا و در ادیتورِ ویدیو دیده می‌شوند." />;
  return (
    <div className="space-y-3">
      {renders.map((r) => (
        <Row key={r.id} r={r} storeId={storeId} onAct={onAct} onDelete={onDelete} onReuse={onReuse} nodeWaiting={nodeWaiting} />
      ))}
    </div>
  );
}
