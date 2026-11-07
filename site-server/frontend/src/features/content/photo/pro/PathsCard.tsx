import { fa } from "../../../../components/ui";
import { flattenPx } from "./pen";
import type { ShapePath } from "./types";

export type SavedPath = { id: string; name: string; path: ShapePath; frameKey: string };

type Props = {
  paths: SavedPath[];
  /** پهنا ÷ ارتفاعِ بوم (برای بندانگشتی) */
  aspect: number;
  penPoints: number;
  onSave: () => void;
  onLoad: (id: string) => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onChannels: () => void;
};

/** کارتِ «مسیرها و کانال‌ها» (نوبت ۷): مسیرهای قلم را نگه دارید و دوباره بارگذاری کنید؛ کانال‌ها را ببینید. */
export default function PathsCard({ paths, aspect, penPoints, onSave, onLoad, onSelect, onDelete, onChannels }: Props) {
  const W = 72;
  const H = Math.max(24, Math.round(W / Math.max(0.2, aspect)));
  return (
    <div className="ws-card" data-testid="paths-card">
      <div className="ws-card-title">مسیرها و کانال‌ها</div>
      <p className="ws-hint">مسیرهایی که با ابزارِ قلم می‌کشید را اینجا نگه دارید؛ با بستنِ صفحه پاک می‌شوند. «کانال‌ها» قرمز، سبز، آبی، شفافیت و روشنایی را سیاه‌وسفید نشان می‌دهد و هر کدام را می‌شود انتخاب کرد.</p>
      <div className="flex flex-wrap gap-1">
        <button type="button" className="ws-btn primary" disabled={penPoints < 2} onClick={onSave} data-testid="path-save" title={penPoints < 2 ? "اول با ابزارِ قلم یک مسیر بکشید" : "مسیرِ فعلی را نگه می‌دارد"}>ذخیرهٔ مسیرِ فعلی</button>
        <button type="button" className="ws-btn" onClick={onChannels} data-testid="channels-open">کانال‌ها…</button>
      </div>
      <ul className="pw-snaps" data-testid="paths-list">
        {paths.map((p) => {
          const poly = flattenPx(p.path, W, H);
          const d = poly.length ? `M${poly.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(" L")}${p.path.closed ? " Z" : ""}` : "";
          return (
            <li key={p.id} data-path={p.id}>
              <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true" style={{ background: "var(--surface-2)", borderRadius: 6, flex: "none" }}>
                <path d={d} fill={p.path.closed ? "rgba(34,211,238,0.25)" : "none"} stroke="#22d3ee" strokeWidth={1.4} />
              </svg>
              <b>{p.name}</b>
              <span className="ws-muted">{fa(p.path.pts.length)} نقطه</span>
              <span className="pw-snap-btns">
                <button type="button" className="ws-btn" onClick={() => onLoad(p.id)} data-testid={`path-load-${p.id}`} title="مسیر روی بوم می‌آید تا ویرایش کنید">بارگذاری</button>
                <button type="button" className="ws-btn" disabled={p.path.pts.length < 3} onClick={() => onSelect(p.id)} data-testid={`path-select-${p.id}`} title="مسیر را به انتخاب تبدیل می‌کند">انتخاب</button>
                <button type="button" className="ws-btn" aria-label="حذفِ مسیر" onClick={() => onDelete(p.id)} data-testid={`path-del-${p.id}`}>🗑</button>
              </span>
            </li>
          );
        })}
        {!paths.length && <li className="ws-muted">هنوز مسیری ذخیره نکرده‌اید.</li>}
      </ul>
    </div>
  );
}
