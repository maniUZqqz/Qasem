/** فرم‌سازِ تنظیماتِ بلوک‌ها: از روی تعریفِ سرور (catalog.py) ساخته می‌شود و واژهٔ فنی ندارد. */
import { useState } from "react";

import type { Block, BlockSpec, Catalog, Device, FieldSpec, Rec } from "./doc";
import { styleValue } from "./doc";
import type { AssetT, ModelT, PageRow, ThemeT } from "./types";

export const DEVICE_LABEL: Record<Device, string> = { d: "رایانه", t: "تبلت", p: "گوشی" };

export function Svg({ body, size = 18 }: { body: string; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      dangerouslySetInnerHTML={{ __html: body }}
    />
  );
}

export type FormEnv = {
  catalog: Catalog;
  pages: PageRow[];
  models: ModelT[];
  media: AssetT[];
  theme: ThemeT;
  hasCart: boolean;
  pickMedia: (accept: string, then: (ref: string) => void) => void;
};

const TOKENS: { v: string; label: string; key?: keyof ThemeT["colors"] }[] = [
  { v: "t:primary", label: "رنگِ اصلی", key: "primary" },
  { v: "t:text", label: "متن", key: "text" },
  { v: "t:muted", label: "متنِ کم‌رنگ", key: "muted" },
  { v: "t:bg", label: "زمینهٔ صفحه", key: "bg" },
  { v: "t:surface", label: "زمینهٔ کارت", key: "surface" },
];

export function ColorField({ label, value, onChange, theme }: { label: string; value: string; onChange: (v: string) => void; theme: ThemeT }) {
  const hex = value?.startsWith("#") ? value.slice(0, 7) : value?.startsWith("t:") ? (theme.colors[value.slice(2) as keyof ThemeT["colors"]] ?? "#888888") : "#888888";
  return (
    <div className="nbe-field">
      <div className="nbe-label">{label}</div>
      <div className="nbe-swatches">
        {TOKENS.map((t) => (
          <button
            key={t.v}
            type="button"
            className={`nbe-swatch ${value === t.v ? "on" : ""}`}
            style={{ background: t.key ? theme.colors[t.key] : undefined }}
            title={t.label}
            aria-label={t.label}
            onClick={() => onChange(t.v)}
          />
        ))}
        <label className={`nbe-swatch custom ${value?.startsWith("#") ? "on" : ""}`} title="رنگِ دلخواه" style={value?.startsWith("#") ? { background: value } : undefined}>
          <input type="color" value={hex} onChange={(e) => onChange(e.target.value)} aria-label="رنگِ دلخواه" />
        </label>
        {value && (
          <button type="button" className="nbe-link" onClick={() => onChange("")}>
            پیش‌فرض
          </button>
        )}
      </div>
    </div>
  );
}

export function SliderField({
  label,
  value,
  placeholder,
  min = 0,
  max = 100,
  unit,
  onChange,
  deviceTag,
}: {
  label: string;
  value: number | undefined;
  placeholder?: number;
  min?: number;
  max?: number;
  unit?: string;
  onChange: (v: number | null) => void;
  deviceTag?: string;
}) {
  const shown = value ?? placeholder ?? min;
  return (
    <div className="nbe-field">
      <div className="nbe-label">
        <span>
          {label}
          {deviceTag && <em className="nbe-devtag">{deviceTag}</em>}
        </span>
        <span className="nbe-num">
          {value === undefined ? "خودکار" : `${value}${unit ?? ""}`}
          {value !== undefined && (
            <button type="button" className="nbe-x" title="برگشت به خودکار" onClick={() => onChange(null)}>
              ×
            </button>
          )}
        </span>
      </div>
      <input type="range" dir="ltr" className="nbe-range" min={min} max={max} value={shown} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} />
    </div>
  );
}

function ImageField({ f, value, onChange, env }: { f: FieldSpec; value: string; onChange: (v: string) => void; env: FormEnv }) {
  const asset = value?.startsWith("m:") ? env.media.find((a) => a.ref === value) : null;
  const video = f.accept === "video";
  return (
    <div className="nbe-field">
      <div className="nbe-label">{f.label}</div>
      <div className="nbe-imagepick">
        <button type="button" className="nbe-thumb" onClick={() => env.pickMedia(f.accept ?? "image", onChange)} aria-label={`انتخابِ ${f.label}`}>
          {asset && asset.kind === "image" ? (
            <img src={asset.thumb} alt="" />
          ) : value && !value.startsWith("m:") ? (
            <img src={value} alt="" />
          ) : asset ? (
            <span>{asset.name}</span>
          ) : (
            <span>{video ? "انتخابِ ویدیو" : "انتخابِ تصویر"}</span>
          )}
        </button>
        {value && (
          <button type="button" className="nbe-link" onClick={() => onChange("")}>
            برداشتن
          </button>
        )}
      </div>
    </div>
  );
}

function LinkField({ f, value, onChange, env }: { f: FieldSpec; value: string; onChange: (v: string) => void; env: FormEnv }) {
  const isPage = value?.startsWith("page:");
  const custom = !isPage;
  return (
    <div className="nbe-field">
      <div className="nbe-label">{f.label}</div>
      <select className="nbe-input" value={isPage ? value : "__url"} onChange={(e) => onChange(e.target.value === "__url" ? "" : e.target.value)}>
        <option value="__url">نشانیِ دلخواه</option>
        {env.pages.map((p) => (
          <option key={p.id} value={`page:${p.id}`}>
            صفحهٔ «{p.title}»
          </option>
        ))}
      </select>
      {custom && (
        <input className="nbe-input mt" dir="ltr" value={value ?? ""} placeholder="https://… یا tel:0912…" onChange={(e) => onChange(e.target.value)} />
      )}
    </div>
  );
}

function IconField({ f, value, onChange, env }: { f: FieldSpec; value: string; onChange: (v: string) => void; env: FormEnv }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="nbe-field">
      <div className="nbe-label">{f.label}</div>
      <button type="button" className="nbe-iconbtn" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Svg body={env.catalog.icons[value] ?? ""} size={22} />
        <span>{open ? "بستن" : "تغییر"}</span>
      </button>
      {open && (
        <div className="nbe-icongrid">
          {env.catalog.icon_names.map((n) => (
            <button key={n} type="button" className={value === n ? "on" : ""} onClick={() => { onChange(n); setOpen(false); }} aria-label={n}>
              <Svg body={env.catalog.icons[n]} size={20} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ItemsField({ f, value, onChange, env }: { f: FieldSpec; value: Rec[]; onChange: (v: Rec[]) => void; env: FormEnv }) {
  const rows = value ?? [];
  const [open, setOpen] = useState<number | null>(null);
  const empty = () => {
    const r: Rec = {};
    (f.fields ?? []).forEach((x) => {
      r[x.key] = x.kind === "toggle" ? false : x.kind === "icon" ? "star" : x.kind === "select" ? x.options?.[0]?.value ?? "" : "";
    });
    return r;
  };
  const labelOf = (r: Rec, i: number) => {
    const k = f.item_label ?? "";
    const v = r[k];
    if (k === "image") {
      const a = env.media.find((m) => m.ref === v);
      return a?.name || `مورد ${i + 1}`;
    }
    return (v as string) || `مورد ${i + 1}`;
  };
  return (
    <div className="nbe-field">
      <div className="nbe-label">{f.label}</div>
      <div className="nbe-items">
        {rows.map((r, i) => (
          <div key={i} className="nbe-item">
            <div className="nbe-item-h">
              <button type="button" className="nbe-item-title" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}>
                {labelOf(r, i)}
              </button>
              <button type="button" title="بالاتر" aria-label="بالاتر" disabled={i === 0} onClick={() => { const n = [...rows]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; onChange(n); }}>↑</button>
              <button type="button" title="پایین‌تر" aria-label="پایین‌تر" disabled={i === rows.length - 1} onClick={() => { const n = [...rows]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; onChange(n); }}>↓</button>
              <button type="button" title="حذف" aria-label="حذف" onClick={() => { onChange(rows.filter((_, j) => j !== i)); setOpen(null); }}>×</button>
            </div>
            {open === i && (
              <div className="nbe-item-b">
                {(f.fields ?? []).map((sf) => (
                  <FieldInput key={sf.key} f={sf} value={r[sf.key]} env={env} block={null} onChange={(v) => { const n = rows.map((x) => ({ ...x })); n[i][sf.key] = v; onChange(n); }} />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <button type="button" className="nbe-add" onClick={() => { onChange([...rows, empty()]); setOpen(rows.length); }}>
        + {f.add_label ?? "افزودن"}
      </button>
    </div>
  );
}

function ModelField({ f, value, block, onChange, env }: { f: FieldSpec; value: string; block: Block | null; onChange: (v: string, extra?: Rec) => void; env: FormEnv }) {
  return (
    <div className="nbe-field">
      <div className="nbe-label">{f.label}</div>
      {env.models.length === 0 ? (
        <p className="nbe-note">هنوز داده‌ای برای این سایت تعریف نشده. از بخشِ «اپ‌ها و مدل‌ها» یک نوع داده (مثلاً محصول یا نوشته) بساز.</p>
      ) : (
        <select
          className="nbe-input"
          value={value ?? ""}
          onChange={(e) => {
            const m = env.models.find((x) => x.ref === e.target.value);
            onChange(e.target.value, { fields: m?.default_fields ?? [], sort: "" });
          }}
        >
          <option value="">انتخاب کن…</option>
          {env.models.map((m) => (
            <option key={m.ref} value={m.ref}>
              {m.label}
            </option>
          ))}
        </select>
      )}
      {block && !value && env.models.length > 0 && <p className="nbe-note">از این فهرست انتخاب کن تا موردها روی صفحه بیایند.</p>}
    </div>
  );
}

function FieldsField({ f, value, block, onChange, env }: { f: FieldSpec; value: string[]; block: Block | null; onChange: (v: string[]) => void; env: FormEnv }) {
  const model = env.models.find((m) => m.ref === block?.props.model);
  if (!model) return null;
  const chosen = value?.length ? value : model.default_fields;
  const toggle = (name: string) => {
    onChange(chosen.includes(name) ? chosen.filter((x) => x !== name) : [...chosen, name]);
  };
  return (
    <div className="nbe-field">
      <div className="nbe-label">{f.label}</div>
      <div className="nbe-checks">
        {model.fields.map((x) => (
          <label key={x.name}>
            <input type="checkbox" checked={chosen.includes(x.name)} onChange={() => toggle(x.name)} />
            <span>{x.label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

function SortField({ f, value, block, onChange, env }: { f: FieldSpec; value: string; block: Block | null; onChange: (v: string) => void; env: FormEnv }) {
  const model = env.models.find((m) => m.ref === block?.props.model);
  if (!model) return null;
  return (
    <div className="nbe-field">
      <div className="nbe-label">{f.label}</div>
      <select className="nbe-input" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">پیش‌فرض</option>
        <option value="-id">جدیدترین</option>
        <option value="id">قدیمی‌ترین</option>
        {model.fields
          .filter((x) => !["ImageField", "FileField", "ManyToManyField", "ForeignKey"].includes(x.type))
          .flatMap((x) => [
            <option key={`a-${x.name}`} value={x.name}>
              {x.label}: کم به زیاد
            </option>,
            <option key={`d-${x.name}`} value={`-${x.name}`}>
              {x.label}: زیاد به کم
            </option>,
          ])}
      </select>
    </div>
  );
}

function DetailLink({ f, value, block, onChange, env }: { f: FieldSpec; value: string; block: Block | null; onChange: (v: string) => void; env: FormEnv }) {
  const model = env.models.find((m) => m.ref === block?.props.model);
  if (!model) return null;
  return (
    <div className="nbe-field">
      <div className="nbe-label">{f.label}</div>
      <select className="nbe-input" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">جایی نرود</option>
        {model.has_detail && <option value="auto">صفحهٔ جزئیاتِ خودش</option>}
        {env.pages.map((p) => (
          <option key={p.id} value={`page:${p.id}`}>
            صفحهٔ «{p.title}»
          </option>
        ))}
      </select>
      <p className="nbe-note">برای صفحهٔ مقصد از بلوکِ «جزئیاتِ یک مورد» استفاده کن.</p>
    </div>
  );
}

export function FieldInput({
  f,
  value,
  env,
  block,
  onChange,
  device,
}: {
  f: FieldSpec;
  value: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  env: FormEnv;
  block: Block | null;
  onChange: (v: any, extra?: Rec) => void; // eslint-disable-line @typescript-eslint/no-explicit-any
  device?: Device;
}) {
  if (f.only_if === "cart" && !env.hasCart) return null;
  switch (f.kind) {
    case "text":
      return (
        <div className="nbe-field">
          <div className="nbe-label">{f.label}</div>
          <input className="nbe-input" dir={f.dir} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />
        </div>
      );
    case "textarea":
      return (
        <div className="nbe-field">
          <div className="nbe-label">{f.label}</div>
          <textarea className="nbe-input" rows={3} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />
        </div>
      );
    case "rich":
      return <p className="nbe-note">برای نوشتن، روی همین متن در صفحه بزن. با انتخابِ متن، پررنگ و پیوند هم دارد.</p>;
    case "code":
      return (
        <div className="nbe-field">
          <div className="nbe-label">{f.label}</div>
          <textarea className="nbe-input nbe-code" dir="ltr" rows={10} spellCheck={false} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />
          <p className="nbe-note">این بخش فقط برای کسی است که HTML می‌داند؛ عیناً در صفحه می‌نشیند. روی بوم اسکریپت‌ها اجرا نمی‌شوند.</p>
        </div>
      );
    case "select":
      return (
        <div className="nbe-field">
          <div className="nbe-label">{f.label}</div>
          <select className="nbe-input" value={String(value ?? "")} onChange={(e) => {
            const opt = f.options?.find((o) => String(o.value) === e.target.value);
            onChange(opt ? opt.value : e.target.value);
          }}>
            {f.options?.map((o) => (
              <option key={String(o.value)} value={String(o.value)}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      );
    case "toggle":
      return (
        <label className="nbe-toggle">
          <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
          <span>{f.label}</span>
        </label>
      );
    case "slider":
      if (f.device) {
        const dev = device ?? "d";
        const obj: Rec = value && typeof value === "object" ? value : {};
        const effective = (dev === "p" ? obj.p ?? obj.t ?? obj.d : dev === "t" ? obj.t ?? obj.d : obj.d) as number | undefined;
        return (
          <SliderField label={f.label} value={effective} min={f.min} max={f.max} unit={f.unit} deviceTag={DEVICE_LABEL[dev]}
            onChange={(v) => { const n = { ...obj }; if (v === null) delete n[dev]; else n[dev] = v; onChange(n); }} />
        );
      }
      return <SliderField label={f.label} value={value ?? undefined} min={f.min} max={f.max} unit={f.unit} onChange={(v) => onChange(v ?? f.min ?? 0)} />;
    case "decimal":
      return (
        <div className="nbe-field">
          <div className="nbe-label">{f.label}</div>
          <input className="nbe-input" dir="ltr" type="number" step="0.0001" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
        </div>
      );
    case "color":
      return <ColorField label={f.label} value={value ?? ""} onChange={onChange} theme={env.theme} />;
    case "image":
      return <ImageField f={f} value={value ?? ""} onChange={onChange} env={env} />;
    case "link":
      return <LinkField f={f} value={value ?? ""} onChange={onChange} env={env} />;
    case "icon":
      return <IconField f={f} value={value ?? "star"} onChange={onChange} env={env} />;
    case "items":
      return <ItemsField f={f} value={value ?? []} onChange={onChange} env={env} />;
    case "model":
      return <ModelField f={f} value={value ?? ""} block={block} onChange={onChange} env={env} />;
    case "fields":
      return <FieldsField f={f} value={value ?? []} block={block} onChange={onChange} env={env} />;
    case "sort":
      return <SortField f={f} value={value ?? ""} block={block} onChange={onChange} env={env} />;
    case "detail_link":
      return <DetailLink f={f} value={value ?? ""} block={block} onChange={onChange} env={env} />;
    default:
      return null;
  }
}

/** زبانهٔ «ظاهر»: تنظیم‌های مجازِ همین بلوک، دسته‌بندی‌شده */
export function StyleForm({
  spec,
  block,
  device,
  env,
  onChange,
}: {
  spec: BlockSpec;
  block: Block;
  device: Device;
  env: FormEnv;
  onChange: (device: Device, key: string, value: unknown) => void;
}) {
  const allowed = new Set(spec.style);
  const groups = env.catalog.style_groups
    .map((g) => ({ ...g, rows: env.catalog.style.filter((s) => s.group === g.value && allowed.has(s.key)) }))
    .filter((g) => g.rows.length);
  if (!groups.length) return <p className="nbe-note">این بلوک تنظیمِ ظاهری ندارد.</p>;
  return (
    <>
      {groups.map((g) => (
        <details key={g.value} className="nbe-group" open={g.value === "text" || g.value === "bg" || g.value === "space"}>
          <summary>{g.label}</summary>
          {g.rows.map((s) => {
            const dev: Device = s.device ? device : "d";
            const own = block.style?.[dev]?.[s.key] as unknown;
            const eff = styleValue(block.style, dev, s.key);
            if (s.kind === "color") {
              return <ColorField key={s.key} label={s.label} value={(own as string) ?? ""} theme={env.theme} onChange={(v) => onChange("d", s.key, v)} />;
            }
            if (s.kind === "slider") {
              return (
                <SliderField key={s.key} label={s.label} value={(own as number) ?? undefined} placeholder={eff as number} min={s.min} max={s.max} unit={s.unit}
                  deviceTag={s.device ? DEVICE_LABEL[dev] : undefined} onChange={(v) => onChange(dev, s.key, v)} />
              );
            }
            if (s.kind === "align") {
              const cur = (eff as string) ?? "";
              return (
                <div className="nbe-field" key={s.key}>
                  <div className="nbe-label">
                    <span>
                      {s.label}
                      <em className="nbe-devtag">{DEVICE_LABEL[dev]}</em>
                    </span>
                  </div>
                  <div className="nbe-seg">
                    {[["start", "راست"], ["center", "وسط"], ["end", "چپ"]].map(([v, l]) => (
                      <button key={v} type="button" className={cur === v ? "on" : ""} onClick={() => onChange(dev, s.key, cur === v ? null : v)}>
                        {l}
                      </button>
                    ))}
                  </div>
                </div>
              );
            }
            if (s.kind === "select") {
              return (
                <div className="nbe-field" key={s.key}>
                  <div className="nbe-label">{s.label}</div>
                  <select className="nbe-input" value={(own as string) ?? ""} onChange={(e) => onChange("d", s.key, e.target.value)}>
                    {s.options?.map((o) => (
                      <option key={String(o.value)} value={String(o.value)}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
              );
            }
            if (s.kind === "toggle") {
              return (
                <label className="nbe-toggle" key={s.key}>
                  <input type="checkbox" checked={!!own} onChange={(e) => onChange("d", s.key, e.target.checked)} />
                  <span>{s.label}</span>
                </label>
              );
            }
            if (s.kind === "image") {
              return <ImageField key={s.key} f={s} value={(own as string) ?? ""} env={env} onChange={(v) => onChange("d", s.key, v)} />;
            }
            return null;
          })}
        </details>
      ))}
    </>
  );
}
