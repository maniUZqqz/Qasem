import { fa } from "../api";
import type { Catalog, SceneDoc } from "../types";
import { type EdSel, KIND_FA, type ObjKind, type ObjRef, keysOf, listObjects, objLabel, sameRef } from "./model";

/** فهرستِ صحنه (Outliner): محیط، آدم‌ها، محصول‌ها، اشیا، نورها، دوربین‌ها — زدن = انتخاب، دوبار = قاب گرفتن. */

const GROUPS: { kind: ObjKind; title: string; icon: string }[] = [
  { kind: "environment", title: "محیط", icon: "🏠" },
  { kind: "actor", title: "آدم‌ها", icon: "🧍" },
  { kind: "product", title: "محصول‌ها", icon: "🧴" },
  { kind: "prop", title: "اشیا", icon: "📦" },
  { kind: "light", title: "نورها", icon: "💡" },
  { kind: "camera", title: "دوربین‌ها", icon: "🎥" },
];

export default function Outliner({
  cat,
  doc,
  sel,
  onSelect,
  onFrame,
  onDelete,
}: {
  cat: Catalog;
  doc: SceneDoc;
  sel: EdSel;
  onSelect: (s: EdSel) => void;
  onFrame: (r: ObjRef) => void;
  onDelete: (r: ObjRef) => void;
}) {
  const all = listObjects(doc);
  const selRef = sel && (sel.type === "obj" || sel.type === "key") ? sel.ref : sel?.type === "target" ? { kind: "camera" as const, id: sel.id } : null;
  return (
    <div className="u3e-outliner">
      {GROUPS.map((g) => {
        const items = all.filter((r) => r.kind === g.kind);
        return (
          <div key={g.kind} className="u3e-og">
            <div className="u3e-og-h">
              <span>
                {g.icon} {g.title}
              </span>
              <span className="n">{fa(items.length)}</span>
            </div>
            {items.length === 0 && <div className="u3e-empty">— (از کتابخانه بکشید)</div>}
            {items.map((r) => {
              const n = keysOf(doc, r).length;
              return (
                <div
                  key={`${r.kind}:${r.id}`}
                  role="button"
                  tabIndex={0}
                  className={`u3e-orow ${sameRef(selRef, r) ? "sel" : ""}`}
                  onClick={() => onSelect({ type: "obj", ref: r })}
                  onDoubleClick={() => onFrame(r)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onSelect({ type: "obj", ref: r });
                  }}
                  data-obj={`${r.kind}:${r.id}`}
                >
                  <span className="t">{objLabel(doc, cat, r)}</span>
                  <span className="id u3d-mono">{r.id}</span>
                  {n > 0 && <span className="kb" title={`${fa(n)} کلید`}>◆{fa(n)}</span>}
                  {r.kind !== "environment" && (
                    <button
                      type="button"
                      className="x"
                      title={`حذفِ ${KIND_FA[r.kind]}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(r);
                      }}
                    >
                      ×
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
