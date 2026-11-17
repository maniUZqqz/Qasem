import { type MouseEvent as RMouseEvent, type PointerEvent as RPointerEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";

import Icon from "../../components/Icon";
import { Badge, Button, Input, Select, TextArea } from "../../components/ui";
import { Check, El, FontRow, Overview, ProductRow, ScenePage, designApi, fa } from "./api";
import type { FieldDef } from "./fields";
import { usePreview } from "./hooks";

export type { FieldDef };

// ───────────────────────────── رنگ

export function ColorField({ label, value, onChange, disabled }: { label: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  const ok = /^#[0-9a-f]{6}$/i.test(value || "");
  return (
    <label className="ds-field">
      <span>{label}</span>
      <span className="ds-color">
        <input type="color" value={ok ? value : "#000000"} disabled={disabled} onChange={(e) => onChange(e.target.value)} aria-label={label} />
        <Input type="text" value={value || ""} disabled={disabled} maxLength={7} dir="ltr" onChange={(e) => onChange(e.target.value)} />
      </span>
    </label>
  );
}

export function Field({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`ds-field ${wide ? "ds-wide" : ""}`}>
      <span>{label}</span>
      {children}
    </label>
  );
}

// ───────────────────────────── پیش‌نمایشِ صفحه با کادرِ انتخاب و کشیدن

export type CanvasProps = {
  storeId: string;
  docId: number;
  page: ScenePage;
  rev: number;
  width: number;
  mode?: string;
  selected?: string | null;
  onSelect?: (id: string | null) => void;
  onMove?: (el: El, x: number, y: number) => void;
  overlays?: ReactNode;
  onBackgroundClick?: (fx: number, fy: number) => void;
  boxes?: { id: string; x: number; y: number; w: number; h: number }[];
  hotspots?: { x: number; y: number; w: number; h: number; to: string }[];
  onHotspot?: (to: string) => void;
  pointerMode?: "edit" | "play" | "comment";
};

export function PageCanvas(p: CanvasProps) {
  const { page, width } = p;
  const scale = width / page.w;
  const h = Math.round(page.h * scale);
  const img = usePreview(p.storeId ? designApi.previewUrl(p.storeId, p.docId, page.id, Math.min(2000, Math.round(width * (window.devicePixelRatio > 1 ? 1.5 : 1))), p.rev, p.mode) : null);
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number } | null>(null);
  const start = useRef<{ x: number; y: number; el: El } | null>(null);
  const mode = p.pointerMode || "edit";

  const down = (e: RPointerEvent, el: El) => {
    if (mode !== "edit") return;
    e.stopPropagation();
    p.onSelect?.(el.id);
    if (!p.onMove) return;
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    start.current = { x: e.clientX, y: e.clientY, el };
    setDrag({ id: el.id, dx: 0, dy: 0 });
  };
  const move = (e: RPointerEvent) => {
    if (!start.current) return;
    setDrag({ id: start.current.el.id, dx: (e.clientX - start.current.x) / scale, dy: (e.clientY - start.current.y) / scale });
  };
  const up = (e: RPointerEvent) => {
    const s = start.current;
    start.current = null;
    if (!s) return;
    const dx = (e.clientX - s.x) / scale;
    const dy = (e.clientY - s.y) / scale;
    setDrag(null);
    if (Math.abs(dx) + Math.abs(dy) > 2 / scale) p.onMove?.(s.el, Math.round((s.el.x + dx) * 100) / 100, Math.round((s.el.y + dy) * 100) / 100);
  };

  const clickBg = (e: RMouseEvent) => {
    if (mode === "comment" && p.onBackgroundClick) {
      const r = (e.currentTarget as Element).getBoundingClientRect();
      p.onBackgroundClick((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
    } else if (mode === "edit" && e.target === e.currentTarget) {
      // فقط کلیک روی خودِ زمینه انتخاب را برمی‌دارد؛ «click» ِ پس از pointerdown روی یک کادر به <svg> می‌رسد و نباید انتخاب را پاک کند.
      p.onSelect?.(null);
    }
  };
  const swallowClick = (e: RMouseEvent) => e.stopPropagation();

  return (
    <div className="ds-canvas" style={{ width, height: h }}>
      {img ? <img src={img} alt={page.name} draggable={false} style={{ width, height: h }} /> : <div className="ds-canvas-wait" style={{ width, height: h }}>در حالِ ساختِ پیش‌نمایش…</div>}
      <svg className="ds-overlay" viewBox={`0 0 ${page.w} ${page.h}`} width={width} height={h} onClick={clickBg} onPointerMove={move} onPointerUp={up}>
        {mode === "edit" && page.elements.filter((e) => e.role !== "decor" && e.type !== "line").map((el) => {
          const d = drag && drag.id === el.id ? drag : null;
          const sel = p.selected === el.id;
          return (
            <rect key={el.id} x={el.x + (d?.dx ?? 0)} y={el.y + (d?.dy ?? 0)} width={Math.max(2, el.w)} height={Math.max(2, el.h)} className={`ds-hit ${sel ? "is-sel" : ""} ${d ? "is-drag" : ""}`}
              onPointerDown={(e) => down(e, el)} onClick={swallowClick} vectorEffect="non-scaling-stroke" />
          );
        })}
        {mode === "edit" && p.boxes?.map((b) => (
          <rect key={b.id} x={b.x} y={b.y} width={b.w} height={b.h} className={`ds-box ${p.selected === b.id ? "is-sel" : ""}`} onPointerDown={(e) => { e.stopPropagation(); p.onSelect?.(b.id); }} onClick={swallowClick} vectorEffect="non-scaling-stroke" />
        ))}
        {mode === "play" && p.hotspots?.map((hs, i) => (
          <rect key={i} x={hs.x} y={hs.y} width={hs.w} height={hs.h} className="ds-hot" onClick={(e) => { e.stopPropagation(); p.onHotspot?.(hs.to); }} vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
      {p.overlays}
    </div>
  );
}

export function Thumb({ storeId, docId, page, rev, width = 120, active, onClick, label, mode }: { storeId: string; docId: number; page: ScenePage; rev: number; width?: number; active?: boolean; onClick?: () => void; label?: string; mode?: string }) {
  const img = usePreview(designApi.previewUrl(storeId, docId, page.id, width * 2, rev, mode));
  const h = Math.min(220, Math.round((page.h / page.w) * width));
  return (
    <button type="button" className={`ds-thumb ${active ? "is-active" : ""}`} onClick={onClick} aria-pressed={active} title={page.name}>
      <span className="ds-thumb-img" style={{ width, height: h }}>{img ? <img src={img} alt="" draggable={false} style={{ width, height: "100%", objectFit: "cover", objectPosition: "top" }} /> : null}</span>
      <span className="ds-thumb-label">{label ?? page.name}</span>
    </button>
  );
}

// ───────────────────────────── چک‌لیست

export function ChecksPanel({ checks, title = "چک‌لیست" }: { checks: Check[]; title?: string }) {
  if (!checks.length) return null;
  return (
    <div className="ds-checks">
      <div className="ds-sub">{title}</div>
      {checks.map((c) => (
        <div key={c.key} className={`ds-check is-${c.level}`}>
          <Icon name={c.level === "ok" ? "ok" : c.level === "warn" ? "warn" : "info"} size={15} />
          <div>
            <b>{c.title}</b>
            {c.detail ? <span>{c.detail}</span> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

// ───────────────────────────── انتخابِ محصول و تصویر

export function ProductPicker({ products, value, onChange, single }: { products: ProductRow[]; value: number[]; onChange: (v: number[]) => void; single?: boolean }) {
  const set = new Set(value);
  const toggle = (id: number) => {
    if (single) return onChange([id]);
    const n = new Set(set);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    onChange(products.filter((p) => n.has(p.id)).map((p) => p.id));
  };
  return (
    <div className="ds-products">
      {products.map((p) => (
        <button type="button" key={p.id} className={`ds-prod ${set.has(p.id) ? "is-on" : ""}`} onClick={() => toggle(p.id)} aria-pressed={set.has(p.id)}>
          <span className="ds-prod-img">{p.image_url ? <img src={p.image_url} alt="" /> : <i>؟</i>}</span>
          <span className="ds-prod-name">{p.name}</span>
          {p.price !== null ? <span className="ds-prod-price">{p.price === 0 ? "ثبت‌شده: ۰" : `${fa(p.price.toLocaleString("en-US"))}`}</span> : null}
        </button>
      ))}
      {!products.length ? <p className="ds-muted">این فروشگاه هنوز محصولی ندارد.</p> : null}
    </div>
  );
}

export function ImagePicker({ storeId, products, value, onChange, hasLogo }: { storeId: string; products: ProductRow[]; value: string; onChange: (v: string) => void; hasLogo?: boolean }) {
  const [photos, setPhotos] = useState<{ id: number; title: string; thumb: string | null }[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open || photos.length) return;
    designApi.photoAssets(storeId).then((a) => setPhotos(a.slice(0, 60))).catch(() => undefined);
  }, [open, photos.length, storeId]);
  return (
    <div className="ds-imgpick">
      <div className="ds-row">
        <code className="ds-ref">{value || "بدونِ تصویر"}</code>
        <Button size="sm" variant="secondary" type="button" onClick={() => setOpen(!open)}>{open ? "بستن" : "انتخاب"}</Button>
        {value ? <Button size="sm" variant="ghost" type="button" onClick={() => onChange("")}>برداشتن</Button> : null}
      </div>
      {open ? (
        <div className="ds-imggrid">
          {hasLogo ? <button type="button" className="ds-imgcell" onClick={() => onChange("logo")}><span>لوگو</span></button> : null}
          {products.filter((p) => p.image_ref).map((p) => (
            <button type="button" key={p.id} className={`ds-imgcell ${value === p.image_ref ? "is-on" : ""}`} onClick={() => onChange(p.image_ref)} title={p.name}><img src={p.image_url} alt={p.name} /></button>
          ))}
          {photos.map((a) => (
            <button type="button" key={`a${a.id}`} className={`ds-imgcell ${value === `photo:${a.id}` ? "is-on" : ""}`} onClick={() => onChange(`photo:${a.id}`)} title={a.title}>{a.thumb ? <img src={a.thumb} alt={a.title} /> : <span>{a.title}</span>}</button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ───────────────────────────── فرمِ مشخصهٔ صفحه/اسلاید

function toLines(v: unknown): string {
  return Array.isArray(v) ? v.map(String).join("\n") : "";
}

export function SpecForm({ defs, spec, ov, onPatch, storeId }: { defs: FieldDef[]; spec: Record<string, any>; ov: Overview; onPatch: (patch: Record<string, unknown>) => void; storeId: string }) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  useEffect(() => setDrafts({}), [spec.id]);
  const commitText = (k: string, v: string) => {
    setDrafts((d) => {
      const n = { ...d };
      delete n[k];
      return n;
    });
    if (v !== (spec[k] ?? "")) onPatch({ [k]: v });
  };
  return (
    <div className="ds-form">
      {defs.map((d) => {
        const v = spec[d.k];
        if (d.t === "text" || d.t === "number") {
          return (
            <Field key={d.k} label={d.l} wide={d.wide}>
              <Input type={d.t === "number" ? "number" : "text"} min={d.min} max={d.max} value={drafts[d.k] ?? (v ?? "")} onChange={(e) => setDrafts({ ...drafts, [d.k]: e.target.value })}
                onBlur={(e) => commitText(d.k, d.t === "number" ? (e.target.value as string) : e.target.value)} />
            </Field>
          );
        }
        if (d.t === "textarea") {
          return (
            <Field key={d.k} label={d.l} wide>
              <TextArea rows={4} value={drafts[d.k] ?? (v ?? "")} onChange={(e) => setDrafts({ ...drafts, [d.k]: e.target.value })} onBlur={(e) => commitText(d.k, e.target.value)} />
            </Field>
          );
        }
        if (d.t === "lines") {
          return (
            <Field key={d.k} label={`${d.l} (هر خط یکی)`} wide>
              <TextArea rows={4} value={drafts[d.k] ?? toLines(v)} onChange={(e) => setDrafts({ ...drafts, [d.k]: e.target.value })}
                onBlur={(e) => {
                  setDrafts((x) => {
                    const n = { ...x };
                    delete n[d.k];
                    return n;
                  });
                  onPatch({ [d.k]: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) });
                }} />
            </Field>
          );
        }
        if (d.t === "select") {
          return (
            <Field key={d.k} label={d.l}>
              <Select value={String(v ?? "")} onChange={(e) => onPatch({ [d.k]: e.target.value })}>
                {d.opts?.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
              </Select>
            </Field>
          );
        }
        if (d.t === "check") {
          return (
            <label key={d.k} className="ds-check-row"><input type="checkbox" checked={!!v} onChange={(e) => onPatch({ [d.k]: e.target.checked })} /> {d.l}</label>
          );
        }
        if (d.t === "image") {
          return (
            <Field key={d.k} label={d.l} wide>
              <ImagePicker storeId={storeId} products={ov.products} hasLogo={ov.store.has_logo} value={String(v ?? "")} onChange={(x) => onPatch({ [d.k]: x })} />
            </Field>
          );
        }
        if (d.t === "imagelist") {
          const sel: string[] = Array.isArray(v) ? v : [];
          const flip = (ref: string) => onPatch({ [d.k]: sel.includes(ref) ? sel.filter((x) => x !== ref) : [...sel, ref].slice(0, 5) });
          return (
            <Field key={d.k} label={`${d.l} (تا ۵ تصویر؛ ترتیبِ انتخاب)`} wide>
              <div className="ds-imggrid">
                {ov.products.filter((p) => p.image_ref).map((p) => (
                  <button type="button" key={p.id} className={`ds-imgcell ${sel.includes(p.image_ref) ? "is-on" : ""}`} onClick={() => flip(p.image_ref)} title={p.name}>
                    <img src={p.image_url} alt={p.name} />
                  </button>
                ))}
              </div>
            </Field>
          );
        }
        if (d.t === "products") {
          return (
            <Field key={d.k} label={d.l} wide>
              <ProductPicker products={ov.products} value={Array.isArray(v) ? v : []} onChange={(x) => onPatch({ [d.k]: x })} />
            </Field>
          );
        }
        if (d.t === "product") {
          return (
            <Field key={d.k} label={d.l} wide>
              <ProductPicker single products={ov.products} value={v ? [Number(v)] : []} onChange={(x) => onPatch({ [d.k]: x[0] ?? null })} />
            </Field>
          );
        }
        if (d.t === "objs") {
          const rows: Record<string, any>[] = Array.isArray(v) ? v : [];
          const setRow = (i: number, patch: Record<string, unknown>) => onPatch({ [d.k]: rows.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
          return (
            <div key={d.k} className="ds-objs ds-wide">
              <div className="ds-sub">{d.l}</div>
              {rows.map((r, i) => (
                <div key={i} className="ds-obj">
                  {d.sub?.map((s) => (
                    s.t === "check" ? (
                      <label key={s.k} className="ds-check-row"><input type="checkbox" checked={!!r[s.k]} onChange={(e) => setRow(i, { [s.k]: e.target.checked })} /> {s.l}</label>
                    ) : s.t === "product" ? (
                      <Field key={s.k} label={s.l}>
                        <Select value={String(r[s.k] ?? "")} onChange={(e) => setRow(i, { [s.k]: e.target.value ? Number(e.target.value) : null })}>
                          <option value="">— انتخاب —</option>
                          {ov.products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </Select>
                      </Field>
                    ) : s.t === "lines" ? (
                      <Field key={s.k} label={`${s.l} (هر خط یکی)`}>
                        <TextArea rows={3} defaultValue={toLines(r[s.k])} onBlur={(e) => setRow(i, { [s.k]: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })} />
                      </Field>
                    ) : (
                      <Field key={s.k} label={s.l}>
                        <Input defaultValue={r[s.k] ?? ""} onBlur={(e) => e.target.value !== (r[s.k] ?? "") && setRow(i, { [s.k]: e.target.value })} />
                      </Field>
                    )
                  ))}
                  <Button size="sm" variant="ghost" type="button" onClick={() => onPatch({ [d.k]: rows.filter((_, j) => j !== i) })}><Icon name="trash" size={14} /> حذف</Button>
                </div>
              ))}
              <Button size="sm" variant="secondary" type="button" onClick={() => onPatch({ [d.k]: [...rows, Object.fromEntries((d.sub ?? []).map((s) => [s.k, s.t === "check" ? false : s.t === "lines" ? [] : ""]))] })}><Icon name="plus" size={14} /> افزودن</Button>
            </div>
          );
        }
        return null;
      })}
    </div>
  );
}

// ───────────────────────────── بازرسِ عنصر (متن، اندازه، رنگ، جا)

export function ElementInspector({ el, fonts, onSet, onClear, onRemove, hasOverride, storeId, ov }: { el: El; fonts: FontRow[]; onSet: (patch: Record<string, unknown>) => void; onClear: () => void; onRemove: () => void; hasOverride: boolean; storeId: string; ov: Overview }) {
  const [text, setText] = useState(el.text ?? "");
  useEffect(() => setText(el.text ?? ""), [el.id, el.text]);
  const num = (label: string, key: "x" | "y" | "w" | "h") => (
    <Field label={label}>
      <Input type="number" step="0.5" value={Math.round(el[key] * 100) / 100} onChange={(e) => onSet({ [key]: Number(e.target.value) })} />
    </Field>
  );
  const fill = typeof el.fill === "string" ? el.fill : "";
  return (
    <div className="ds-form">
      <div className="ds-sub ds-wide">عنصر «{el.name || el.id}» <Badge tone="neutral">{el.type === "text" ? "متن" : el.type === "image" ? "تصویر" : el.type === "line" ? "خط" : "شکل"}</Badge></div>
      {el.type === "text" ? (
        <>
          <Field label="متن" wide>
            <TextArea rows={3} value={text} onChange={(e) => setText(e.target.value)} onBlur={() => text !== (el.text ?? "") && onSet({ text })} />
          </Field>
          {el.lay?.overflow || el.lay?.truncated ? <p className="ds-warn ds-wide">این متن از جعبه‌اش بیشتر بود؛ جعبه را بزرگ‌تر کن یا متن را کوتاه کن.</p> : null}
          <Field label="فونت">
            <Select value={el.font ?? "vazirmatn"} onChange={(e) => onSet({ font: e.target.value })}>
              {fonts.map((f) => <option key={f.key} value={f.key}>{f.title}</option>)}
            </Select>
          </Field>
          <Field label="وزن">
            <Select value={String(el.weight ?? 400)} onChange={(e) => onSet({ weight: Number(e.target.value) })}>
              {[300, 400, 500, 600, 700, 800].map((w) => <option key={w} value={w}>{fa(w)}</option>)}
            </Select>
          </Field>
          <Field label="اندازه">
            <Input type="number" step="0.5" value={Math.round((el.size ?? 4) * 100) / 100} onChange={(e) => onSet({ size: Number(e.target.value) })} />
          </Field>
          <Field label="چینش">
            <Select value={el.align ?? "auto"} onChange={(e) => onSet({ align: e.target.value })}>
              <option value="auto">خودکار</option><option value="right">راست</option><option value="center">وسط</option><option value="left">چپ</option><option value="justify">دوطرفه</option>
            </Select>
          </Field>
          <ColorField label="رنگِ متن" value={el.color ?? "#000000"} onChange={(v) => onSet({ color: v })} />
        </>
      ) : null}
      {el.type === "image" ? (
        <Field label="تصویر" wide>
          <ImagePicker storeId={storeId} products={ov.products} hasLogo={ov.store.has_logo} value={el.src ?? ""} onChange={(v) => onSet({ src: v })} />
        </Field>
      ) : null}
      {el.type === "rect" || el.type === "ellipse" ? <ColorField label="رنگِ پر" value={fill} onChange={(v) => onSet({ fill: v })} /> : null}
      {num("x", "x")}{num("y", "y")}{num("پهنا", "w")}{num("بلندی", "h")}
      <Field label="شفافیت">
        <Input type="range" min="0" max="1" step="0.05" value={el.opacity ?? 1} onChange={(e) => onSet({ opacity: Number(e.target.value) })} />
      </Field>
      <div className="ds-row ds-wide">
        {hasOverride ? <Button size="sm" variant="secondary" type="button" onClick={onClear}>بازگرداندن به پیش‌فرض</Button> : null}
        <Button size="sm" variant="danger" type="button" onClick={onRemove}><Icon name="trash" size={14} /> حذفِ این عنصر</Button>
      </div>
    </div>
  );
}

export function AddElementMenu({ onAdd }: { onAdd: (el: Record<string, unknown>) => void }) {
  return (
    <div className="ds-row">
      <Button size="sm" variant="secondary" type="button" onClick={() => onAdd({ type: "text", x: 20, y: 20, w: 80, h: 12, text: "متنِ تازه", size: 5, color: "#111827", weight: 600 })}>+ متن</Button>
      <Button size="sm" variant="secondary" type="button" onClick={() => onAdd({ type: "rect", x: 20, y: 40, w: 60, h: 30, fill: "#dbe6ff", radius: 3 })}>+ شکل</Button>
      <Button size="sm" variant="secondary" type="button" onClick={() => onAdd({ type: "image", x: 20, y: 80, w: 70, h: 50, src: "", radius: 2 })}>+ تصویر</Button>
      <Button size="sm" variant="secondary" type="button" onClick={() => onAdd({ type: "line", x: 20, y: 140, w: 100, h: 0, stroke: { color: "#126f85", w: 0.5 } })}>+ خط</Button>
    </div>
  );
}

export function useWidth(ref: { current: HTMLElement | null }, min = 280): number {
  const [w, setW] = useState(600);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.max(min, Math.floor(el.clientWidth - 2))));
    ro.observe(el);
    setW(Math.max(min, Math.floor(el.clientWidth - 2)));
    return () => ro.disconnect();
  }, [ref, min]);
  return w;
}

export function useStable<T>(v: T): T {
  const r = useRef(v);
  const s = JSON.stringify(v);
  const last = useRef(s);
  if (last.current !== s) {
    last.current = s;
    r.current = v;
  }
  return useMemo(() => r.current, [s]); // eslint-disable-line react-hooks/exhaustive-deps
}
