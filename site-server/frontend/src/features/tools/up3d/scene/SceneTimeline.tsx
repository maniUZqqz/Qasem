import { DragEvent, PointerEvent as RPE, useRef, useState } from "react";

import { fa, label } from "../api";
import { byId } from "../editor/model";
import type { Catalog, Issue, Item, KeyFrame, SceneDoc } from "../types";
import type { Clock } from "./clock";
import { useClockPlaying, useClockTime } from "./clock";

function TimeText({ clock, total }: { clock: Clock; total: number }) {
  const t = useClockTime(clock);
  return (
    <span className="u3d-mono u3e-time" data-testid="time">
      {t.toFixed(2)} / {total.toFixed(1)}ث
    </span>
  );
}

function PlayheadLine({ clock, zoom, offset }: { clock: Clock; zoom: number; offset: number }) {
  const t = useClockTime(clock);
  return <div className="u3e-playhead" style={{ left: offset + t * zoom }} />;
}
import { type EdSel, type ObjRef, docDur, keysOf, listObjects, objLabel, shotLabel } from "./model";
import { DND_TYPE, type DragPayload } from "./Viewport";

/**
 * خطِ زمانِ ویرایشگرِ آزاد (زمان چپ‌به‌راست): ردیفِ «نماها» (شات‌های آماده/آزاد)، کلیدهای هر دوربین،
 * برای هر آدم یک ردیفِ «حرکت» (قطعه‌های حرکت: کشیدن = جابه‌جایی، لبه = کش دادن) و یک ردیفِ «جا» (کلیدها)،
 * کلیدهای محصول/شیء/نور، و گفتار (فقط نمایش). کتابخانه ⇐ حرکت را روی ردیفِ آدم، نما را روی «نماها» رها کنید.
 */

type Row =
  | { kind: "shots"; label: string }
  | { kind: "actions"; actor: string; label: string }
  | { kind: "keys"; ref: ObjRef; label: string }
  | { kind: "speech"; label: string };

export type DropTarget = { row: "shots" } | { row: "actions"; actor: string };

type BlockDrag = { list: "actions" | "shots"; id: string; x0: number; s0: number; d0: number; mode: "move" | "start" | "end"; moved: boolean; start: number; duration: number };
type KeyDrag = { ref: ObjRef; t0: number; x0: number; t: number; moved: boolean };

const LABEL_W = 132;
const SNAP = 0.05;

export default function SceneTimeline({
  cat,
  doc,
  clock,
  sel,
  issues,
  onSelect,
  onMoveBlock,
  onMoveKey,
  onDropAsset,
  onAddKey,
  onTogglePlay,
}: {
  cat: Catalog;
  doc: SceneDoc;
  clock: Clock;
  sel: EdSel;
  issues: Issue[];
  onSelect: (s: EdSel) => void;
  onMoveBlock: (list: "actions" | "shots", id: string, start: number, duration: number) => void;
  onMoveKey: (ref: ObjRef, t0: number, t1: number) => void;
  onDropAsset: (p: DragPayload, target: DropTarget, t: number) => void;
  onAddKey: (ref: ObjRef, t: number) => void;
  onTogglePlay: () => void;
}) {
  const [zoom, setZoom] = useState(64);
  const [bdrag, setBdrag] = useState<BlockDrag | null>(null);
  const [kdrag, setKdrag] = useState<KeyDrag | null>(null);
  const bref = useRef<BlockDrag | null>(null);
  const kref = useRef<KeyDrag | null>(null);
  const playing = useClockPlaying(clock);
  const total = docDur(doc);
  const w = Math.max(total * zoom, 300);
  const step = zoom > 110 ? 0.5 : zoom > 45 ? 1 : 2;
  const ticks: number[] = [];
  for (let x = 0; x <= total + 1e-6; x += step) ticks.push(Math.round(x * 10) / 10);
  const errs = new Set(issues.filter((i) => i.level === "error").map((i) => i.path));
  const snap = (v: number) => Math.round(v / SNAP) * SNAP;

  const rows: Row[] = [{ kind: "shots", label: "🎬 نماها" }];
  for (const c of doc.cameras || []) rows.push({ kind: "keys", ref: { kind: "camera", id: c.id }, label: `🎥 ${objLabel(doc, cat, { kind: "camera", id: c.id })}` });
  for (const a of doc.actors) {
    const nm = objLabel(doc, cat, { kind: "actor", id: a.id });
    rows.push({ kind: "actions", actor: a.id, label: `🧍 حرکت: ${nm}` });
    rows.push({ kind: "keys", ref: { kind: "actor", id: a.id }, label: `↔ جا: ${nm}` });
  }
  for (const r of listObjects(doc).filter((x) => x.kind === "product" || x.kind === "prop" || x.kind === "light")) {
    rows.push({ kind: "keys", ref: r, label: `${r.kind === "light" ? "💡" : r.kind === "product" ? "🧴" : "📦"} ${objLabel(doc, cat, r)}` });
  }
  if (doc.speech.length) rows.push({ kind: "speech", label: "🗣 گفتار" });

  const timeAt = (el: HTMLElement, clientX: number) => {
    const r = el.getBoundingClientRect();
    return Math.max(0, Math.min(total, (clientX - r.left) / zoom));
  };

  // ── کشیدنِ قطعه
  const blockDown = (list: "actions" | "shots", it: Item) => (e: RPE<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const cls = (e.target as HTMLElement).dataset.edge;
    const id = it.id || "";
    onSelect(list === "actions" ? { type: "action", id } : { type: "shot", id });
    const d: BlockDrag = { list, id, x0: e.clientX, s0: it.start, d0: it.duration || 1, mode: cls === "s" ? "start" : cls === "e" ? "end" : "move", moved: false, start: it.start, duration: it.duration || 1 };
    bref.current = d;
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const blockMove = (e: RPE<HTMLDivElement>) => {
    const d = bref.current;
    if (!d) return;
    const dx = e.clientX - d.x0;
    if (!d.moved && Math.abs(dx) < 3) return;
    d.moved = true;
    const dt = dx / zoom;
    if (d.mode === "move") d.start = Math.max(0, Math.min(total - 0.2, snap(d.s0 + dt)));
    else if (d.mode === "end") d.duration = Math.max(0.2, snap(d.d0 + dt));
    else {
      const ns = Math.max(0, Math.min(d.s0 + d.d0 - 0.2, snap(d.s0 + dt)));
      d.duration = Math.max(0.2, d.s0 + d.d0 - ns);
      d.start = ns;
    }
    setBdrag({ ...d });
  };
  const blockUp = () => {
    const d = bref.current;
    bref.current = null;
    setBdrag(null);
    if (d?.moved) onMoveBlock(d.list, d.id, Math.round(d.start * 1000) / 1000, Math.round(d.duration * 1000) / 1000);
  };

  // ── کشیدنِ کلید
  const keyDown = (ref: ObjRef, k: KeyFrame) => (e: RPE<HTMLSpanElement>) => {
    e.preventDefault();
    e.stopPropagation();
    onSelect({ type: "key", ref, t: k.t });
    clock.set(k.t);
    kref.current = { ref, t0: k.t, x0: e.clientX, t: k.t, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const keyMove = (e: RPE<HTMLSpanElement>) => {
    const d = kref.current;
    if (!d) return;
    const dx = e.clientX - d.x0;
    if (!d.moved && Math.abs(dx) < 3) return;
    d.moved = true;
    d.t = Math.max(0, Math.min(total, snap(d.t0 + dx / zoom)));
    setKdrag({ ...d });
  };
  const keyUp = () => {
    const d = kref.current;
    kref.current = null;
    setKdrag(null);
    if (d?.moved && Math.abs(d.t - d.t0) > 1e-4) onMoveKey(d.ref, d.t0, Math.round(d.t * 1000) / 1000);
  };

  // ── رها کردن از کتابخانه
  const dropOn = (target: DropTarget | null) => (e: DragEvent<HTMLDivElement>) => {
    const raw = e.dataTransfer.getData(DND_TYPE);
    if (!raw || !target) return;
    e.preventDefault();
    try {
      onDropAsset(JSON.parse(raw) as DragPayload, target, snap(timeAt(e.currentTarget, e.clientX)));
    } catch {
      /* نامعتبر */
    }
  };
  const over = (e: DragEvent<HTMLDivElement>) => {
    if (e.dataTransfer.types.includes(DND_TYPE)) e.preventDefault();
  };

  // ── زمان (خط‌کش)
  const scrubRef = useRef(false);
  const rulerDown = (e: RPE<HTMLDivElement>) => {
    scrubRef.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    clock.set(Math.round(timeAt(e.currentTarget, e.clientX) * 100) / 100);
  };
  const rulerMove = (e: RPE<HTMLDivElement>) => {
    if (scrubRef.current) clock.set(Math.round(timeAt(e.currentTarget, e.clientX) * 100) / 100);
  };

  const block = (list: "actions" | "shots", it: Item, i: number, text: string, extraCls = "") => {
    const id = it.id || `${list}-${i}`;
    const drag = bdrag && bdrag.list === list && bdrag.id === it.id ? bdrag : null;
    const start = drag ? drag.start : it.start;
    const dur = drag ? drag.duration : it.duration || 0.5;
    const isSel = sel && ((list === "actions" && sel.type === "action") || (list === "shots" && sel.type === "shot")) && sel.id === it.id;
    const err = errs.has(`${list}[${doc[list].indexOf(it)}]`);
    const m = list === "actions" ? byId(cat, "motion", it.motion) : undefined;
    const blend = list === "actions" && typeof it.params?.blend === "number" ? (it.params.blend as number) : m?.source?.type === "clip" ? Math.min(0.3, dur * 0.25) : 0;
    return (
      <div
        key={id}
        className={`u3e-blk ${list} ${extraCls} ${isSel ? "sel" : ""} ${err ? "err" : ""} ${m?.layer ? "layer" : ""}`}
        style={{ left: start * zoom, width: Math.max(8, dur * zoom) }}
        title={text}
        data-block={`${list}:${it.id}`}
        onPointerDown={blockDown(list, it)}
        onPointerMove={blockMove}
        onPointerUp={blockUp}
        onPointerCancel={blockUp}
      >
        {blend > 0 && (
          <>
            <i className="fade l" style={{ width: Math.min(blend * zoom, (dur * zoom) / 2) }} />
            <i className="fade r" style={{ width: Math.min(blend * zoom, (dur * zoom) / 2) }} />
          </>
        )}
        <span className="tx">{text}</span>
        <span className="edge s" data-edge="s" />
        <span className="edge e" data-edge="e" />
      </div>
    );
  };

  return (
    <div className="u3e-tl" dir="ltr">
      <div className="u3e-tl-bar" dir="rtl">
        <button type="button" className="u3e-tbtn" onClick={() => clock.set(0)} title="به شروع (Home)">
          ⏮
        </button>
        <button type="button" className="u3e-tbtn play" onClick={onTogglePlay} title="پخش/توقف (Space)" data-testid="play">
          {playing ? "⏸" : "▶"}
        </button>
        <TimeText clock={clock} total={total} />
        <span className="u3e-tl-hint">کتابخانه ⇐ حرکت را روی ردیفِ آدم و نما را روی «نماها» رها کنید · دوبار زدن روی ردیفِ «جا» = کلید</span>
        <span className="ms-auto flex items-center gap-1">
          <button type="button" className="u3e-tbtn" onClick={() => setZoom((z) => Math.max(18, z / 1.3))} title="کوچک‌نمایی">
            −
          </button>
          <button type="button" className="u3e-tbtn" onClick={() => setZoom((z) => Math.min(320, z * 1.3))} title="بزرگ‌نمایی">
            +
          </button>
        </span>
      </div>
      <div className="u3e-tl-body">
        <div className="u3e-tl-inner" style={{ width: w + LABEL_W + 16 }}>
          <div className="u3e-tl-row ruler">
            <div className="u3e-tl-lab" />
            <div className="u3e-ruler" style={{ width: w }} onPointerDown={rulerDown} onPointerMove={rulerMove} onPointerUp={() => (scrubRef.current = false)} data-testid="ruler">
              {ticks.map((x) => (
                <i key={x} style={{ left: x * zoom }}>
                  {fa(x)}
                </i>
              ))}
            </div>
          </div>
          {rows.map((row, ri) => {
            if (row.kind === "shots")
              return (
                <div key={`r${ri}`} className="u3e-tl-row shots" data-row="shots">
                  <div className="u3e-tl-lab" dir="rtl">{row.label}</div>
                  <div className="u3e-lane" style={{ width: w }} onDragOver={over} onDrop={dropOn({ row: "shots" })}>
                    {doc.shots.map((it, i) => block("shots", it, i, shotLabel(cat, doc, it), it.camera ? "free" : ""))}
                    {doc.shots.length === 0 && <span className="u3e-lane-hint" dir="rtl">نمایی نیست — نمای آماده را این‌جا رها کنید یا برای دوربینِ آزاد کلید بزنید</span>}
                  </div>
                </div>
              );
            if (row.kind === "actions")
              return (
                <div key={`r${ri}`} className="u3e-tl-row actions" data-row={`actions:${row.actor}`}>
                  <div className="u3e-tl-lab" dir="rtl">{row.label}</div>
                  <div className="u3e-lane" style={{ width: w }} onDragOver={over} onDrop={dropOn({ row: "actions", actor: row.actor })}>
                    {doc.actions.map((it, i) => (it.actor === row.actor ? block("actions", it, i, label(byId(cat, "motion", it.motion)) || it.motion || "") : null))}
                  </div>
                </div>
              );
            if (row.kind === "speech")
              return (
                <div key={`r${ri}`} className="u3e-tl-row speech">
                  <div className="u3e-tl-lab" dir="rtl">{row.label}</div>
                  <div className="u3e-lane" style={{ width: w }}>
                    {doc.speech.map((s, i) => (
                      <div key={s.id || i} className="u3e-blk speech ro" style={{ left: s.start * zoom, width: Math.max(8, (s.duration || 1) * zoom) }} title={`${s.text} (در حالتِ گام‌به‌گام ویرایش کنید)`}>
                        <span className="tx" dir="rtl">{s.text}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            const keys = keysOf(doc, row.ref);
            return (
              <div key={`r${ri}`} className={`u3e-tl-row keys ${row.ref.kind}`} data-row={`keys:${row.ref.kind}:${row.ref.id}`}>
                <div
                  className="u3e-tl-lab"
                  dir="rtl"
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelect({ type: "obj", ref: row.ref })}
                  onKeyDown={(e) => e.key === "Enter" && onSelect({ type: "obj", ref: row.ref })}
                >
                  {row.label}
                </div>
                <div
                  className="u3e-lane"
                  style={{ width: w }}
                  onDoubleClick={(e) => onAddKey(row.ref, snap(timeAt(e.currentTarget, e.clientX)))}
                  title="دوبار بزنید: کلید در همین زمان"
                >
                  {keys.length > 1 && <i className="u3e-span" style={{ left: keys[0].t * zoom, width: (keys[keys.length - 1].t - keys[0].t) * zoom }} />}
                  {keys.map((k) => {
                    const drag = kdrag && kdrag.ref.kind === row.ref.kind && kdrag.ref.id === row.ref.id && Math.abs(kdrag.t0 - k.t) < 1e-4 ? kdrag : null;
                    const kt = drag ? drag.t : k.t;
                    const isSel = sel?.type === "key" && sel.ref.kind === row.ref.kind && sel.ref.id === row.ref.id && Math.abs(sel.t - k.t) < 1e-3;
                    return (
                      <span
                        key={k.t}
                        className={`u3e-key ${isSel ? "sel" : ""} ez-${k.ease || "smooth"}`}
                        style={{ left: kt * zoom }}
                        title={`${fa(kt.toFixed(2))}ث`}
                        data-key={`${row.ref.kind}:${row.ref.id}:${k.t}`}
                        onPointerDown={keyDown(row.ref, k)}
                        onPointerMove={keyMove}
                        onPointerUp={keyUp}
                        onPointerCancel={keyUp}
                      />
                    );
                  })}
                </div>
              </div>
            );
          })}
          <PlayheadLine clock={clock} zoom={zoom} offset={LABEL_W} />
        </div>
      </div>
    </div>
  );
}
