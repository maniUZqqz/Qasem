import { ReactNode } from "react";

import { Button, Field, Select } from "../../../../components/ui";
import { fa, label } from "../api";
import { DraftInput, DraftNumber } from "../editor/fields";
import { MOVES_FA, byId } from "../editor/model";
import ParamInputs from "../editor/ParamInputs";
import type { Actor, Catalog, Ease, Item, KeyFrame, LightRef, LightType, ProductRef, PropRef, SceneDoc, Transform, UploadResult, Vec3 } from "../types";
import { EASES, round3 } from "./anim";
import { rebuildPreview, usePreview, type PreviewKind } from "./loaders";
import {
  type EdSel,
  KIND_FA,
  LIGHT_FA,
  type ObjRef,
  addKey,
  deleteKey,
  findKey,
  keysOf,
  moveKey,
  objLabel,
  record,
  transformOf,
  writeTransform,
} from "./model";

/**
 * بازرسِ ویرایشگرِ آزاد: هر چه انتخاب شده — شیء (جا/چرخش/اندازه، ظاهر، کلیدها)، کلید (زمان، گذار، مقدار)،
 * قطعهٔ حرکت (حرکت، زمان، پارامترها، نرمیِ ورود/خروج) یا شات (نمای آماده یا دوربینِ آزاد).
 */

export type Ed = {
  cat: Catalog;
  doc: SceneDoc;
  sel: EdSel;
  t: number;
  setSel: (s: EdSel) => void;
  change: (fn: (d: SceneDoc) => void) => void;
  upload: (f: File) => Promise<UploadResult | null>;
  capture: () => { pos: Vec3; target: Vec3; lens: number } | null;
  goTo: (pos: Vec3, target: Vec3) => void;
  seek: (t: number) => void;
  cameraView: boolean;
  setCameraView: (v: boolean) => void;
};

const AX = ["X ⟷", "Y ↕ عمق", "Z ↑"];

function Vec({ label: lbl, value, step, onCommit, disabled, hints = AX }: { label: string; value: Vec3; step: number; onCommit: (v: Vec3) => void; disabled?: boolean[]; hints?: string[] }) {
  return (
    <div className="u3e-vec">
      <span className="lb">{lbl}</span>
      {[0, 1, 2].map((i) => (
        <label key={i} className="c">
          <small>{hints[i]}</small>
          <DraftNumber
            value={round3(value[i])}
            step={step}
            disabled={disabled?.[i]}
            onCommit={(v) => {
              if (v == null) return;
              const n = [...value] as Vec3;
              n[i] = v;
              onCommit(n);
            }}
          />
        </label>
      ))}
    </div>
  );
}

function Sec({ title, children, extra }: { title: string; children: ReactNode; extra?: ReactNode }) {
  return (
    <section className="u3e-sec">
      <div className="u3e-sec-h">
        <b>{title}</b>
        {extra}
      </div>
      <div className="u3e-sec-b">{children}</div>
    </section>
  );
}

function PreviewLine({ kind, id }: { kind: PreviewKind; id: string }) {
  const p = usePreview(kind, id);
  const text: Record<string, string> = {
    file: "مدلِ خودِ بسته در نما",
    ready: "پیش‌نمایشِ سه‌بعدیِ موتور آماده است",
    building: "پیش‌نمایشِ سه‌بعدی روی کارگر ساخته می‌شود… (فعلاً جانشین)",
    failed: "ساختِ پیش‌نمایش ناموفق بود (جانشینِ ساده)",
    none: "پیش‌نمایش ندارد",
    unsupported: "جانشینِ ساده",
    loading: "…",
  };
  return (
    <div className="u3e-note">
      {text[p.state] || p.state}
      {p.state === "failed" && (
        <Button size="sm" variant="ghost" onClick={() => void rebuildPreview(kind, id)}>
          ساختِ دوباره
        </Button>
      )}
    </div>
  );
}

// ───────────────────────── جا و کلیدهای یک شیء

function TransformSec({ ed, objRef: ref }: { ed: Ed; objRef: ObjRef }) {
  const { cat, doc, t, change } = ed;
  const tr = transformOf(doc, cat, ref, t);
  const keys = keysOf(doc, ref);
  const keyed = keys.length > 0;
  const actor = ref.kind === "actor";
  const light = ref.kind === "light";
  const write = (next: Transform) => change((d) => void writeTransform(d, cat, ref, next, t));
  const uniform = Math.abs(tr.scale[0] - tr.scale[1]) < 1e-6 && Math.abs(tr.scale[1] - tr.scale[2]) < 1e-6;
  return (
    <Sec
      title={keyed ? `جا در زمانِ ${fa(t.toFixed(2))}ث` : "جا، چرخش و اندازه"}
      extra={keyed ? <span className="u3e-pill">کلیددار · تغییر = کلید در همین زمان</span> : undefined}
    >
      <Vec label="جا (متر)" value={tr.pos} step={0.05} onCommit={(v) => write({ ...tr, pos: v })} />
      {actor ? (
        <Field label="رو به (درجه، دورِ محورِ عمودی)">
          <DraftNumber value={round3(tr.rot[2])} step={5} onCommit={(v) => v != null && write({ ...tr, rot: [0, 0, v] })} />
        </Field>
      ) : (
        <Vec label="چرخش (درجه)" value={tr.rot} step={5} onCommit={(v) => write({ ...tr, rot: v })} hints={["دورِ X", "دورِ Y", "دورِ Z"]} />
      )}
      {!actor && !light && (
        <>
          <Field label="اندازه (ضریب)" hint={uniform ? "یکسان در هر سه جهت" : "نایکسان"}>
            <DraftNumber value={round3(tr.scale[0])} step={0.1} min={0.01} onCommit={(v) => v != null && v > 0 && write({ ...tr, scale: [v, v, v] })} />
          </Field>
          {!uniform && <Vec label="اندازهٔ جدا" value={tr.scale} step={0.1} onCommit={(v) => write({ ...tr, scale: v })} hints={["X", "Y", "Z"]} />}
        </>
      )}
      <KeysList ed={ed} refObj={ref} />
    </Sec>
  );
}

function KeysList({ ed, refObj }: { ed: Ed; refObj: ObjRef }) {
  const { doc, cat, t, change, setSel, seek } = ed;
  const keys = keysOf(doc, refObj);
  const atKey = findKey(keys, t) >= 0;
  const cam = refObj.kind === "camera";
  return (
    <div className="u3e-keys">
      <div className="u3e-keys-h">
        <span>کلیدها ({fa(keys.length)})</span>
        <Button
          size="sm"
          variant="secondary"
          title="K"
          onClick={() => {
            const c = cam ? ed.capture() : undefined;
            if (cam && !c) return;
            change((d) => addKey(d, cat, refObj, t, c || undefined));
            setSel({ type: "key", ref: refObj, t: round3(t) });
          }}
        >
          {cam ? "◆ کلید از همین نما" : atKey ? "◆ به‌روز کردنِ کلید" : "◆ کلید در زمانِ فعلی"}
        </Button>
      </div>
      {keys.length === 0 && (
        <p className="u3e-hint">
          {cam
            ? "نما را با موش بچرخانید/نزدیک کنید، زمان را روی خطِ زمان بگذارید و «کلید از همین نما» بزنید. دوربین از کلیدی به کلیدِ بعد می‌رود."
            : "بی‌کلید = همین جا در کلِ ویدئو. برای حرکت: در یک زمان کلید بزنید، زمان را جلو ببرید، شیء را جابه‌جا کنید (کلید خودکار ساخته می‌شود)."}
        </p>
      )}
      {keys.map((k) => (
        <div key={k.t} className={`u3e-krow ${ed.sel?.type === "key" && Math.abs(ed.sel.t - k.t) < 1e-3 && ed.sel.ref.id === refObj.id ? "sel" : ""}`}>
          <button type="button" className="tm u3d-mono" onClick={() => { seek(k.t); setSel({ type: "key", ref: refObj, t: k.t }); }}>
            ◆ {fa(k.t.toFixed(2))}ث
          </button>
          <span className="ez">{EASES.find((e) => e.id === (k.ease || "smooth"))?.fa}</span>
          <button type="button" className="x" title="حذفِ کلید" onClick={() => change((d) => deleteKey(d, refObj, k.t))}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

// ───────────────────────── کلید

function KeyPanel({ ed, refObj, t0 }: { ed: Ed; refObj: ObjRef; t0: number }) {
  const { doc, cat, change, setSel, seek } = ed;
  const keys = keysOf(doc, refObj);
  const i = findKey(keys, t0);
  const k: KeyFrame | undefined = keys[i];
  if (!k) return <p className="u3e-hint">کلید پیدا نشد.</p>;
  const upd = (fn: (k: KeyFrame) => void) =>
    change((d) => {
      const kk = keysOf(d, refObj)[findKey(keysOf(d, refObj), t0)];
      if (kk) fn(kk);
    });
  const cam = refObj.kind === "camera";
  return (
    <>
      <Sec title={`کلیدِ ${objLabel(doc, cat, refObj)}`} extra={<span className="u3e-pill">{KIND_FA[refObj.kind]}</span>}>
        <Field label="زمان (ثانیه)">
          <DraftNumber
            value={k.t}
            step={0.05}
            min={0}
            onCommit={(v) => {
              if (v == null) return;
              let nt = v;
              change((d) => void (nt = moveKey(d, refObj, t0, v)));
              setSel({ type: "key", ref: refObj, t: nt });
              seek(nt);
            }}
          />
        </Field>
        <Field label="گذار تا کلیدِ بعد">
          <Select value={k.ease || "smooth"} onChange={(e) => upd((kk) => void (kk.ease = e.target.value as Ease))}>
            {EASES.map((e) => (
              <option key={e.id} value={e.id}>
                {e.fa}
              </option>
            ))}
          </Select>
        </Field>
        {k.pos && <Vec label="جا" value={k.pos} step={0.05} onCommit={(v) => upd((kk) => void (kk.pos = v))} />}
        {k.target && <Vec label="نقطهٔ نگاه" value={k.target} step={0.05} onCommit={(v) => upd((kk) => void (kk.target = v))} />}
        {k.lens != null && (
          <Field label="لنز (میلی‌متر)" hint="کوچک = زاویهٔ باز، بزرگ = نزدیک">
            <DraftNumber value={k.lens} step={1} min={8} max={300} onCommit={(v) => v != null && upd((kk) => void (kk.lens = v))} />
          </Field>
        )}
        {k.rot && !cam && <Vec label="چرخش" value={k.rot} step={5} onCommit={(v) => upd((kk) => void (kk.rot = v))} hints={["دورِ X", "دورِ Y", "دورِ Z"]} />}
        {k.scale && refObj.kind !== "actor" && refObj.kind !== "light" && (
          <Vec label="اندازه" value={k.scale} step={0.1} onCommit={(v) => upd((kk) => void (kk.scale = v))} hints={["X", "Y", "Z"]} />
        )}
        <div className="u3e-row">
          {cam && k.pos && k.target && (
            <Button size="sm" variant="secondary" onClick={() => { ed.setCameraView(false); ed.goTo(k.pos as Vec3, k.target as Vec3); seek(k.t); }}>
              نما را به این کلید ببر
            </Button>
          )}
          {cam && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                const c = ed.capture();
                if (c) upd((kk) => Object.assign(kk, { pos: c.pos, target: c.target, lens: c.lens }));
              }}
            >
              به‌روز از همین نما
            </Button>
          )}
          <Button size="sm" variant="danger" onClick={() => { change((d) => deleteKey(d, refObj, t0)); setSel({ type: "obj", ref: refObj }); }}>
            حذفِ کلید
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSel({ type: "obj", ref: refObj })}>
            ← خودِ {KIND_FA[refObj.kind]}
          </Button>
        </div>
      </Sec>
    </>
  );
}

// ───────────────────────── اشیا

function EnvPanel({ ed }: { ed: Ed }) {
  const { cat, doc, change } = ed;
  const env = byId(cat, "environment", doc.environment.id);
  const light = byId(cat, "lighting", doc.lighting.id);
  return (
    <>
      <Sec title="محیط">
        <Select
          value={doc.environment.id}
          onChange={(e) =>
            change((d) => {
              d.environment = { id: e.target.value, params: {} };
              const en = byId(cat, "environment", e.target.value);
              if (en?.default_lighting) d.lighting = { id: en.default_lighting, params: {} };
            })
          }
        >
          {cat.environment.map((x) => (
            <option key={x.id} value={x.id}>
              {label(x)}
            </option>
          ))}
        </Select>
        <PreviewLine kind="environment" id={doc.environment.id} />
        <ParamInputs spec={env?.params} values={doc.environment.params || {}} onChange={(k, v) => change((d) => void (d.environment.params = { ...(d.environment.params || {}), [k]: v }))} />
      </Sec>
      <Sec title="نورپردازیِ کلی">
        <Select value={doc.lighting.id} onChange={(e) => change((d) => void (d.lighting = { id: e.target.value, params: {} }))}>
          {cat.lighting.map((x) => (
            <option key={x.id} value={x.id}>
              {label(x)}
            </option>
          ))}
        </Select>
        <ParamInputs spec={light?.params} values={doc.lighting.params || {}} onChange={(k, v) => change((d) => void (d.lighting.params = { ...(d.lighting.params || {}), [k]: typeof v === "string" && !Number.isNaN(Number(v)) && v !== "" ? Number(v) : v }))} />
        <p className="u3e-hint">نورهای اضافه (نقطه‌ای، نورافکن، سطحی، خورشید) را از کتابخانه ⇐ «نور» به صحنه بکشید.</p>
      </Sec>
      <Sec title="خروجی">
        <div className="u3e-row">
          <Field label="مدت (ث)">
            <DraftNumber value={doc.output.duration} step={0.5} min={3} max={60} onCommit={(v) => v != null && change((d) => void (d.output.duration = Math.max(3, Math.min(60, v))))} />
          </Field>
          <Field label="قاب">
            <Select value={doc.output.aspect} onChange={(e) => change((d) => void (d.output.aspect = e.target.value))}>
              <option value="9:16">۹:۱۶ عمودی</option>
              <option value="16:9">۱۶:۹ افقی</option>
              <option value="1:1">۱:۱ مربع</option>
              <option value="4:5">۴:۵ پست</option>
            </Select>
          </Field>
          <Field label="fps">
            <Select value={String(doc.output.fps)} onChange={(e) => change((d) => void (d.output.fps = Number(e.target.value)))}>
              <option value="24">24</option>
              <option value="25">25</option>
              <option value="30">30</option>
            </Select>
          </Field>
        </div>
      </Sec>
    </>
  );
}

function ActorPanel({ ed, a }: { ed: Ed; a: Actor }) {
  const { cat, doc, change } = ed;
  const ref: ObjRef = { kind: "actor", id: a.id };
  const ch = byId(cat, "character", a.character);
  const env = byId(cat, "environment", doc.environment.id);
  const mine = doc.actions.filter((x) => x.actor === a.id);
  const upd = (fn: (x: Actor) => void) => change((d) => { const x = d.actors.find((y) => y.id === a.id); if (x) fn(x); });
  return (
    <>
      <Sec title="آدم" extra={<span className="u3e-pill u3d-mono">{a.id}</span>}>
        <Field label="نام (فقط برای خودتان)">
          <DraftInput value={a.name || ""} onCommit={(v) => upd((x) => void (x.name = v))} />
        </Field>
        <Field label="کاراکتر">
          <Select value={a.character} onChange={(e) => upd((x) => { x.character = e.target.value; x.params = {}; })}>
            {cat.character.map((x) => (
              <option key={x.id} value={x.id}>
                {label(x)}
              </option>
            ))}
          </Select>
        </Field>
        <PreviewLine kind="character" id={a.character} />
        <ParamInputs spec={ch?.params} values={a.params || {}} onChange={(k, v) => upd((x) => void (x.params = { ...(x.params || {}), [k]: v }))} />
      </Sec>
      <TransformSec ed={ed} objRef={ref} />
      {(a.transform || a.keys) && (
        <Sec title="جایگاهِ آماده">
          <div className="u3e-row">
            <Select value={a.mark} onChange={(e) => upd((x) => { x.mark = e.target.value; delete x.transform; delete x.keys; })}>
              {Object.keys(env?.marks || {}).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
            <Button size="sm" variant="ghost" onClick={() => upd((x) => { delete x.transform; delete x.keys; })}>
              برگشت به جایگاهِ «{a.mark}»
            </Button>
          </div>
        </Sec>
      )}
      <Sec title={`حرکت‌ها (${fa(mine.length)})`}>
        {mine.length === 0 && <p className="u3e-hint">از کتابخانه ⇐ «حرکت‌ها» یک حرکت را روی ردیفِ این آدم در خطِ زمان بکشید.</p>}
        {mine.map((x) => (
          <button key={x.id} type="button" className="u3e-link" onClick={() => { ed.setSel({ type: "action", id: x.id || "" }); ed.seek(x.start); }}>
            ▶ {label(byId(cat, "motion", x.motion))} · {fa(x.start.toFixed(1))}ث
          </button>
        ))}
      </Sec>
    </>
  );
}

function ProductPanel({ ed, p, prop }: { ed: Ed; p: ProductRef | PropRef; prop: boolean }) {
  const { cat, doc, change } = ed;
  const ref: ObjRef = { kind: prop ? "prop" : "product", id: p.id };
  const pa = byId(cat, "product", p.asset);
  const env = byId(cat, "environment", doc.environment.id);
  const upd = (fn: (x: ProductRef | PropRef) => void) =>
    change((d) => {
      const list: (ProductRef | PropRef)[] = prop ? d.props || [] : d.products;
      const x = list.find((y) => y.id === p.id);
      if (x) fn(x);
    });
  return (
    <>
      <Sec title={prop ? "شیءِ صحنه" : "محصول"} extra={<span className="u3e-pill u3d-mono">{p.id}</span>}>
        <Field label={prop ? "نام (اختیاری)" : "نامِ محصول (روی برچسب)"}>
          <DraftInput value={p.name || ""} onCommit={(v) => upd((x) => void (x.name = v))} />
        </Field>
        <Field label="شکل">
          <Select value={p.asset} onChange={(e) => upd((x) => void (x.asset = e.target.value))}>
            {cat.product.map((x) => (
              <option key={x.id} value={x.id}>
                {label(x)}
              </option>
            ))}
          </Select>
        </Field>
        <PreviewLine kind="product" id={p.asset} />
      </Sec>
      <TransformSec ed={ed} objRef={ref} />
      {!prop && (
        <Sec title="روی سطحِ آماده">
          <Select
            value=""
            onChange={(e) => {
              const sf = (env?.surfaces?.[e.target.value] || {}) as { pos?: number[]; yaw?: number };
              if (!sf.pos) return;
              const cur = transformOf(doc, cat, ref, ed.t);
              change((d) => {
                const x = d.products.find((y) => y.id === p.id);
                if (x) x.surface = e.target.value;
                writeTransform(d, cat, ref, { ...cur, pos: [sf.pos![0], sf.pos![1], sf.pos![2]], rot: [0, 0, Number(sf.yaw) || 0] }, ed.t);
              });
            }}
          >
            <option value="">بگذار روی…</option>
            {Object.keys(env?.surfaces || {}).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </Sec>
      )}
      <Sec title="ظاهر (رنگ، برچسب، جنس)">
        <ParamInputs
          spec={pa?.params}
          values={p.params || {}}
          onChange={(k, v) => upd((x) => void (x.params = { ...(x.params || {}), [k]: v }))}
          onFile={(k, f) =>
            void ed.upload(f).then((r) => {
              if (r) upd((x) => void (x.params = { ...(x.params || {}), [k]: r.path }));
            })
          }
        />
        <p className="u3e-hint">رنگ‌ها و برچسب در رندر اعمال می‌شوند؛ پیش‌نمایشِ نما شکلِ پیش‌فرض را نشان می‌دهد.</p>
      </Sec>
    </>
  );
}

function LightPanel({ ed, l }: { ed: Ed; l: LightRef }) {
  const { change } = ed;
  const ref: ObjRef = { kind: "light", id: l.id };
  const upd = (fn: (x: LightRef) => void) => change((d) => { const x = (d.lights || []).find((y) => y.id === l.id); if (x) fn(x); });
  return (
    <>
      <Sec title="نور" extra={<span className="u3e-pill u3d-mono">{l.id}</span>}>
        <div className="u3e-row">
          <Field label="نوع">
            <Select value={l.type} onChange={(e) => upd((x) => void (x.type = e.target.value as LightType))}>
              {(Object.keys(LIGHT_FA) as LightType[]).map((k) => (
                <option key={k} value={k}>
                  {LIGHT_FA[k]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="رنگ">
            <input type="color" className="u-input" style={{ width: 64, height: 38, padding: 2 }} value={l.color} onChange={(e) => upd((x) => void (x.color = e.target.value))} />
          </Field>
        </div>
        <Field label={l.type === "sun" ? "قدرت (۱ تا ۱۰)" : "توان (وات)"}>
          <DraftNumber value={l.power} step={l.type === "sun" ? 0.5 : 25} min={0} onCommit={(v) => v != null && upd((x) => void (x.power = v))} />
        </Field>
        {l.type !== "point" && (
          <Field label={l.type === "area" ? "اندازهٔ سطح (متر)" : l.type === "sun" ? "نرمیِ سایه" : "نرمیِ لبه"}>
            <DraftNumber value={l.size ?? 0.5} step={0.1} min={0.01} onCommit={(v) => v != null && upd((x) => void (x.size = v))} />
          </Field>
        )}
        {l.type === "spot" && (
          <div className="u3e-row">
            <Field label="زاویهٔ مخروط (درجه)">
              <DraftNumber value={l.cone ?? 45} step={5} min={1} max={175} onCommit={(v) => v != null && upd((x) => void (x.cone = v))} />
            </Field>
            <Field label="نرمیِ لبه (۰–۱)">
              <DraftNumber value={l.blend ?? 0.3} step={0.1} min={0} max={1} onCommit={(v) => v != null && upd((x) => void (x.blend = v))} />
            </Field>
          </div>
        )}
        <p className="u3e-hint">جهتِ تابش = خطِ زردِ نقطه‌چین. با چرخش (E) جهت را عوض کنید. نورِ نما تقریبی است؛ نورِ واقعی در «پیش‌نمایش» به بالا.</p>
      </Sec>
      <TransformSec ed={ed} objRef={ref} />
    </>
  );
}

function CameraPanel({ ed, id }: { ed: Ed; id: string }) {
  const { doc, change } = ed;
  const c = (doc.cameras || []).find((x) => x.id === id);
  if (!c) return null;
  const ref: ObjRef = { kind: "camera", id };
  const shots = doc.shots.filter((s) => s.camera === id);
  const upd = (fn: (x: NonNullable<SceneDoc["cameras"]>[number]) => void) => change((d) => { const x = (d.cameras || []).find((y) => y.id === id); if (x) fn(x); });
  return (
    <>
      <Sec title="دوربینِ آزاد" extra={<span className="u3e-pill u3d-mono">{id}</span>}>
        <Field label="نام">
          <DraftInput value={c.name || ""} onCommit={(v) => upd((x) => void (x.name = v))} />
        </Field>
        <div className="u3e-row">
          <Field label="لنزِ پیش‌فرض (mm)">
            <DraftNumber value={c.lens} step={1} min={8} max={300} onCommit={(v) => v != null && upd((x) => void (x.lens = v))} />
          </Field>
          <Field label="دیافراگم (f)" hint="کوچک = پس‌زمینهٔ تارتر">
            <DraftNumber value={c.fstop ?? 4} step={0.5} min={0.7} max={32} onCommit={(v) => v != null && upd((x) => void (x.fstop = v))} />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={ed.cameraView} onChange={(e) => ed.setCameraView(e.target.checked)} />
          نگاه از دوربینِ ویدئو (C)
        </label>
        <p className="u3e-hint">
          {shots.length
            ? `این دوربین در ${fa(shots.length)} شات استفاده می‌شود.`
            : "هنوز در هیچ شاتی نیست: با اولین کلید، شاتِ همان زمان دوربینِ آزاد می‌شود (یا در ردیفِ «نماها» قطعه‌ای را «آزاد» کنید)."}
          {" "}نقطهٔ صورتی = جایی که دوربین نگاه می‌کند (جابه‌جا کردنی).
        </p>
      </Sec>
      <Sec title="کلیدهای دوربین">
        <KeysList ed={ed} refObj={ref} />
      </Sec>
    </>
  );
}

// ───────────────────────── قطعه‌های خطِ زمان

function ActionPanel({ ed, id }: { ed: Ed; id: string }) {
  const { cat, doc, change } = ed;
  const it = doc.actions.find((x) => x.id === id);
  if (!it) return <p className="u3e-hint">قطعه پیدا نشد.</p>;
  const m = byId(cat, "motion", it.motion);
  const clip = m?.source?.type === "clip";
  const upd = (fn: (x: Item) => void) => change((d) => { const x = d.actions.find((y) => y.id === id); if (x) fn(x); });
  const productSpec = Object.fromEntries(
    Object.entries(m?.params || {}).map(([k, s]) =>
      s.type === "product_ref" ? [k, { ...s, type: "enum", values: doc.products.map((p) => p.id) }] : [k, s],
    ),
  );
  return (
    <Sec title="قطعهٔ حرکت" extra={<span className="u3e-pill">{clip ? "mocap (BVH/FBX)" : "رویه‌ای"}</span>}>
      <Field label="حرکت">
        <Select value={it.motion} onChange={(e) => upd((x) => { x.motion = e.target.value; const mm = byId(cat, "motion", e.target.value); if (mm) x.duration = mm.duration.default; })}>
          {cat.motion.map((x) => (
            <option key={x.id} value={x.id}>
              {label(x)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="آدم">
        <Select value={it.actor || ""} onChange={(e) => upd((x) => void (x.actor = e.target.value))}>
          {doc.actors.map((a) => (
            <option key={a.id} value={a.id}>
              {objLabel(doc, cat, { kind: "actor", id: a.id })}
            </option>
          ))}
        </Select>
      </Field>
      <div className="u3e-row">
        <Field label="شروع (ث)">
          <DraftNumber value={it.start} step={0.1} min={0} onCommit={(v) => v != null && upd((x) => void (x.start = Math.max(0, v)))} />
        </Field>
        <Field label="مدت (ث)" hint={m ? `${fa(m.duration.min)} تا ${fa(m.duration.max)}` : undefined}>
          <DraftNumber value={it.duration ?? 1} step={0.1} min={0.2} onCommit={(v) => v != null && upd((x) => void (x.duration = Math.max(0.2, v)))} />
        </Field>
      </div>
      {clip && (
        <Field label="نرمیِ ورود/خروج (ثانیه)" hint="آمیختنِ کلیپ با حالتِ قبل و بعد">
          <DraftNumber
            value={typeof it.params?.blend === "number" ? (it.params.blend as number) : null}
            placeholder="خودکار"
            step={0.05}
            min={0}
            max={3}
            onCommit={(v) => upd((x) => { x.params = { ...(x.params || {}) }; if (v == null) delete x.params.blend; else x.params.blend = v; })}
          />
        </Field>
      )}
      <ParamInputs spec={productSpec} values={it.params || {}} onChange={(k, v) => upd((x) => void (x.params = { ...(x.params || {}), [k]: v }))} />
      <div className="u3e-row">
        <Button size="sm" variant="danger" onClick={() => { change((d) => void (d.actions = d.actions.filter((x) => x.id !== id))); ed.setSel(null); }}>
          حذفِ قطعه
        </Button>
      </div>
      {!clip && <p className="u3e-hint">حرکت‌های رویه‌ای در مرورگر فقط با برچسب نشان داده می‌شوند؛ حرکتِ واقعی را «انیمیک» نشان می‌دهد.</p>}
    </Sec>
  );
}

function ShotPanel({ ed, id }: { ed: Ed; id: string }) {
  const { cat, doc, change } = ed;
  const it = doc.shots.find((x) => x.id === id);
  if (!it) return <p className="u3e-hint">شات پیدا نشد.</p>;
  const upd = (fn: (x: Item) => void) => change((d) => { const x = d.shots.find((y) => y.id === id); if (x) fn(x); });
  const sa = byId(cat, "shot", it.shot);
  const cams = doc.cameras || [];
  const subjects = sa?.subject === "product" ? doc.products.map((p) => p.id) : sa?.subject === "actor" ? doc.actors.map((a) => a.id) : [...doc.actors.map((a) => a.id), ...doc.products.map((p) => p.id)];
  return (
    <Sec title="شاتِ دوربین">
      <Field label="نوع">
        <Select
          value={it.camera ? "free" : "preset"}
          onChange={(e) =>
            upd((x) => {
              if (e.target.value === "free") {
                x.camera = cams[0]?.id || "cam1";
              } else {
                delete x.camera;
                x.shot = x.shot || "medium";
                x.subject = x.subject || doc.actors[0]?.id || doc.products[0]?.id;
                x.move = x.move || "static";
              }
            })
          }
        >
          <option value="preset">نمای آماده (قاب‌بندیِ خودکار روی سوژه)</option>
          <option value="free">دوربینِ آزاد (کلیدهای خودتان)</option>
        </Select>
      </Field>
      {it.camera ? (
        <Field label="دوربین">
          <Select value={it.camera} onChange={(e) => upd((x) => void (x.camera = e.target.value))}>
            {cams.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name || c.id} ({fa(c.keys.length)} کلید)
              </option>
            ))}
          </Select>
        </Field>
      ) : (
        <>
          <Field label="نما">
            <Select value={it.shot} onChange={(e) => upd((x) => void (x.shot = e.target.value))}>
              {cat.shot.map((x) => (
                <option key={x.id} value={x.id}>
                  {label(x)}
                </option>
              ))}
            </Select>
          </Field>
          <div className="u3e-row">
            <Field label="سوژه">
              <Select value={it.subject || ""} onChange={(e) => upd((x) => void (x.subject = e.target.value))}>
                {subjects.map((s) => (
                  <option key={s} value={s}>
                    {objLabel(doc, cat, { kind: doc.actors.some((a) => a.id === s) ? "actor" : "product", id: s })}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="حرکتِ دوربین">
              <Select value={it.move || "static"} onChange={(e) => upd((x) => void (x.move = e.target.value))}>
                {(sa?.moves || ["static"]).map((mv) => (
                  <option key={mv} value={mv}>
                    {MOVES_FA[mv] || mv}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        </>
      )}
      <div className="u3e-row">
        <Field label="شروع (ث)">
          <DraftNumber value={it.start} step={0.1} min={0} onCommit={(v) => v != null && upd((x) => void (x.start = Math.max(0, v)))} />
        </Field>
        <Field label="مدت (ث)">
          <DraftNumber value={it.duration ?? 1} step={0.1} min={0.3} onCommit={(v) => v != null && upd((x) => void (x.duration = Math.max(0.3, v)))} />
        </Field>
      </div>
      <div className="u3e-row">
        <Button size="sm" variant="secondary" onClick={() => { ed.seek(it.start + 0.01); ed.setCameraView(true); }}>
          نگاه از این شات
        </Button>
        <Button size="sm" variant="danger" onClick={() => { change((d) => void (d.shots = d.shots.filter((x) => x.id !== id))); ed.setSel(null); }}>
          حذفِ شات
        </Button>
      </div>
    </Sec>
  );
}

export default function SceneInspector({ ed }: { ed: Ed }) {
  const { doc, sel } = ed;
  if (!sel) {
    return (
      <div className="u3e-insp-empty">
        <b>چیزی انتخاب نشده</b>
        <p>روی یک شیء در نما یا فهرستِ صحنه بزنید، یا یک قطعه/کلید در خطِ زمان.</p>
        <EnvPanel ed={ed} />
      </div>
    );
  }
  if (sel.type === "key") return <KeyPanel ed={ed} refObj={sel.ref} t0={sel.t} />;
  if (sel.type === "action") return <ActionPanel ed={ed} id={sel.id} />;
  if (sel.type === "shot") return <ShotPanel ed={ed} id={sel.id} />;
  if (sel.type === "target") return <CameraPanel ed={ed} id={sel.id} />;
  const r = sel.ref;
  const rec = record(doc, r);
  switch (r.kind) {
    case "environment":
      return <EnvPanel ed={ed} />;
    case "actor":
      return rec ? <ActorPanel ed={ed} a={rec as Actor} /> : null;
    case "product":
      return rec ? <ProductPanel ed={ed} p={rec as ProductRef} prop={false} /> : null;
    case "prop":
      return rec ? <ProductPanel ed={ed} p={rec as PropRef} prop /> : null;
    case "light":
      return rec ? <LightPanel ed={ed} l={rec as LightRef} /> : null;
    case "camera":
      return <CameraPanel ed={ed} id={r.id} />;
    default:
      return null;
  }
}

