import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, Field, Input, Select, Spinner, TextArea, fa } from "../../../components/ui";
import { Catalog, ContrastReport, KindDef, ParamSpec, StyleCheck, StyleDef, StyleDoc, StyleSchema, Tok, customApi, errText } from "./api";
import PlayerFrame, { PlayerHandle } from "./PlayerFrame";

/**
 * «سبکِ تازه» — ویرایشگرِ سبک. هر قسمتِ یک سبک (پالت، قلم، پس‌زمینه، بافت، تزئین، کارت، حرکت، گذار) اینجا ویرایش می‌شود؛
 * پیش‌نمایشِ زنده با متنِ خودِ فروشگاه؛ ذخیره فقط بعد از «کنترلِ کیفیتِ» واقعی (رندرِ فریم‌ها + نگهبانِ کنتراست).
 * توکن‌ها در سرور اعتبارسنجی می‌شوند (backend/apps/motion/custom.py)؛ این‌جا فقط فرم و بازخوردِ زنده است.
 */

const TABS = [
  { key: "start", label: "شروع" },
  { key: "colors", label: "رنگ‌ها" },
  { key: "type", label: "قلم و حروف" },
  { key: "bg", label: "پس‌زمینه و بافت" },
  { key: "decor", label: "تزئین" },
  { key: "card", label: "کارت و دکمه" },
  { key: "motion", label: "حرکت و گذار" },
  { key: "json", label: "خروجی/ورودی" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

const GRADES: { id: string; label: string; css: string }[] = [
  { id: "", label: "بدونِ فیلتر", css: "" },
  { id: "contrast", label: "کنتراستِ بیشتر", css: "contrast(1.08) saturate(1.1)" },
  { id: "bw", label: "سیاه‌وسفید", css: "grayscale(1) contrast(1.15)" },
  { id: "warm", label: "گرم", css: "sepia(0.25) saturate(1.15)" },
  { id: "soft", label: "کم‌رنگ و نرم", css: "saturate(0.85) brightness(1.04)" },
];
const POS = ["50% 20%", "50% 35%", "50% 45%", "50% 60%", "30% 40%", "70% 40%"];
const ASPECT_CHOICES = [
  { id: "4:5", label: "پست ۴:۵" },
  { id: "9:16", label: "ریلز ۹:۱۶" },
  { id: "16:9", label: "افقی ۱۶:۹" },
];

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** هر شیءِ سبک (کاتالوگ، ذخیره‌شده یا وارد‌شده) ⇒ سندِ قابلِ‌ویرایش؛ هرچه نبود از «سبکِ از صفر» پر می‌شود */
export function toDoc(x: unknown, blank: StyleDoc): StyleDoc {
  const s = (x || {}) as Partial<StyleDoc> & Record<string, unknown>;
  const b = clone(blank);
  const m = (s.motion || {}) as Partial<StyleDoc["motion"]>;
  return {
    name_fa: String(s.name_fa || b.name_fa),
    name_en: String(s.name_en || ""),
    about: String(s.about || ""),
    tags: Array.isArray(s.tags) ? [...s.tags] : [],
    group: String(s.group || "custom"),
    palette: { ...b.palette, ...(s.palette || {}) },
    font: { ...b.font, ...(s.font || {}) } as StyleDoc["font"],
    bg: clone((s.bg as Tok) || b.bg),
    bg2: s.bg2 ? clone(s.bg2 as Tok) : null,
    tex: clone((s.tex as Tok[]) || []),
    decor: clone((s.decor as Tok[]) || []),
    text: clone((s.text as Tok) || b.text),
    shape: { ...b.shape, ...(s.shape || {}) },
    motion: {
      enter: m.enter || b.motion.enter,
      spring: (Array.isArray(m.spring) && m.spring.length === 3 ? [...m.spring] : [...b.motion.spring]) as [number, number, number],
      ease: m.ease || "out-expo",
      stagger: m.stagger ?? b.motion.stagger,
      stepFps: m.stepFps ?? null,
      wobble: m.wobble ?? 0,
      cam: m.cam ? clone(m.cam) : null,
    },
    trans: { ...(b.trans), ...(s.trans || {}) },
    fx: clone((s.fx as Record<string, unknown>) || {}),
  };
}

// ───────────────────────────────────────────── colours (the live part of the contrast guard; the server has the final word)

function hexRgb(h: string): [number, number, number] | null {
  const m = /^#?([0-9a-fA-F]{6})$/.exec((h || "").trim());
  if (!m) return null;
  return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16)];
}
function lum(c: [number, number, number]): number {
  const f = (v: number) => {
    const x = v / 255;
    return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
}
export function ratio(a: string, b: string): number {
  const ra = hexRgb(a), rb = hexRgb(b);
  if (!ra || !rb) return 0;
  const la = lum(ra), lb = lum(rb);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const isRole = (v: unknown, roles: string[]): v is string => typeof v === "string" && roles.includes(v);

function ColorPick({ value, onChange, schema, pal }: { value: unknown; onChange: (v: string) => void; schema: StyleSchema; pal: Record<string, string> }) {
  const role = isRole(value, schema.roles);
  const hex = typeof value === "string" && hexRgb(value) ? value : "";
  const raw = typeof value === "string" && !role && !hex ? value : "";
  const shown = role ? pal[value as string] : hex || "#888888";
  return (
    <div className="flex items-center gap-2">
      <span className="inline-block h-7 w-7 shrink-0 rounded-lg" style={{ background: raw ? "transparent" : shown, border: "1px solid var(--line)" }} aria-hidden />
      <Select
        value={role ? (value as string) : "__custom"}
        onChange={(e) => (e.target.value === "__custom" ? onChange(hex || "#888888") : onChange(e.target.value))}
        aria-label="رنگ"
      >
        {schema.roles.map((r) => (
          <option key={r} value={r}>
            {schema.role_labels[r] || r}
          </option>
        ))}
        <option value="__custom">{raw ? "رنگِ شفاف (rgba)" : "رنگِ دلخواه…"}</option>
      </Select>
      {!role && !raw ? <input type="color" value={hex || "#888888"} onChange={(e) => onChange(e.target.value)} className="h-9 w-12 shrink-0 cursor-pointer rounded-lg" aria-label="انتخابِ رنگِ دلخواه" /> : null}
    </div>
  );
}

function ParamRow({ name, spec, value, onChange, schema, pal }: { name: string; spec: ParamSpec; value: unknown; onChange: (v: unknown) => void; schema: StyleSchema; pal: Record<string, string> }) {
  const set = value !== undefined;
  const label = spec.label || name;
  let body: React.ReactNode = null;
  if (spec.t === "num") {
    const lo = spec.min ?? 0, hi = spec.max ?? 1;
    const step = spec.int ? 1 : hi - lo <= 2 ? 0.01 : hi - lo <= 20 ? 0.1 : 1;
    const cur = typeof value === "number" ? value : spec.default ?? (lo + hi) / 2;
    body = (
      <div className="flex items-center gap-2">
        <input type="range" min={lo} max={hi} step={step} value={cur} onChange={(e) => onChange(spec.int ? Math.round(Number(e.target.value)) : Number(e.target.value))} className="min-w-0 flex-1" aria-label={label} />
        <span className="w-14 text-center text-xs tabular-nums" style={{ color: set ? "var(--text)" : "var(--text-3)" }}>
          {fa(Number(cur.toFixed(2)))}
        </span>
      </div>
    );
  } else if (spec.t === "bool") {
    body = (
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {value ? "روشن" : "خاموش"}
      </label>
    );
  } else if (spec.t === "color" || spec.t === "fill") {
    body = (
      <div className="flex flex-wrap items-center gap-2">
        <ColorPick value={value ?? "ink"} onChange={onChange} schema={schema} pal={pal} />
        {spec.t === "fill" ? (
          <>
            <Button type="button" size="sm" variant="ghost" onClick={() => onChange("glass")}>شیشه‌ای</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => onChange("none")}>بدونِ پُرشدگی</Button>
          </>
        ) : null}
      </div>
    );
    if (spec.t === "fill" && (value === "glass" || value === "none")) {
      body = (
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="info">{value === "glass" ? "شیشه‌ای" : "بدونِ پُرشدگی"}</Badge>
          <Button type="button" size="sm" variant="ghost" onClick={() => onChange("paper")}>رنگِ کاغذ</Button>
        </div>
      );
    }
  } else if (spec.t === "colors") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    body = (
      <div className="flex flex-wrap items-center gap-1.5">
        {schema.roles.map((r) => {
          const on = arr.includes(r);
          return (
            <button
              key={r}
              type="button"
              className="rounded-full px-2.5 py-1 text-xs"
              style={{ background: on ? pal[r] : "var(--surface-2)", color: on ? (ratio(pal[r], "#ffffff") > ratio(pal[r], "#111111") ? "#fff" : "#111") : "var(--text-2)", border: "1px solid var(--line)" }}
              aria-pressed={on}
              onClick={() => onChange(on ? arr.filter((x) => x !== r) : [...arr, r].slice(0, spec.max ?? 8))}
            >
              {schema.role_labels[r] || r}
            </button>
          );
        })}
      </div>
    );
  } else if (spec.t === "enum") {
    body = (
      <Select value={typeof value === "string" ? value : spec.choices?.[0] ?? ""} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        {(spec.choices || []).map((c) => (
          <option key={c} value={c}>
            {c || "—"}
          </option>
        ))}
      </Select>
    );
  } else if (spec.t === "enumlist") {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    body = (
      <div className="flex flex-wrap gap-1.5">
        {(spec.choices || []).map((c) => (
          <button
            key={c}
            type="button"
            className={`u-btn u-btn-sm ${arr.includes(c) ? "u-btn-primary" : "u-btn-secondary"}`}
            aria-pressed={arr.includes(c)}
            onClick={() => onChange(arr.includes(c) ? arr.filter((x) => x !== c) : [...arr, c].slice(0, spec.max ?? 6))}
          >
            {c}
          </button>
        ))}
      </div>
    );
  } else if (spec.t === "pos") {
    body = (
      <Select value={typeof value === "string" ? value : POS[2]} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        {POS.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </Select>
    );
  } else if (spec.t === "rgb") {
    const v = Array.isArray(value) && value.length === 3 ? (value as number[]) : [255, 255, 255];
    const h = "#" + v.map((x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, "0")).join("");
    body = <input type="color" value={h} onChange={(e) => onChange(hexRgb(e.target.value) ?? [255, 255, 255])} className="h-9 w-14 cursor-pointer rounded-lg" aria-label={label} />;
  } else {
    body = <span className="text-xs" style={{ color: "var(--text-3)" }}>این پارامتر از سبکِ پایه می‌آید و با ویرایشگر عوض نمی‌شود.</span>;
  }
  return (
    <div className="grid items-center gap-2 sm:grid-cols-[130px_minmax(0,1fr)_auto]">
      <div className="text-sm" style={{ color: "var(--text-2)" }}>
        {label}
      </div>
      <div className="min-w-0">{body}</div>
      {set ? (
        <button type="button" className="text-xs underline" style={{ color: "var(--text-3)" }} onClick={() => onChange(undefined)} title="برگرداندن به پیش‌فرضِ موتور">
          پیش‌فرض
        </button>
      ) : (
        <span />
      )}
    </div>
  );
}

function ParamForm({ spec, value, skip, onChange, schema, pal }: { spec: Record<string, ParamSpec>; value: Tok; skip: string[]; onChange: (v: Tok) => void; schema: StyleSchema; pal: Record<string, string> }) {
  const keys = Object.keys(spec).filter((k) => !skip.includes(k));
  if (!keys.length) return <div className="text-xs" style={{ color: "var(--text-3)" }}>این نوع پارامترِ قابلِ‌ویرایش ندارد.</div>;
  return (
    <div className="space-y-2.5">
      {keys.map((k) => (
        <ParamRow
          key={k}
          name={k}
          spec={spec[k]}
          value={value[k]}
          schema={schema}
          pal={pal}
          onChange={(v) => {
            const next = { ...value };
            if (v === undefined) delete next[k];
            else next[k] = v;
            onChange(next);
          }}
        />
      ))}
    </div>
  );
}

/** یک «نوع + پارامترهایش» (پس‌زمینه، افکتِ متن) */
function KindPicker({ title, kinds, value, kindKey, onChange, schema, pal, allowNone }: { title: string; kinds: KindDef[]; value: Tok | null; kindKey: "kind" | "fx"; onChange: (v: Tok | null) => void; schema: StyleSchema; pal: Record<string, string>; allowNone?: boolean }) {
  const cur = value ? (value[kindKey] as string) : "";
  const def = kinds.find((k) => k.id === cur);
  return (
    <div className="space-y-3">
      <Field label={title}>
        <Select
          value={cur}
          onChange={(e) => {
            const v = e.target.value;
            onChange(v ? ({ [kindKey]: v } as Tok) : null);
          }}
        >
          {allowNone ? <option value="">بدون (مثلِ زمینهٔ اصلی)</option> : null}
          {kinds.map((k) => (
            <option key={k.id} value={k.id}>
              {k.label}
            </option>
          ))}
        </Select>
      </Field>
      {def && value ? <ParamForm spec={def.params} value={value} skip={[kindKey]} onChange={(v) => onChange({ [kindKey]: cur, ...v } as Tok)} schema={schema} pal={pal} /> : null}
    </div>
  );
}

function KindList({ title, kinds, items, max, onChange, schema, pal, addLabel }: { title: string; kinds: KindDef[]; items: Tok[]; max: number; onChange: (v: Tok[]) => void; schema: StyleSchema; pal: Record<string, string>; addLabel: string }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-bold" style={{ color: "var(--text)" }}>
          {title} ({fa(items.length)} از {fa(max)})
        </div>
        <Button type="button" size="sm" variant="secondary" disabled={items.length >= max} onClick={() => onChange([...items, { kind: kinds[0].id }])}>
          <Icon name="plus" size={14} /> {addLabel}
        </Button>
      </div>
      {!items.length ? <div className="text-xs" style={{ color: "var(--text-3)" }}>هیچ موردی نیست.</div> : null}
      {items.map((it, i) => {
        const def = kinds.find((k) => k.id === it.kind);
        return (
          <div key={i} className="rounded-xl p-3" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
            <div className="mb-2 flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <Select value={String(it.kind)} onChange={(e) => onChange(items.map((x, j) => (j === i ? { kind: e.target.value } : x)))} aria-label={`${title} ${i + 1}`}>
                  {kinds.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.label}
                    </option>
                  ))}
                </Select>
              </div>
              <Button type="button" size="sm" variant="ghost" onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label="حذف">
                <Icon name="trash" size={14} />
              </Button>
            </div>
            {def ? <ParamForm spec={def.params} value={it} skip={["kind"]} onChange={(v) => onChange(items.map((x, j) => (j === i ? { kind: it.kind, ...v } : x)))} schema={schema} pal={pal} /> : null}
          </div>
        );
      })}
    </div>
  );
}

function Slider({ label, value, min, max, step, onChange, fmt }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; fmt?: (v: number) => string }) {
  return (
    <div className="grid items-center gap-2 sm:grid-cols-[130px_minmax(0,1fr)_60px]">
      <div className="text-sm" style={{ color: "var(--text-2)" }}>
        {label}
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} />
      <span className="text-center text-xs tabular-nums">{fmt ? fmt(value) : fa(Number(value.toFixed(2)))}</span>
    </div>
  );
}

function CheckPanel({ check, onFix }: { check: StyleCheck; onFix?: () => void }) {
  const tone = check.state === "pass" ? "ok" : check.state === "running" ? "info" : "bad";
  return (
    <div className="space-y-2">
      <Alert tone={tone} title={check.state === "pass" ? "کنترلِ کیفیت قبول شد" : check.state === "running" ? "کنترلِ کیفیت در حال اجراست…" : check.state === "fail" ? "کنترلِ کیفیت رد کرد" : "کنترلِ کیفیت اجرا نشد"}>
        {check.summary}
        {check.state === "running" ? (
          <div className="mt-2 h-2 overflow-hidden rounded-full" style={{ background: "var(--surface-2)" }} role="progressbar" aria-valuenow={Math.round(check.progress * 100)}>
            <div className="h-full rounded-full" style={{ width: `${Math.max(4, Math.round(check.progress * 100))}%`, background: "var(--brand)", transition: "width .4s" }} />
          </div>
        ) : null}
        {check.state !== "running" && !check.geometry && check.state === "pass" ? <div className="mt-1 text-xs">بررسیِ تصویریِ فریم‌ها روی این سایت ممکن نبود؛ فقط رنگ‌ها و ساختار سنجیده شد.</div> : null}
      </Alert>
      {check.errors.length ? (
        <ul className="list-disc space-y-1 ps-5 text-sm" style={{ color: "var(--bad)" }}>
          {check.errors.map((e, i) => (
            <li key={i}>{e.message}</li>
          ))}
        </ul>
      ) : null}
      {check.warnings.length ? (
        <ul className="list-disc space-y-1 ps-5 text-xs" style={{ color: "var(--text-2)" }}>
          {check.warnings.slice(0, 6).map((e, i) => (
            <li key={i}>{e.message}</li>
          ))}
        </ul>
      ) : null}
      {check.shots.some((s) => s.image_url) ? (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {check.shots
            .filter((s) => s.image_url)
            .slice(0, 8)
            .map((s, i) => (
              <img key={i} src={s.image_url} alt={`فریمِ ${s.aspect}`} className="h-28 w-auto shrink-0 rounded-lg" style={{ border: "1px solid var(--line)" }} loading="lazy" />
            ))}
        </div>
      ) : null}
      {onFix ? (
        <Button type="button" size="sm" variant="secondary" onClick={onFix}>
          اصلاحِ خودکارِ رنگ‌ها
        </Button>
      ) : null}
    </div>
  );
}

export default function StyleEditor({
  storeId,
  schema,
  catalog,
  customStyles,
  editing,
  startFrom,
  canGlobal,
  brandColors,
  onClose,
  onSaved,
}: {
  storeId: string;
  schema: StyleSchema;
  catalog: Catalog;
  customStyles: StyleDef[];
  editing: StyleDef | null;
  startFrom: StyleDef | null;
  canGlobal: boolean;
  brandColors: string[];
  onClose: () => void;
  onSaved: (s: StyleDef) => void;
}) {
  const initial = useMemo(() => {
    if (editing) return toDoc(editing, schema.blank);
    if (startFrom) {
      const d = toDoc(startFrom, schema.blank);
      d.name_fa = `کپیِ ${startFrom.name_fa}`.slice(0, 40);
      d.name_en = "";
      d.group = "custom";
      d.tags = [];
      return d;
    }
    return clone(schema.blank);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [doc, setDoc] = useState<StyleDoc>(initial);
  const [tab, setTab] = useState<TabKey>(editing || startFrom ? "colors" : "start");
  const [aspect, setAspect] = useState("4:5");
  const [scope, setScope] = useState<"store" | "global">(editing?.scope === "global" ? "global" : "store");
  const [busy, setBusy] = useState<"" | "save" | "check" | "describe" | "palette">("");
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [info, setInfo] = useState<{ tone: "ok" | "warn" | "info"; text: string } | null>(null);
  const [contrast, setContrast] = useState<ContrastReport | null>(null);
  const [fixed, setFixed] = useState<Record<string, string> | null>(null);
  const [check, setCheck] = useState<StyleCheck | null>(null);
  const [desc, setDesc] = useState("");
  const [baseId, setBaseId] = useState(startFrom?.id || editing?.base_style || "");
  const [importText, setImportText] = useState("");
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const player = useRef<PlayerHandle>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const patch = useCallback((p: Partial<StyleDoc>) => {
    setDoc((d) => ({ ...d, ...p }));
    setCheck(null);
  }, []);
  const pal = doc.palette;

  // ───── the server validates every edit (debounced): the contrast guard and the notes come from there
  useEffect(() => {
    let live = true;
    const t = window.setTimeout(async () => {
      try {
        const r = await customApi.validate(storeId, doc);
        if (!live) return;
        setContrast(r.contrast);
        setNotes(r.notes);
        setFixed(r.fixed_palette ?? null);
      } catch (e) {
        if (live) setNotes([errText(e)]);
      }
    }, 450);
    return () => {
      live = false;
      window.clearTimeout(t);
    };
  }, [doc, storeId]);

  // ───── live preview with the store's own text (debounced; stale answers are dropped)
  const seq = useRef(0);
  useEffect(() => {
    const n = ++seq.current;
    const t = window.setTimeout(async () => {
      try {
        const spec = await customApi.preview(storeId, doc, aspect, 2);
        if (n !== seq.current) return;
        setPreviewErr(null);
        player.current?.send({ type: "template", spec });
      } catch (e) {
        if (n === seq.current) setPreviewErr(errText(e));
      }
    }, 700);
    return () => window.clearTimeout(t);
  }, [doc, aspect, storeId]);

  const allBases = useMemo(() => [...customStyles, ...catalog.styles], [customStyles, catalog.styles]);

  const loadBase = (id: string) => {
    const b = allBases.find((s) => s.id === id);
    if (!b) return;
    const d = toDoc(b, schema.blank);
    d.name_fa = `کپیِ ${b.name_fa}`.slice(0, 40);
    d.name_en = "";
    d.group = "custom";
    d.tags = [];
    setDoc(d);
    setBaseId(id);
    setCheck(null);
    setInfo({ tone: "ok", text: `از سبکِ «${b.name_fa}» شروع شد؛ هر بخش را عوض کنید.` });
  };

  const applyPalette = (p: Record<string, string>) => patch({ palette: { ...pal, ...p } });

  const describe = async () => {
    setBusy("describe");
    setError(null);
    try {
      const r = await customApi.describe(storeId, desc, baseId || undefined);
      const keep = { name_fa: doc.name_fa };
      setDoc({ ...toDoc(r.style, schema.blank), name_fa: r.style.name_fa || keep.name_fa });
      setCheck(null);
      setInfo({ tone: r.source === "ai" ? "ok" : "warn", text: r.message || (r.source === "ai" ? "پیش‌نویس با هوش مصنوعی ساخته شد." : "پیش‌نویس ساخته شد.") });
      setTab("colors");
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy("");
    }
  };

  const fromBrand = async () => {
    setBusy("palette");
    setError(null);
    try {
      const r = await customApi.palette(storeId, brandColors.length ? brandColors : undefined, undefined);
      applyPalette(r.palette);
      setInfo({ tone: "ok", text: "پالت از رنگ‌های برندِ فروشگاه ساخته شد (کنتراست رعایت شده)." });
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy("");
    }
  };

  const doImport = async (payload: unknown) => {
    setError(null);
    try {
      const r = await customApi.importJson(storeId, payload);
      setDoc(toDoc(r.style, schema.blank));
      setCheck(null);
      setInfo({ tone: r.notes.length ? "warn" : "ok", text: r.notes.length ? `وارد شد؛ ${r.notes.slice(0, 3).join("؛ ")}` : "سبک وارد شد." });
      setTab("colors");
    } catch (e) {
      setError(errText(e));
    }
  };

  const download = () => {
    const blob = new Blob([JSON.stringify({ nm_motion_style: 1, style: doc }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(doc.name_en || "style").replace(/[^A-Za-z0-9-]+/g, "-").toLowerCase() || "style"}.nm-style.json`;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };

  // ───── save = quality check, then save (only a passing check lets the server store the style)
  const saveFlow = async (onlyCheck: boolean) => {
    setError(null);
    setBusy(onlyCheck ? "check" : "save");
    try {
      const start = await customApi.check(storeId, doc);
      setFixed(start.fixed_palette);
      let c = start.check;
      setCheck(c);
      const t0 = Date.now();
      while (c.state === "running" && alive.current && Date.now() - t0 < 8 * 60 * 1000) {
        await new Promise((r) => window.setTimeout(r, 2500));
        if (!alive.current) return;
        c = await customApi.checkGet(storeId, c.id);
        setCheck(c);
      }
      if (c.state === "running") throw new Error("کنترلِ کیفیت بیش از حدِ انتظار طول کشید؛ بعداً دوباره امتحان کنید.");
      if (c.state !== "pass" || onlyCheck) return;
      const saved = editing?.pk ? await customApi.update(storeId, editing.pk, doc) : await customApi.save(storeId, { style: doc, scope, base_style: baseId || undefined });
      if (alive.current) onSaved(saved);
    } catch (e) {
      if (alive.current) setError(errText(e));
    } finally {
      if (alive.current) setBusy("");
    }
  };

  const nameOk = doc.name_fa.trim().length >= 2;
  const motionPers = schema.personalities;
  const springName = schema.springs.find((s) => s.value.every((v, i) => Math.abs(v - doc.motion.spring[i]) < 0.01))?.id ?? "";

  const roleRows = schema.roles.map((r) => {
    const vsBg = ratio(pal[r], pal.bg);
    return { r, vsBg };
  });

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto" style={{ background: "var(--bg)" }} role="dialog" aria-modal="true" aria-label="ویرایشگرِ سبکِ تازه" dir="rtl">
      <div className="mx-auto max-w-[1400px] px-4 py-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-extrabold" style={{ color: "var(--text)" }}>
              {editing ? "ویرایشِ سبک" : "سبکِ تازه"}
            </h1>
            <p className="mt-1 text-sm" style={{ color: "var(--text-3)" }}>
              رنگ، قلم، پس‌زمینه، تزئین، کارت و شخصیتِ حرکت را بسازید؛ پیش‌نمایش با متنِ فروشگاهِ شماست و سبک فقط بعد از کنترلِ کیفیتِ واقعی ذخیره می‌شود.
            </p>
          </div>
          <Button type="button" variant="secondary" onClick={onClose}>
            <Icon name="x" size={15} /> بستن
          </Button>
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_400px]">
          <div className="min-w-0 space-y-4">
            <div className="flex flex-wrap gap-2" role="tablist" aria-label="بخش‌های سبک">
              {TABS.map((t) => (
                <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className={`u-btn u-btn-sm ${tab === t.key ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setTab(t.key)}>
                  {t.label}
                </button>
              ))}
            </div>

            {info ? <Alert tone={info.tone}>{info.text}</Alert> : null}
            {error ? <Alert tone="bad">{error}</Alert> : null}

            {tab === "start" ? (
              <Card>
                <div className="space-y-5">
                  <div>
                    <div className="mb-2 text-sm font-bold">۱) از یک سبکِ موجود شروع کنید (کپی)</div>
                    <div className="flex flex-wrap items-end gap-2">
                      <div className="min-w-[220px] flex-1">
                        <Select value={baseId} onChange={(e) => setBaseId(e.target.value)} aria-label="سبکِ پایه">
                          <option value="">— انتخاب کنید —</option>
                          {customStyles.length ? (
                            <optgroup label="سبک‌های من">
                              {customStyles.map((s) => (
                                <option key={s.id} value={s.id}>
                                  {s.name_fa}
                                </option>
                              ))}
                            </optgroup>
                          ) : null}
                          {Object.entries(catalog.groups).map(([g, label]) => (
                            <optgroup key={g} label={label}>
                              {catalog.styles
                                .filter((s) => s.group === g)
                                .map((s) => (
                                  <option key={s.id} value={s.id}>
                                    {s.name_fa} — {s.name_en}
                                  </option>
                                ))}
                            </optgroup>
                          ))}
                        </Select>
                      </div>
                      <Button type="button" variant="secondary" disabled={!baseId} onClick={() => loadBase(baseId)}>
                        <Icon name="copy" size={15} /> کپیِ این سبک
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => {
                          setDoc(clone(schema.blank));
                          setBaseId("");
                          setCheck(null);
                          setInfo({ tone: "info", text: "از صفر شروع شد." });
                        }}
                      >
                        از صفر
                      </Button>
                    </div>
                  </div>

                  <div>
                    <div className="mb-2 text-sm font-bold">۲) توصیف کن، بساز</div>
                    <TextArea rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="مثلاً: تیره و سینمایی با رنگِ طلایی، حرکتِ آرام و سنگین" aria-label="توصیفِ سبک" />
                    <div className="mt-2 flex flex-wrap items-center gap-3">
                      <Button type="button" onClick={describe} disabled={busy !== "" || desc.trim().length < 3}>
                        <Icon name="sparkle" size={15} /> {busy === "describe" ? "در حال ساختن…" : "بساز"}
                      </Button>
                      <span className="text-xs" style={{ color: "var(--text-3)" }}>
                        هوش مصنوعی فقط توکن می‌نویسد؛ اگر در دسترس نباشد، پیش‌نویس با واژه‌های کلیدیِ توصیفِ شما و یکی از سبک‌های آماده ساخته می‌شود. نتیجه را می‌توانید ویرایش کنید.
                      </span>
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="نامِ فارسیِ سبک">
                      <Input value={doc.name_fa} maxLength={40} onChange={(e) => patch({ name_fa: e.target.value })} />
                    </Field>
                    <Field label="نامِ انگلیسی (برای شناسه)" hint="اختیاری">
                      <Input value={doc.name_en} maxLength={40} dir="ltr" onChange={(e) => patch({ name_en: e.target.value })} />
                    </Field>
                  </div>
                  <Field label="توضیحِ کوتاه" hint="در گالریِ سبک‌ها زیرِ نام دیده می‌شود.">
                    <TextArea rows={2} value={doc.about} maxLength={240} onChange={(e) => patch({ about: e.target.value })} />
                  </Field>
                  {canGlobal && !editing ? (
                    <Field label="دامنهٔ سبک" hint="سبکِ همگانی را همهٔ فروشگاه‌ها می‌بینند (فقط مدیرِ سامانه می‌سازد).">
                      <Select value={scope} onChange={(e) => setScope(e.target.value as "store" | "global")}>
                        <option value="store">فقط همین فروشگاه</option>
                        <option value="global">همگانی (همهٔ فروشگاه‌ها)</option>
                      </Select>
                    </Field>
                  ) : null}
                </div>
              </Card>
            ) : null}

            {tab === "colors" ? (
              <Card>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <Button type="button" size="sm" variant="secondary" onClick={fromBrand} disabled={busy !== ""}>
                    <Icon name="image" size={14} /> از رنگ‌های برندِ فروشگاه
                  </Button>
                  {fixed ? (
                    <Button type="button" size="sm" variant="secondary" onClick={() => applyPalette(fixed)}>
                      <Icon name="shield" size={14} /> اصلاحِ خودکارِ کنتراست
                    </Button>
                  ) : null}
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {roleRows.map(({ r, vsBg }) => (
                    <div key={r} className="flex items-center gap-3 rounded-xl p-2.5" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
                      <input type="color" value={pal[r]} onChange={(e) => patch({ palette: { ...pal, [r]: e.target.value } })} className="h-10 w-12 shrink-0 cursor-pointer rounded-lg" aria-label={schema.role_labels[r]} />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium" style={{ color: "var(--text)" }}>
                          {schema.role_labels[r]}
                        </div>
                        <Input value={pal[r]} dir="ltr" maxLength={7} onChange={(e) => /^#[0-9a-fA-F]{6}$/.test(e.target.value) && patch({ palette: { ...pal, [r]: e.target.value.toLowerCase() } })} aria-label={`${schema.role_labels[r]} (hex)`} />
                      </div>
                      {r !== "bg" ? (
                        <span className="shrink-0 rounded-full px-2 py-0.5 text-xs tabular-nums" style={{ background: vsBg >= 4.5 ? "var(--ok-soft)" : vsBg >= 3 ? "var(--warn-soft)" : "var(--surface)", color: "var(--text-2)" }} title="کنتراست با رنگِ زمینه">
                          {fa(vsBg.toFixed(1))}
                        </span>
                      ) : null}
                    </div>
                  ))}
                </div>
                <div className="mt-4 space-y-1.5">
                  <div className="text-sm font-bold">نگهبانِ کنتراست</div>
                  {contrast ? (
                    <ul className="space-y-1 text-sm">
                      {contrast.checks.map((c, i) => (
                        <li key={i} className="flex items-center gap-2" style={{ color: c.severity === "error" ? "var(--bad)" : c.severity === "warn" ? "var(--warn)" : "var(--text-2)" }}>
                          <Icon name={c.severity === "ok" ? "ok" : "warn"} size={14} /> {c.message}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <Spinner size={16} />
                  )}
                  <div className="text-xs" style={{ color: "var(--text-3)" }}>
                    خطا = ذخیره نمی‌شود (متنِ اصلی روی زمینه باید حداقل ۴٫۵ بگیرد)؛ هشدار = بهتر است اصلاح شود. کنتراستِ واقعیِ پیکسل‌ها بعداً در کنترلِ کیفیت سنجیده می‌شود.
                  </div>
                </div>
              </Card>
            ) : null}

            {tab === "type" ? (
              <Card>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="قلمِ لاتین (تیتر)">
                    <Select value={doc.font.latin} onChange={(e) => patch({ font: { ...doc.font, latin: e.target.value } })}>
                      {schema.fonts.map((f) => (
                        <option key={f.key} value={f.key}>
                          {f.family}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="قلمِ فارسی (تیتر)" hint="فقط قلم‌هایی که حروفِ فارسی دارند">
                    <Select value={doc.font.fa} onChange={(e) => patch({ font: { ...doc.font, fa: e.target.value } })}>
                      {schema.fonts
                        .filter((f) => f.fa)
                        .map((f) => (
                          <option key={f.key} value={f.key}>
                            {f.family}
                          </option>
                        ))}
                    </Select>
                  </Field>
                  <Field label="قلمِ لاتینِ متنِ کوچک" hint="خالی = همان وزیرمتن">
                    <Select value={doc.font.body_latin ?? ""} onChange={(e) => patch({ font: { ...doc.font, body_latin: e.target.value || null } })}>
                      <option value="">پیش‌فرض</option>
                      {schema.fonts.map((f) => (
                        <option key={f.key} value={f.key}>
                          {f.family}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="قلمِ فارسیِ متنِ کوچک">
                    <Select value={doc.font.body_fa ?? ""} onChange={(e) => patch({ font: { ...doc.font, body_fa: e.target.value || null } })}>
                      <option value="">پیش‌فرض</option>
                      {schema.fonts
                        .filter((f) => f.fa)
                        .map((f) => (
                          <option key={f.key} value={f.key}>
                            {f.family}
                          </option>
                        ))}
                    </Select>
                  </Field>
                  <Field label="وزنِ قلم">
                    <Select value={String(doc.font.weight)} onChange={(e) => patch({ font: { ...doc.font, weight: Number(e.target.value) } })}>
                      {[300, 400, 500, 600, 700, 800, 900].map((w) => (
                        <option key={w} value={w}>
                          {fa(w)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="حروفِ لاتین">
                    <Select value={doc.font.case} onChange={(e) => patch({ font: { ...doc.font, case: e.target.value as "none" | "upper" } })}>
                      <option value="none">همان‌طور که نوشته شده</option>
                      <option value="upper">همه بزرگ (UPPERCASE)</option>
                    </Select>
                  </Field>
                </div>
                <div className="mt-4 space-y-2">
                  <Slider label="فاصلهٔ حروف" value={doc.font.track} min={-0.05} max={0.4} step={0.01} onChange={(v) => patch({ font: { ...doc.font, track: v } })} />
                  <Slider label="ارتفاعِ خط" value={doc.font.lh} min={1} max={1.8} step={0.05} onChange={(v) => patch({ font: { ...doc.font, lh: v } })} />
                </div>
                <div className="mt-5 border-t pt-4" style={{ borderColor: "var(--line)" }}>
                  <KindPicker title="افکتِ متن" kinds={schema.text} value={doc.text} kindKey="fx" onChange={(v) => patch({ text: v ?? { fx: "plain" } })} schema={schema} pal={pal} />
                </div>
                <div className="mt-5 space-y-2 border-t pt-4" style={{ borderColor: "var(--line)" }}>
                  <div className="text-sm font-bold">فیلترِ کلِ تصویر</div>
                  <Select
                    value={GRADES.find((g) => g.css === (doc.fx.grade as string | undefined))?.id ?? (doc.fx.grade ? "custom" : "")}
                    onChange={(e) => {
                      const g = GRADES.find((x) => x.id === e.target.value);
                      const fx = { ...doc.fx };
                      if (g && g.css) fx.grade = g.css;
                      else delete fx.grade;
                      patch({ fx });
                    }}
                  >
                    {GRADES.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.label}
                      </option>
                    ))}
                    {doc.fx.grade && !GRADES.some((g) => g.css === doc.fx.grade) ? <option value="custom">فیلترِ واردشده</option> : null}
                  </Select>
                  {Object.entries(schema.fx).map(([k, [lo, hi]]) => (
                    <Slider
                      key={k}
                      label={k === "chroma" ? "جداشدنِ رنگ‌ها (گلیچ)" : k === "posterize" ? "پله‌ایِ رنگ (پوسترایز)" : "پیکسلی‌کردن"}
                      value={Number(doc.fx[k] ?? 0)}
                      min={0}
                      max={hi}
                      step={1}
                      fmt={(v) => (v < lo ? "خاموش" : fa(v))}
                      onChange={(v) => {
                        const fx = { ...doc.fx };
                        if (v < lo) delete fx[k];
                        else fx[k] = v;
                        patch({ fx });
                      }}
                    />
                  ))}
                </div>
              </Card>
            ) : null}

            {tab === "bg" ? (
              <Card>
                <div className="space-y-5">
                  <KindPicker title="پس‌زمینهٔ اصلی" kinds={schema.bg} value={doc.bg} kindKey="kind" onChange={(v) => patch({ bg: v ?? { kind: "solid" } })} schema={schema} pal={pal} />
                  <div className="border-t pt-4" style={{ borderColor: "var(--line)" }}>
                    <KindPicker title="پس‌زمینهٔ صحنه‌های زوج (اختیاری)" kinds={schema.bg} value={doc.bg2} kindKey="kind" allowNone onChange={(v) => patch({ bg2: v })} schema={schema} pal={pal} />
                  </div>
                  <div className="border-t pt-4" style={{ borderColor: "var(--line)" }}>
                    <KindList title="بافت (روی کلِ تصویر)" kinds={schema.tex} items={doc.tex} max={schema.limits.tex} onChange={(v) => patch({ tex: v })} schema={schema} pal={pal} addLabel="افزودنِ بافت" />
                  </div>
                </div>
              </Card>
            ) : null}

            {tab === "decor" ? (
              <Card>
                <KindList title="تزئین (لایهٔ همراه)" kinds={schema.decor} items={doc.decor} max={schema.limits.decor} onChange={(v) => patch({ decor: v })} schema={schema} pal={pal} addLabel="افزودنِ تزئین" />
              </Card>
            ) : null}

            {tab === "card" ? (
              <Card>
                <div className="space-y-2.5">
                  {Object.entries(schema.shape).map(([k, sp]) => (
                    <ParamRow
                      key={k}
                      name={k}
                      spec={sp}
                      value={doc.shape[k]}
                      schema={schema}
                      pal={pal}
                      onChange={(v) => {
                        const shape = { ...doc.shape };
                        if (v === undefined || v === "") delete shape[k];
                        else shape[k] = v;
                        patch({ shape });
                      }}
                    />
                  ))}
                </div>
              </Card>
            ) : null}

            {tab === "motion" ? (
              <Card>
                <div className="space-y-5">
                  <div>
                    <div className="mb-2 text-sm font-bold">شخصیتِ حرکت (یک‌کلیکی)</div>
                    <div className="flex flex-wrap gap-2">
                      {motionPers.map((p) => (
                        <Button key={p.id} type="button" size="sm" variant="secondary" onClick={() => patch({ motion: { ...doc.motion, ...clone(p.motion) }, trans: { kind: p.trans[0], frames: p.trans[1] } })}>
                          {p.name}
                        </Button>
                      ))}
                    </div>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="حرکتِ ورودِ عنصرها">
                      <Select value={doc.motion.enter} onChange={(e) => patch({ motion: { ...doc.motion, enter: e.target.value } })}>
                        {schema.enters.map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.label}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <Field label="منحنیِ شتاب (پیش‌فرضِ صحنه‌ها)">
                      <Select value={doc.motion.ease} onChange={(e) => patch({ motion: { ...doc.motion, ease: e.target.value } })}>
                        {schema.eases.map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.id} — {x.label}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <Field label="فنر (آماده)">
                      <Select value={springName} onChange={(e) => e.target.value && patch({ motion: { ...doc.motion, spring: [...(schema.springs.find((s) => s.id === e.target.value)?.value ?? doc.motion.spring)] as [number, number, number] } })}>
                        <option value="">دلخواه</option>
                        {schema.springs.map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.label}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  </div>
                  <div className="space-y-2">
                    <Slider label="میرایی فنر" value={doc.motion.spring[0]} min={1} max={80} step={1} onChange={(v) => patch({ motion: { ...doc.motion, spring: [v, doc.motion.spring[1], doc.motion.spring[2]] } })} />
                    <Slider label="سفتیِ فنر" value={doc.motion.spring[1]} min={20} max={400} step={5} onChange={(v) => patch({ motion: { ...doc.motion, spring: [doc.motion.spring[0], v, doc.motion.spring[2]] } })} />
                    <Slider label="جرمِ فنر" value={doc.motion.spring[2]} min={0.2} max={3} step={0.05} onChange={(v) => patch({ motion: { ...doc.motion, spring: [doc.motion.spring[0], doc.motion.spring[1], v] } })} />
                    <Slider label="تأخیرِ پله‌ای (فریم)" value={doc.motion.stagger} min={0} max={24} step={1} onChange={(v) => patch({ motion: { ...doc.motion, stagger: v } })} />
                    <Slider label="حرکتِ پله‌ای (فریم‌بر‌ثانیه)" value={doc.motion.stepFps ?? 0} min={0} max={24} step={1} fmt={(v) => (v < 4 ? "روان" : fa(v))} onChange={(v) => patch({ motion: { ...doc.motion, stepFps: v < 4 ? null : v } })} />
                    <Slider label="لرزشِ دست" value={doc.motion.wobble} min={0} max={8} step={0.5} onChange={(v) => patch({ motion: { ...doc.motion, wobble: v } })} />
                    <Slider label="زومِ دوربین" value={doc.motion.cam?.zoom ?? 0} min={0} max={0.15} step={0.01} onChange={(v) => patch({ motion: { ...doc.motion, cam: v ? { ...(doc.motion.cam || {}), zoom: v } : null } })} />
                  </div>
                  <div className="grid gap-3 border-t pt-4 sm:grid-cols-2" style={{ borderColor: "var(--line)" }}>
                    <Field label="گذار بینِ صحنه‌ها">
                      <Select value={doc.trans.kind} onChange={(e) => patch({ trans: { ...doc.trans, kind: e.target.value } })}>
                        {schema.transitions.map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.label}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <div className="self-end">
                      <Slider label="طولِ گذار (فریم)" value={doc.trans.frames} min={0} max={40} step={1} onChange={(v) => patch({ trans: { ...doc.trans, frames: v } })} />
                    </div>
                  </div>
                </div>
              </Card>
            ) : null}

            {tab === "json" ? (
              <Card>
                <div className="space-y-4">
                  <div>
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <div className="text-sm font-bold">خروجی (JSON)</div>
                      <Button type="button" size="sm" variant="secondary" onClick={download}>
                        <Icon name="download" size={14} /> دانلودِ فایل
                      </Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => navigator.clipboard?.writeText(JSON.stringify({ nm_motion_style: 1, style: doc }, null, 2)).then(() => setInfo({ tone: "ok", text: "JSON کپی شد." }))}>
                        <Icon name="copy" size={14} /> کپی
                      </Button>
                    </div>
                    <TextArea rows={10} readOnly dir="ltr" value={JSON.stringify({ nm_motion_style: 1, style: doc }, null, 2)} aria-label="JSON سبک" style={{ fontFamily: "monospace", fontSize: 12 }} />
                  </div>
                  <div>
                    <div className="mb-2 text-sm font-bold">ورودی: فایل یا JSON</div>
                    <input
                      type="file"
                      accept="application/json,.json"
                      aria-label="فایلِ سبک"
                      onChange={async (e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        try {
                          await doImport(JSON.parse(await f.text()));
                        } catch {
                          setError("فایل JSON معتبر نیست.");
                        }
                      }}
                    />
                    <TextArea rows={5} dir="ltr" value={importText} onChange={(e) => setImportText(e.target.value)} placeholder='{"nm_motion_style": 1, "style": {...}}' className="mt-2" aria-label="JSON برای ورود" />
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      className="mt-2"
                      disabled={!importText.trim()}
                      onClick={async () => {
                        try {
                          await doImport(JSON.parse(importText));
                        } catch {
                          setError("JSON معتبر نیست.");
                        }
                      }}
                    >
                      <Icon name="upload" size={14} /> واردکردن
                    </Button>
                  </div>
                </div>
              </Card>
            ) : null}

            {notes.length ? (
              <div className="rounded-xl p-3 text-xs leading-6" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>
                {notes.slice(0, 5).map((n, i) => (
                  <div key={i}>• {n}</div>
                ))}
              </div>
            ) : null}
          </div>

          {/* ───────── پیش‌نمایش + کنترلِ کیفیت + ذخیره */}
          <div className="min-w-0 space-y-4 lg:sticky lg:top-4 lg:self-start">
            <Card>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                {ASPECT_CHOICES.map((a) => (
                  <button key={a.id} type="button" className={`u-btn u-btn-sm ${aspect === a.id ? "u-btn-primary" : "u-btn-secondary"}`} aria-pressed={aspect === a.id} onClick={() => setAspect(a.id)}>
                    {a.label}
                  </button>
                ))}
              </div>
              <PlayerFrame ref={player} aspect={aspect === "9:16" ? 9 / 16 : aspect === "16:9" ? 16 / 9 : 4 / 5} maxHeight={aspect === "16:9" ? 260 : 440} />
              <div className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                پیش‌نمایشِ زنده با نام و متنِ همین فروشگاه.
              </div>
              {previewErr ? <div className="mt-2 text-xs" style={{ color: "var(--bad)" }}>{previewErr}</div> : null}
            </Card>

            <Card>
              <div className="space-y-3">
                <Field label="نامِ سبک">
                  <Input value={doc.name_fa} maxLength={40} onChange={(e) => patch({ name_fa: e.target.value })} />
                </Field>
                {check ? <CheckPanel check={check} onFix={fixed && check.state === "fail" ? () => applyPalette(fixed) : undefined} /> : null}
                {contrast && !contrast.ok && !check ? <Alert tone="warn" title="نگهبانِ کنتراست">{contrast.errors[0]}</Alert> : null}
                <div className="flex flex-wrap gap-2">
                  <Button type="button" onClick={() => saveFlow(false)} disabled={busy !== "" || !nameOk || (contrast ? !contrast.ok : false)}>
                    <Icon name="check" size={15} /> {busy === "save" ? "در حال کنترل و ذخیره…" : editing ? "کنترلِ کیفیت و ذخیرهٔ تغییرات" : "کنترلِ کیفیت و ذخیره"}
                  </Button>
                  <Button type="button" variant="secondary" onClick={() => saveFlow(true)} disabled={busy !== "" || !nameOk}>
                    {busy === "check" ? "در حال کنترل…" : "فقط کنترلِ کیفیت"}
                  </Button>
                </div>
                <div className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
                  کنترلِ کیفیت چند فریمِ واقعی (۹:۱۶ و ۱۶:۹) را با متنِ فروشگاهتان رندر می‌کند و خوانایی، بیرون‌زدنِ متن و کنتراستِ پیکسل‌ها را می‌سنجد؛ سبکی که رد شود ذخیره نمی‌شود. چند دقیقه طول می‌کشد.
                </div>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
