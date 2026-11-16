import { useState } from "react";
import { useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, Field, Input, Select, TextArea, fa } from "../../../components/ui";
import { COMPONENT_THUMB, Comp, Library, Scene, Source } from "./api";
import FieldsForm from "./FieldsForm";
import { bcApi } from "../../brandchar/api";

const SWATCHES = ["#e63946", "#f77f00", "#ffbe0b", "#2a9d5c", "#126f85", "#1d6fd1", "#7b2cbf", "#ef476f"];
const SCENE_KEYS_PLAIN = new Set(["type", "duration", "enter", "exit", "ease", "spring", "emphasis", "camera", "transition", "tokens", "overlays", "narration", "cues", "sfx"]);

type Props = {
  scenes: Scene[];
  onChange: (s: Scene[]) => void;
  lib: Library;
  sources: Source[];
  onUpload?: (f: File) => void;
  maxScenes: number;
  brandColors: string[];
  findings?: Record<number, { severity: "error" | "warn" | "info"; message: string }[]>;
};

function Thumb({ cid, label, size = 56 }: { cid: string; label: string; size?: number }) {
  const [bad, setBad] = useState(false);
  if (bad)
    return (
      <span className="flex items-center justify-center rounded-md text-[10px]" style={{ width: size, height: size * 1.4, background: "var(--surface-2)", color: "var(--text-3)" }}>
        {label.slice(0, 6)}
      </span>
    );
  return <img src={COMPONENT_THUMB(cid)} alt={label} loading="lazy" onError={() => setBad(true)} className="rounded-md object-cover" style={{ width: size, height: size * 1.4, border: "1px solid var(--line)" }} />;
}

export function ComponentPicker({ lib, onPick, overlayOnly = false, disabled }: { lib: Library; onPick: (c: Comp) => void; overlayOnly?: boolean; disabled?: boolean }) {
  const groups = Object.entries(lib.groups);
  return (
    <div className="space-y-4">
      {groups.map(([g, gl]) => {
        const items = lib.components.filter((c) => c.group === g && (!overlayOnly || c.overlay));
        if (!items.length) return null;
        return (
          <div key={g}>
            <div className="mb-2 text-sm font-bold" style={{ color: "var(--text-2)" }}>
              {gl}
            </div>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
              {items.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  disabled={disabled}
                  onClick={() => onPick(c)}
                  title={c.about}
                  className="flex flex-col items-center gap-1 rounded-xl p-2 text-center text-xs transition"
                  style={{ border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text-2)" }}
                >
                  <Thumb cid={c.id} label={c.label} />
                  <span className="leading-4">{c.label}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Pills({ value, options, onChange, empty = "پیش‌فرضِ سبک" }: { value?: string; options: { id: string; name: string }[]; onChange: (v?: string) => void; empty?: string }) {
  return (
    <Select value={value ?? ""} onChange={(e) => onChange(e.target.value || undefined)}>
      <option value="">{empty}</option>
      {options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.name}
        </option>
      ))}
    </Select>
  );
}

function Overlays({ sc, onChange, lib, sources, onUpload }: { sc: Scene; onChange: (s: Scene) => void; lib: Library; sources: Source[]; onUpload?: (f: File) => void }) {
  const list = (Array.isArray(sc.overlays) ? sc.overlays : []) as Record<string, unknown>[];
  const [adding, setAdding] = useState(false);
  const set = (next: Record<string, unknown>[]) => onChange({ ...sc, overlays: next.length ? next : undefined } as Scene);
  return (
    <div className="space-y-2">
      {list.map((ov, k) => {
        const comp = lib.components.find((c) => c.id === ov.type);
        return (
          <div key={k} className="rounded-lg p-3" style={{ background: "var(--surface-2)" }}>
            <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
              <Badge tone="brand">{comp?.label || String(ov.type)}</Badge>
              <label className="flex items-center gap-1">
                از ثانیهٔ
                <input type="number" className="u-input" style={{ width: 64 }} min={0} step={0.5} value={Number(ov.at ?? 0)} onChange={(e) => set(list.map((o, j) => (j === k ? { ...o, at: Number(e.target.value) } : o)))} />
              </label>
              <label className="flex items-center gap-1">
                جا
                <Select value={String(ov.anchor ?? "")} onChange={(e) => set(list.map((o, j) => (j === k ? { ...o, anchor: e.target.value || undefined } : o)))}>
                  <option value="">پیش‌فرض</option>
                  {lib.anchors.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </Select>
              </label>
              <span className="flex-1" />
              <Button variant="ghost" size="sm" type="button" onClick={() => set(list.filter((_, j) => j !== k))}>
                <Icon name="trash" size={14} />
              </Button>
            </div>
            {comp ? (
              <FieldsForm
                fields={comp.fields}
                value={Object.fromEntries(Object.entries(ov).filter(([key]) => key in comp.fields))}
                onChange={(v) => set(list.map((o, j) => (j === k ? { type: o.type, at: o.at, dur: o.dur, anchor: o.anchor, dx: o.dx, dy: o.dy, ...v } : o)))}
                lib={lib}
                sources={sources}
                onUpload={onUpload}
              />
            ) : null}
          </div>
        );
      })}
      {adding ? (
        <Card>
          <ComponentPicker
            lib={lib}
            overlayOnly
            onPick={(c) => {
              const { type: _t, duration: _d, ...rest } = c.sample;
              void _t;
              void _d;
              set([...list, { type: c.id, at: 0.5, ...rest }]);
              setAdding(false);
            }}
          />
        </Card>
      ) : (
        <Button variant="secondary" size="sm" type="button" disabled={list.length >= 4} onClick={() => setAdding(true)}>
          <Icon name="plus" size={14} /> افزودنِ رویه (نوارِ نام، استیکر، زیرنویس، تیکر، …)
        </Button>
      )}
    </div>
  );
}

function Motion({ sc, onChange, lib }: { sc: Scene; onChange: (s: Scene) => void; lib: Library }) {
  const set = (k: string, v: unknown) => {
    const next = { ...sc } as Record<string, unknown>;
    if (v === undefined || v === "") delete next[k];
    else next[k] = v;
    onChange(next as Scene);
  };
  const cam = (sc.camera ?? {}) as { move?: string; amount?: number };
  const emph = Array.isArray(sc.emphasis) ? (sc.emphasis as string[]) : [];
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <Field label="حرکتِ ورود">
        <Select value={String(sc.enter ?? "")} onChange={(e) => set("enter", e.target.value)}>
          <option value="">پیش‌فرضِ سبک</option>
          {lib.enters.map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="خروج">
        <Pills value={sc.exit as string | undefined} options={lib.exits} onChange={(v) => set("exit", v)} empty="پیش‌فرض" />
      </Field>
      <Field label="منحنیِ شتاب (Easing)">
        <Pills value={sc.ease as string | undefined} options={lib.eases} onChange={(v) => set("ease", v)} />
      </Field>
      <Field label="فنر (Spring)">
        <Pills value={sc.spring as string | undefined} options={lib.springs} onChange={(v) => set("spring", v)} />
      </Field>
      <Field label="حرکتِ دوربین">
        <Select value={cam.move ?? ""} onChange={(e) => set("camera", e.target.value ? { move: e.target.value, amount: cam.amount ?? 0.5 } : undefined)}>
          <option value="">ثابت</option>
          {lib.camera_moves
            .filter((m) => m.id !== "none")
            .map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
        </Select>
      </Field>
      <Field label="گذار به صحنهٔ بعد" hint="بستهٔ گذارها: wipe، push، zoom، ink، glitch، iris">
        <Select value={String(sc.transition ?? "")} onChange={(e) => set("transition", e.target.value)}>
          <option value="">پیش‌فرضِ سبک</option>
          <optgroup label="بسته‌ی گذارها">
            {lib.transition_pack.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </optgroup>
          <optgroup label="بقیه">
            {lib.transitions
              .filter((x) => !lib.transition_pack.includes(x))
              .map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
          </optgroup>
        </Select>
      </Field>
      {cam.move ? (
        <Field label={`شدتِ دوربین (${fa(((cam.amount ?? 0.5) * 100).toFixed(0))}٪)`}>
          <input type="range" min={0} max={1} step={0.05} value={cam.amount ?? 0.5} onChange={(e) => set("camera", { move: cam.move, amount: Number(e.target.value) })} className="w-full" />
        </Field>
      ) : null}
      <div className="sm:col-span-2">
        <Field label="کلمه‌های برجسته (با کاما جدا کنید)" hint="با رنگِ تأکید و پاپ نمایش داده می‌شوند">
          <Input value={emph.join("، ")} onChange={(e) => set("emphasis", e.target.value.split(/[,،]/).map((x) => x.trim()).filter(Boolean).slice(0, 8))} />
        </Field>
      </div>
    </div>
  );
}

function SceneCard({ sc, i, n, props, onChange, onMove, onDup, onDel }: { sc: Scene; i: number; n: number; props: Props; onChange: (s: Scene) => void; onMove: (d: number) => void; onDup: () => void; onDel: () => void }) {
  const { lib, sources, onUpload } = props;
  const comp = lib.components.find((c) => c.id === sc.type);
  const [more, setMore] = useState(false);
  const tokens = (sc.tokens ?? {}) as { accent?: string; font_scale?: number; calm?: boolean };
  const fs = tokens.font_scale ?? 1;
  const setTok = (k: string, v: unknown) => {
    const t = { ...tokens, [k]: v } as Record<string, unknown>;
    if (v === undefined) delete t[k];
    onChange({ ...sc, tokens: Object.keys(t).length ? t : undefined } as Scene);
  };
  const dur = Number(sc.duration || 4);
  const fnd = props.findings?.[i] ?? [];
  const content = Object.fromEntries(Object.entries(sc).filter(([k]) => !SCENE_KEYS_PLAIN.has(k)));
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold" style={{ background: "var(--brand-soft, var(--surface-2))", color: "var(--brand)" }}>
          {fa(i + 1)}
        </span>
        <Thumb cid={sc.type} label={comp?.label || sc.type} size={28} />
        <div className="w-56">
          <Select
            value={sc.type}
            onChange={(e) => {
              const c = lib.components.find((x) => x.id === e.target.value);
              if (c) onChange({ ...c.sample, duration: sc.duration } as Scene);
            }}
          >
            {Object.entries(lib.groups).map(([g, gl]) => (
              <optgroup key={g} label={gl}>
                {lib.components
                  .filter((c) => c.group === g)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
                    </option>
                  ))}
              </optgroup>
            ))}
          </Select>
        </div>
        <span className="flex-1" />
        <Button variant="ghost" size="sm" type="button" onClick={() => onMove(-1)} disabled={i === 0} title="بالا">
          <Icon name="up" size={14} />
        </Button>
        <Button variant="ghost" size="sm" type="button" onClick={() => onMove(1)} disabled={i === n - 1} title="پایین">
          <Icon name="down" size={14} />
        </Button>
        <Button variant="ghost" size="sm" type="button" onClick={onDup} disabled={n >= props.maxScenes} title="کپی">
          <Icon name="copy" size={14} />
        </Button>
        <Button variant="ghost" size="sm" type="button" onClick={onDel} disabled={n < 2} title="حذف">
          <Icon name="trash" size={14} />
        </Button>
      </div>

      {/* کنترل‌های سریع */}
      <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg p-2 text-sm" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>
        <span className="flex items-center gap-1">
          اندازهٔ متن
          <Button variant="secondary" size="sm" type="button" onClick={() => setTok("font_scale", Math.max(0.6, Math.round((fs - 0.1) * 100) / 100))} title="کوچک‌تر">
            −
          </Button>
          <span className="w-10 text-center">{fa(fs.toFixed(1))}×</span>
          <Button variant="secondary" size="sm" type="button" onClick={() => setTok("font_scale", Math.min(1.6, Math.round((fs + 0.1) * 100) / 100))} title="بزرگ‌تر">
            +
          </Button>
        </span>
        <span className="flex items-center gap-1">
          مدت
          <input type="number" min={1} max={30} step={0.5} value={dur} onChange={(e) => onChange({ ...sc, duration: Number(e.target.value) })} className="u-input" style={{ width: 70 }} />
          ثانیه
        </span>
        <label className="flex items-center gap-1" title="لکه‌ها و خط‌های تزئینیِ پس‌زمینه برای این صحنه خاموش می‌شوند تا متن خواناتر باشد">
          <input type="checkbox" checked={!!tokens.calm} onChange={(e) => setTok("calm", e.target.checked ? true : undefined)} />
          پس‌زمینهٔ آرام
        </label>
        <span className="flex items-center gap-1">
          رنگِ تأکید
          {[...props.brandColors, ...SWATCHES].slice(0, 10).map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setTok("accent", c)}
              title={c}
              className="h-5 w-5 rounded-full"
              style={{ background: c, outline: tokens.accent?.toLowerCase() === c.toLowerCase() ? "2px solid var(--text)" : "1px solid var(--line)" }}
            />
          ))}
          {tokens.accent ? (
            <button type="button" className="text-xs underline" onClick={() => setTok("accent", undefined)}>
              پیش‌فرض
            </button>
          ) : null}
        </span>
      </div>

      {fnd.length ? (
        <div className="mb-3 space-y-1">
          {fnd.map((f, k) => (
            <div key={k} className="text-xs leading-6" style={{ color: f.severity === "error" ? "var(--bad)" : f.severity === "warn" ? "var(--warn)" : "var(--text-3)" }}>
              • {f.message}
            </div>
          ))}
        </div>
      ) : null}

      {comp ? <FieldsForm fields={comp.fields} value={content} onChange={(v) => onChange({ ...Object.fromEntries(Object.entries(sc).filter(([k]) => SCENE_KEYS_PLAIN.has(k))), ...v } as Scene)} lib={lib} sources={sources} onUpload={onUpload} /> : null}

      <div className="mt-3">
        <button type="button" className="text-sm font-semibold" style={{ color: "var(--brand)" }} onClick={() => setMore((v) => !v)}>
          {more ? "▾" : "◂"} حرکت، گفتار و رویه‌ها
        </button>
        {more ? (
          <div className="mt-3 space-y-4">
            <Motion sc={sc} onChange={onChange} lib={lib} />
            <Field label="گفتارِ این صحنه (اختیاری)" hint="همان کلماتِ روی صحنه را بگویید؛ متنِ کینتیک و زیرنویس با کلمه‌های گفتار هم‌زمان می‌شوند. خالی = اگر گوینده روشن باشد از متنِ صحنه ساخته می‌شود.">
              <TextArea rows={2} value={String(sc.narration ?? "")} onChange={(e) => onChange({ ...sc, narration: e.target.value || undefined } as Scene)} maxLength={700} />
            </Field>
            <div>
              <div className="mb-1 text-sm font-semibold" style={{ color: "var(--text-2)" }}>
                رویه‌ها (قطعه‌هایی که روی همین صحنه می‌نشینند)
              </div>
              <Overlays sc={sc} onChange={onChange} lib={lib} sources={sources} onUpload={onUpload} />
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

export default function ScenePlan(props: Props) {
  const { scenes, onChange, lib } = props;
  const { id: storeId = "" } = useParams<{ id: string }>();
  const [picking, setPicking] = useState(false);
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= scenes.length) return;
    const next = scenes.slice();
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  return (
    <div className="space-y-3">
      {scenes.map((sc, i) => (
        <SceneCard
          key={i}
          sc={sc}
          i={i}
          n={scenes.length}
          props={props}
          onChange={(s) => onChange(scenes.map((x, k) => (k === i ? s : x)))}
          onMove={(d) => move(i, d)}
          onDup={() => onChange([...scenes.slice(0, i + 1), { ...sc, cues: undefined }, ...scenes.slice(i + 1)])}
          onDel={() => onChange(scenes.filter((_, k) => k !== i))}
        />
      ))}
      {picking ? (
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <div className="font-bold" style={{ color: "var(--text)" }}>
              کدام قطعه؟ ({fa(lib.components.length)} قطعهٔ آماده)
            </div>
            <Button variant="ghost" size="sm" type="button" onClick={() => setPicking(false)}>
              <Icon name="x" size={14} />
            </Button>
          </div>
          <ComponentPicker
            lib={lib}
            onPick={(c) => {
              if (c.id === "brand_character" && storeId) {
                // «شخصیتِ برند»: تصویرِ ژست‌ها از شخصیتِ اصلیِ فروشگاه (اگر شخصیتی نباشد همان نمونه می‌آید)
                void bcApi
                  .useMotion(storeId, { action: "wave", text: "" })
                  .then((sc) => onChange([...scenes, sc as Scene]))
                  .catch(() => onChange([...scenes, { ...c.sample }]))
                  .finally(() => setPicking(false));
                return;
              }
              onChange([...scenes, { ...c.sample }]);
              setPicking(false);
            }}
          />
        </Card>
      ) : (
        <Button variant="secondary" type="button" disabled={scenes.length >= props.maxScenes} onClick={() => setPicking(true)}>
          <Icon name="plus" size={15} /> افزودنِ صحنه از کتابخانهٔ قطعه‌ها
        </Button>
      )}
    </div>
  );
}
