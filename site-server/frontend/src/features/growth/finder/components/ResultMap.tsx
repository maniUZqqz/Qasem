import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Icon from "../../../../components/Icon";
import { fa } from "../../../../components/ui";
import type { MapPoint } from "../types";

/**
 * A small slippy map without a map library: OpenStreetMap raster tiles positioned by plain maths (Web Mercator), markers
 * coloured by the fit score, drag to pan, wheel / buttons to zoom. If the tiles cannot be loaded (blocked network) the markers
 * still sit at their true relative positions on a plain grid, and a line says so. Always LTR (geometry), the labels around it are RTL.
 */
const TILE = 256;
const TILE_URL = (z: number, x: number, y: number) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;
const MAX_MARKERS = 700;

const worldX = (lon: number, z: number) => ((lon + 180) / 360) * TILE * 2 ** z;
const worldY = (lat: number, z: number) => {
  const s = Math.sin((lat * Math.PI) / 180);
  return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * TILE * 2 ** z;
};
const lonOf = (x: number, z: number) => (x / (TILE * 2 ** z)) * 360 - 180;
const latOf = (y: number, z: number) => {
  const n = Math.PI - (2 * Math.PI * y) / (TILE * 2 ** z);
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
};

function fit(points: MapPoint[], w: number, h: number): { lat: number; lon: number; zoom: number } {
  if (!points.length) return { lat: 32.4, lon: 53.7, zoom: 5 };
  const lats = points.map((p) => p.lat);
  const lons = points.map((p) => p.lon);
  const [s, n, west, e] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
  let zoom = 16;
  for (; zoom > 3; zoom--) {
    if (Math.abs(worldX(e, zoom) - worldX(west, zoom)) < w * 0.85 && Math.abs(worldY(s, zoom) - worldY(n, zoom)) < h * 0.85) break;
  }
  return { lat: (s + n) / 2, lon: (west + e) / 2, zoom };
}

const colour = (score: number) => (score >= 70 ? "var(--ok)" : score >= 45 ? "var(--info)" : "var(--text-3)");

export default function ResultMap({
  points,
  selectedId,
  onSelect,
  height = 520,
}: {
  points: MapPoint[];
  selectedId?: number | null;
  onSelect: (point: MapPoint) => void;
  height?: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: height });
  const [view, setView] = useState(() => fit(points, 800, height));
  const [tilesFailed, setTilesFailed] = useState(0);
  const drag = useRef<{ x: number; y: number; cx: number; cy: number } | null>(null);
  const fitted = useRef(false);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth || 800, h: el.clientHeight || height }));
    ro.observe(el);
    setSize({ w: el.clientWidth || 800, h: el.clientHeight || height });
    return () => ro.disconnect();
  }, [height]);

  const refit = useCallback(() => setView(fit(points, size.w, size.h)), [points, size.w, size.h]);
  useEffect(() => {
    if (!fitted.current && points.length) {
      fitted.current = true;
      refit();
    }
  }, [points, refit]);

  const cx = worldX(view.lon, view.zoom);
  const cy = worldY(view.lat, view.zoom);
  const left = cx - size.w / 2;
  const top = cy - size.h / 2;

  const tiles = useMemo(() => {
    const n = 2 ** view.zoom;
    const out: { key: string; x: number; y: number; src: string }[] = [];
    for (let tx = Math.floor(left / TILE); tx <= Math.floor((left + size.w) / TILE); tx++) {
      for (let ty = Math.floor(top / TILE); ty <= Math.floor((top + size.h) / TILE); ty++) {
        if (ty < 0 || ty >= n) continue;
        const wrapped = ((tx % n) + n) % n;
        out.push({ key: `${view.zoom}/${tx}/${ty}`, x: tx * TILE - left, y: ty * TILE - top, src: TILE_URL(view.zoom, wrapped, ty) });
      }
    }
    return out;
  }, [view.zoom, left, top, size.w, size.h]);

  const visible = useMemo(() => {
    const out: (MapPoint & { px: number; py: number })[] = [];
    for (const p of points) {
      const px = worldX(p.lon, view.zoom) - left;
      const py = worldY(p.lat, view.zoom) - top;
      if (px >= -10 && px <= size.w + 10 && py >= -10 && py <= size.h + 10) out.push({ ...p, px, py });
      if (out.length >= MAX_MARKERS) break;
    }
    return out.sort((a, b) => a.score - b.score);
  }, [points, view.zoom, left, top, size.w, size.h]);

  const zoomBy = (d: number) => setView((v) => ({ ...v, zoom: Math.max(3, Math.min(18, v.zoom + d)) }));

  return (
    <div className="space-y-1.5" data-testid="result-map">
      <div
        ref={box}
        dir="ltr"
        className="relative select-none overflow-hidden rounded-xl"
        style={{ height, background: "var(--surface-2)", border: "1px solid var(--line)", cursor: drag.current ? "grabbing" : "grab", touchAction: "none" }}
        onPointerDown={(e) => {
          drag.current = { x: e.clientX, y: e.clientY, cx, cy };
          (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d) return;
          const nx = d.cx - (e.clientX - d.x);
          const ny = d.cy - (e.clientY - d.y);
          setView((v) => ({ ...v, lon: lonOf(nx, v.zoom), lat: latOf(ny, v.zoom) }));
        }}
        onPointerUp={() => (drag.current = null)}
        onWheel={(e) => zoomBy(e.deltaY < 0 ? 1 : -1)}
      >
        {tiles.map((t) => (
          // eslint-disable-next-line jsx-a11y/alt-text
          <img
            key={t.key}
            src={t.src}
            alt=""
            draggable={false}
            loading="lazy"
            onError={() => setTilesFailed((n) => n + 1)}
            style={{ position: "absolute", left: t.x, top: t.y, width: TILE, height: TILE, pointerEvents: "none" }}
          />
        ))}
        {visible.map((p) => (
          <button
            key={p.id}
            type="button"
            title={`${p.name} · امتیاز ${fa(p.score)}`}
            aria-label={p.name}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => onSelect(p)}
            data-testid="map-marker"
            style={{
              position: "absolute",
              left: p.px - 8,
              top: p.py - 8,
              width: selectedId === p.id ? 20 : 16,
              height: selectedId === p.id ? 20 : 16,
              marginLeft: selectedId === p.id ? -2 : 0,
              marginTop: selectedId === p.id ? -2 : 0,
              borderRadius: 999,
              background: colour(p.score),
              border: `2px solid ${selectedId === p.id ? "var(--text)" : "#fff"}`,
              boxShadow: "0 1px 4px rgba(0,0,0,.45)",
              padding: 0,
              cursor: "pointer",
              zIndex: selectedId === p.id ? 5 : 1,
            }}
          />
        ))}
        <div className="absolute flex flex-col gap-1" style={{ top: 8, left: 8, zIndex: 6 }} dir="ltr">
          <button type="button" className="u-btn u-btn-secondary u-btn-sm" aria-label="بزرگ‌نمایی" onPointerDown={(e) => e.stopPropagation()} onClick={() => zoomBy(1)}>
            <Icon name="plus" size={14} />
          </button>
          <button type="button" className="u-btn u-btn-secondary u-btn-sm" aria-label="کوچک‌نمایی" onPointerDown={(e) => e.stopPropagation()} onClick={() => zoomBy(-1)}>
            <span style={{ fontWeight: 800, lineHeight: 1 }}>−</span>
          </button>
          <button type="button" className="u-btn u-btn-secondary u-btn-sm" aria-label="نمایشِ همهٔ نقطه‌ها" onPointerDown={(e) => e.stopPropagation()} onClick={refit}>
            <Icon name="target" size={14} />
          </button>
        </div>
        <div className="absolute rounded px-1.5 text-[10px]" style={{ right: 6, bottom: 4, background: "rgba(255,255,255,.8)", color: "#333", zIndex: 6 }}>
          © OpenStreetMap contributors
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs" style={{ color: "var(--text-3)" }}>
        <span>
          {fa(visible.length)} نقطه در این نما از {fa(points.length)}؛ سبز = تناسبِ بالا، آبی = متوسط، خاکستری = کم.
        </span>
        {tilesFailed > 3 && <span style={{ color: "var(--warn)" }}>تصویرِ نقشه بارگذاری نشد (شبکه)؛ نقطه‌ها همچنان جای درستشان را نشان می‌دهند.</span>}
      </div>
    </div>
  );
}
