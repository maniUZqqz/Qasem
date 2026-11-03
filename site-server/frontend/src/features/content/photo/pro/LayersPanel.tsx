import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as RPointerEvent, ReactNode } from "react";

import Icon from "../../../../components/Icon";
import { Select, Spinner, fa } from "../../../../components/ui";
import type { LayersPanelProps, MaskKind } from "./panelTypes";
import { BLEND_MODES, BlendMode, LAYER_ICON, Layer, ProState } from "./types";
import "./panels.css";

/** آیکون‌های کوچکِ هم‌ضخامت با آیکون‌های پنل */
function Ico({ d, size = 17 }: { d: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

const D_EYE = "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z";
const D_EYE_OFF = "M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3 3.8M6.5 6.6C3.6 8.4 2 12 2 12s3.6 7 10 7a9.8 9.8 0 0 0 4.2-.9M9.9 9.9a3 3 0 0 0 4.2 4.2";
const D_LOCK = "M6 11h12v9H6v-9Zm2 0V8a4 4 0 0 1 8 0v3";
const D_UNLOCK = "M6 11h12v9H6v-9Zm2 0V8a4 4 0 0 1 7.6-1.7";
const D_GRIP = "M8 7h8M8 12h8M8 17h8";
const D_MASK = "M4 4h16v16H4V4Zm8 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z";

const MASK_LABEL: Record<string, string> = { paint: "نقاشی", linear: "شیب خطی", radial: "شیب شعاعی" };
const TRIPLE = new Set(["image", "text", "shape"]);

const mapLayer = (id: string, fn: (l: Layer) => Layer) => (s: ProState): ProState => ({
  ...s,
  layers: s.layers.map((l) => (l.id === id ? fn(l) : l)),
});

type Menu = null | "add" | "pick" | "mask";

/** پنلِ لایه‌ها (مثلِ فتوشاپ): بالاترین لایه بالای فهرست است. */
export default function LayersPanel(props: LayersPanelProps) {
  const { state, hist, activeId, setActiveId, actions, assets, storeLogo } = props;
  const layers = state.layers;
  const n = layers.length;
  const display = useMemo(() => [...layers].reverse(), [layers]);
  const active = layers.find((l) => l.id === activeId) ?? null;
  const activeIndex = active ? layers.indexOf(active) : -1;

  const [menu, setMenu] = useState<Menu>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [merging, setMerging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [drag, setDrag] = useState<{ id: string; target: number } | null>(null);
  const dragRef = useRef<{ id: string; target: number } | null>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const fileRef = useRef<HTMLInputElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const footRef = useRef<HTMLDivElement>(null);

  // بستنِ منو با کلیک بیرون یا Esc
  useEffect(() => {
    if (!menu) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (headRef.current?.contains(t) || footRef.current?.contains(t)) return;
      setMenu(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(null);
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  const toggle = (l: Layer, key: "visible" | "locked") =>
    hist.apply(
      key === "visible" ? (l.visible ? `پنهان کردنِ «${l.name}»` : `نمایشِ «${l.name}»`) : l.locked ? `بازکردنِ قفلِ «${l.name}»` : `قفل کردنِ «${l.name}»`,
      mapLayer(l.id, (x) => ({ ...x, [key]: !x[key] }) as Layer),
    );

  const startRename = (l: Layer) => {
    if (l.locked) return;
    setRenaming(l.id);
    setDraft(l.name);
  };
  const commitRename = () => {
    const id = renaming;
    setRenaming(null);
    const name = draft.trim().slice(0, 60);
    if (!id || !name) return;
    hist.apply("تغییر نام", mapLayer(id, (l) => ({ ...l, name })));
  };

  // ───────────────────────── کشیدن برای جابه‌جایی (pointer؛ با لمس هم کار می‌کند)
  const targetAt = (y: number): number => {
    let t = display.length - 1;
    for (let i = 0; i < display.length; i++) {
      const el = rowRefs.current[display[i].id];
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (y < r.bottom) {
        t = i;
        break;
      }
    }
    return t;
  };
  const gripDown = (e: RPointerEvent<HTMLButtonElement>, l: Layer) => {
    if (l.locked || e.button > 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setActiveId(l.id);
    const d = { id: l.id, target: display.findIndex((x) => x.id === l.id) };
    dragRef.current = d;
    setDrag(d);
  };
  const gripMove = (e: RPointerEvent<HTMLButtonElement>) => {
    const d = dragRef.current;
    if (!d) return;
    const t = targetAt(e.clientY);
    if (t !== d.target) {
      const next = { ...d, target: t };
      dragRef.current = next;
      setDrag(next);
    }
  };
  const gripUp = (e: RPointerEvent<HTMLButtonElement>) => {
    const d = dragRef.current;
    dragRef.current = null;
    setDrag(null);
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    if (!d) return;
    const idx = n - 1 - d.target;
    if (idx !== layers.findIndex((x) => x.id === d.id)) actions.reorder(d.id, idx);
  };
  const gripCancel = () => {
    dragRef.current = null;
    setDrag(null);
  };

  const thumbOf = (l: Layer): ReactNode => {
    if (l.type === "image") {
      const src = l.src;
      const url = src.kind === "asset" ? assets.find((a) => a.id === src.asset)?.thumb : storeLogo;
      if (url) return <img src={url} alt="" />;
    }
    return <span aria-hidden="true">{LAYER_ICON[l.type]}</span>;
  };

  const setOpacity = (v: number, commit: boolean) => {
    if (!active) return;
    hist.live(mapLayer(active.id, (l) => ({ ...l, opacity: v / 100 })));
    if (commit) hist.end("شفافیتِ لایه");
  };

  const lowerSibling = activeIndex > 0 ? layers[activeIndex - 1] : null;
  const canMerge = !!active && !!lowerSibling && !active.locked && !lowerSibling.locked && TRIPLE.has(active.type) && TRIPLE.has(lowerSibling.type);

  const doMerge = async () => {
    if (!active || merging) return;
    setMerging(true);
    try {
      const id = await actions.mergeDown(active.id);
      if (id) setActiveId(id);
    } finally {
      setMerging(false);
    }
  };

  const doUpload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setMenu(null);
    try {
      await actions.uploadImage(file);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const addItem = (testId: string, label: string, fn: () => void, disabled = false) => (
    <button type="button" data-testid={testId} disabled={disabled} onClick={() => { setMenu(null); fn(); }}>
      {label}
    </button>
  );

  const addMask = (kind: MaskKind) => {
    if (!active) return;
    setMenu(null);
    actions.addMask(active.id, kind);
  };

  const invertMask = () => {
    if (!active?.mask) return;
    hist.apply("معکوس کردنِ ماسک", mapLayer(active.id, (l) => (l.mask ? { ...l, mask: { ...l.mask, invert: !l.mask.invert } } : l)));
  };

  const addMaskItem = (testId: string, label: string, fn: () => void) => (
    <button type="button" data-testid={testId} onClick={fn}>
      {label}
    </button>
  );

  return (
    <div className="pn-root" data-testid="layers-panel">
      <div className="pn-head" ref={headRef}>
        <span className="pn-title">لایه‌ها</span>
        <span className="pn-count" data-testid="layer-count">{fa(n)} لایه</span>
        {uploading && <Spinner size={14} />}
        <button
          type="button" className="pn-btn primary" data-testid="layer-add" aria-haspopup="menu" aria-expanded={menu === "add" || menu === "pick"}
          onClick={() => setMenu(menu === "add" || menu === "pick" ? null : "add")} aria-label="افزودنِ لایه"
        >
          <Icon name="plus" size={15} /> لایه
        </button>
        <input
          ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" hidden data-testid="layer-upload-input"
          onChange={(e) => void doUpload(e.target.files?.[0])}
        />
        {menu === "add" && (
          <div className="pn-menu" role="menu">
            {addItem("layer-add-text", "متن", actions.addText)}
            {addItem("layer-add-rect", "مستطیل", () => actions.addShape("rect"))}
            {addItem("layer-add-ellipse", "بیضی", () => actions.addShape("ellipse"))}
            {addItem("layer-add-line", "خط", () => actions.addShape("line"))}
            <hr />
            <button type="button" data-testid="layer-add-image" onClick={() => setMenu("pick")}>تصویر از کتابخانه…</button>
            <button type="button" data-testid="layer-add-upload" onClick={() => fileRef.current?.click()}>آپلودِ تصویر…</button>
            {addItem("layer-add-logo", "لوگوی فروشگاه", actions.addLogo, !storeLogo)}
            <hr />
            {addItem("layer-add-adjust", "لایهٔ تنظیم (نور و رنگِ محلی)", actions.addAdjust)}
            {addItem("layer-add-retouch", "لایهٔ روتوش (کلون / ترمیم)", actions.addRetouch)}
            {addItem("layer-add-watermark", "واترمارک (تکرار روی عکس)", actions.addWatermark)}
          </div>
        )}
        {menu === "pick" && (
          <div className="pn-menu" role="dialog" aria-label="انتخابِ تصویر از کتابخانه">
            <div className="pn-menu-title">یک تصویر از کتابخانه انتخاب کنید</div>
            {assets.length === 0 ? (
              <div className="pn-muted" style={{ padding: 10 }}>کتابخانه خالی است.</div>
            ) : (
              <div className="pn-pick" data-testid="layer-asset-pick">
                {assets.map((a) => (
                  <button key={a.id} type="button" title={a.title} aria-label={a.title} data-asset-id={a.id} onClick={() => { setMenu(null); actions.addImageFromAsset(a.id); }}>
                    <img src={a.thumb} alt="" />
                  </button>
                ))}
              </div>
            )}
            <button type="button" onClick={() => setMenu("add")}>بازگشت</button>
          </div>
        )}
      </div>

      <div className="pn-list" role="list" aria-label="فهرستِ لایه‌ها" data-testid="layer-list">
        {display.map((l, di) => {
          const isActive = l.id === activeId;
          const cls = [
            "pn-row", isActive ? "is-active" : "", l.visible ? "" : "is-off", drag?.id === l.id ? "is-dragging" : "",
            drag && drag.id !== l.id && drag.target === di ? (di < display.findIndex((x) => x.id === drag.id) ? "drop-top" : "drop-bottom") : "",
          ].join(" ");
          const idx = layers.indexOf(l);
          return (
            <div key={l.id} ref={(el) => { rowRefs.current[l.id] = el; }} role="listitem" className={cls} data-testid="layer-row" data-layer-id={l.id} data-type={l.type} data-active={isActive ? "1" : "0"}>
              <button
                type="button" className="pn-grip" aria-label={`جابه‌جایی «${l.name}» (بکشید)`} disabled={l.locked} data-testid="layer-grip"
                onPointerDown={(e) => gripDown(e, l)} onPointerMove={gripMove} onPointerUp={gripUp} onPointerCancel={gripCancel}
              >
                <Ico d={D_GRIP} size={15} />
              </button>
              <button
                type="button" className={`pn-ico ${l.visible ? "" : "is-off"}`} data-testid="layer-visible" aria-pressed={l.visible}
                aria-label={l.visible ? `پنهان کردنِ «${l.name}»` : `نمایشِ «${l.name}»`} onClick={() => toggle(l, "visible")}
              >
                <Ico d={l.visible ? D_EYE : D_EYE_OFF} />
              </button>
              <button
                type="button" className={`pn-ico ${l.locked ? "is-on" : ""}`} data-testid="layer-lock" aria-pressed={l.locked}
                aria-label={l.locked ? `بازکردنِ قفلِ «${l.name}»` : `قفل کردنِ «${l.name}»`} onClick={() => toggle(l, "locked")}
              >
                <Ico d={l.locked ? D_LOCK : D_UNLOCK} />
              </button>
              {renaming === l.id ? (
                <div className="pn-select">
                  <span className="pn-thumb">{thumbOf(l)}</span>
                  <input
                    className="u-input pn-rename" value={draft} autoFocus maxLength={60} aria-label="نامِ لایه" data-testid="layer-rename-input"
                    onChange={(e) => setDraft(e.target.value)} onBlur={commitRename}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitRename();
                      else if (e.key === "Escape") setRenaming(null);
                    }}
                  />
                </div>
              ) : (
                <button
                  type="button" className="pn-select" aria-current={isActive ? "true" : undefined} data-testid="layer-select"
                  onClick={() => setActiveId(l.id)} onDoubleClick={() => startRename(l)} title="دوبار کلیک = تغییر نام"
                >
                  <span className="pn-thumb">{thumbOf(l)}</span>
                  <span className="pn-name">{l.name}</span>
                </button>
              )}
              {l.mask && (
                <button
                  type="button" className="pn-maskbadge" data-testid="layer-mask-badge" title={`ماسک: ${MASK_LABEL[l.mask.type]}${l.mask.invert ? " (معکوس)" : ""}`}
                  aria-label="ماسکِ لایه"
                  onClick={() => {
                    setActiveId(l.id);
                    if (l.mask?.type === "paint") actions.paintMask(l.id);
                  }}
                >
                  <Ico d={D_MASK} size={12} />
                  {MASK_LABEL[l.mask.type]}
                </button>
              )}
              {isActive && (
                <div className="pn-rowtools">
                  <button type="button" className="pn-btn icon" data-testid="layer-dup" disabled={l.type === "base"} aria-label="کپی از لایه (Ctrl+J)" title="کپی از لایه (Ctrl+J)" onClick={() => actions.duplicate(l.id)}>
                    <Icon name="copy" size={15} />
                  </button>
                  <button type="button" className="pn-btn icon danger" data-testid="layer-del" disabled={l.type === "base" || l.locked} aria-label="حذفِ لایه" title="حذفِ لایه (Delete)" onClick={() => actions.remove(l.id)}>
                    <Icon name="trash" size={15} />
                  </button>
                  <button type="button" className="pn-btn icon" data-testid="layer-up" disabled={l.locked || idx >= n - 1} aria-label="یک پله بالاتر" title="یک پله بالاتر" onClick={() => actions.reorder(l.id, idx + 1)}>
                    <Icon name="up" size={15} />
                  </button>
                  <button type="button" className="pn-btn icon" data-testid="layer-down" disabled={l.locked || idx <= 0} aria-label="یک پله پایین‌تر" title="یک پله پایین‌تر" onClick={() => actions.reorder(l.id, idx - 1)}>
                    <Icon name="down" size={15} />
                  </button>
                  <button type="button" className="pn-btn sm" data-testid="layer-rename" disabled={l.locked} onClick={() => startRename(l)}>تغییر نام</button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {active ? (
        <div className="pn-strip" data-testid="layer-strip">
          <div className="pn-strip-row">
            <label className="ws-slider" style={{ margin: 0 }}>
              <span className="ws-slider-head">
                <span>{active.type === "adjust" ? "شدتِ اثر" : "شفافیت"}</span>
                <span className="ws-slider-val" dir="ltr">{fa(Math.round(active.opacity * 100))}%</span>
              </span>
              <input
                type="range" min={0} max={100} step={1} value={Math.round(active.opacity * 100)} disabled={active.locked} aria-label="شفافیتِ لایه"
                data-testid="layer-opacity" onChange={(e) => setOpacity(Number(e.target.value), false)}
                onPointerUp={() => hist.end("شفافیتِ لایه")} onKeyUp={() => hist.end("شفافیتِ لایه")} onBlur={() => hist.end("شفافیتِ لایه")}
              />
            </label>
          </div>
          <label className="ws-field" style={{ margin: 0 }}>
            <span>حالتِ ترکیب</span>
            <Select
              className="pn-select-full" value={active.blend} disabled={active.locked || active.type === "adjust" || active.type === "retouch"} aria-label="حالتِ ترکیب"
              data-testid="layer-blend" onChange={(e) => hist.apply("حالتِ ترکیب", mapLayer(active.id, (l) => ({ ...l, blend: e.target.value as BlendMode })))}
            >
              {BLEND_MODES.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
            </Select>
          </label>
        </div>
      ) : (
        <p className="pn-hint">یک لایه را انتخاب کنید.</p>
      )}

      <div className="pn-head" ref={footRef} style={{ flexWrap: "wrap" }}>
        <button type="button" className="pn-btn" data-testid="layer-merge" disabled={!canMerge || merging} onClick={() => void doMerge()} title="تلفیق با لایهٔ زیرین (فقط تصویر / متن / شکل)">
          {merging ? <Spinner size={13} /> : null} تلفیق با زیرین
        </button>
        {active && !active.mask && (
          <span style={{ position: "relative" }}>
            <button type="button" className="pn-btn" data-testid="mask-add" aria-haspopup="menu" aria-expanded={menu === "mask"} disabled={active.locked} onClick={() => setMenu(menu === "mask" ? null : "mask")}>
              <Ico d={D_MASK} size={14} /> افزودنِ ماسک
            </button>
            {menu === "mask" && (
              <div className="pn-menu" role="menu" style={{ insetInlineStart: 0 }}>
                {addMaskItem("mask-add-reveal", "ماسک سفید (همه دیده شود)", () => addMask("reveal"))}
                {addMaskItem("mask-add-hide", "ماسک سیاه (با قلم باز کن)", () => addMask("hide"))}
                {addMaskItem("mask-add-linear", "شیبِ خطی", () => addMask("linear"))}
                {addMaskItem("mask-add-radial", "شیبِ شعاعی", () => addMask("radial"))}
              </div>
            )}
          </span>
        )}
        {active?.mask && (
          <>
            {active.mask.type === "paint" && (
              <button type="button" className="pn-btn" data-testid="mask-paint" onClick={() => actions.paintMask(active.id)}>نقاشی روی ماسک</button>
            )}
            <button type="button" className={`pn-btn ${active.mask.invert ? "is-on" : ""}`} data-testid="mask-invert" aria-pressed={active.mask.invert} disabled={active.locked} onClick={invertMask}>معکوس</button>
            <button type="button" className="pn-btn danger" data-testid="mask-remove" disabled={active.locked} onClick={() => actions.removeMask(active.id)}>حذفِ ماسک</button>
          </>
        )}
        <button type="button" className="pn-btn" data-testid="mask-from-selection" disabled={!active || active.locked} onClick={() => active && actions.maskFromSelection(active.id)} title="ناحیهٔ انتخاب‌شده را ماسکِ این لایه کن">
          ماسک از انتخاب
        </button>
      </div>
    </div>
  );

}
