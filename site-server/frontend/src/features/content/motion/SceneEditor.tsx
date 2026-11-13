import { useRef } from "react";

import Icon from "../../../components/Icon";
import { Button, Card, Field, Input, Select, TextArea, fa } from "../../../components/ui";
import { SCENE_LABELS, Scene, SceneType, Source } from "./api";

type Kind = "text" | "area" | "lines" | "number" | "bool" | "image";
type FieldDef = { key: string; label: string; kind?: Kind; placeholder?: string; hint?: string };

const FIELDS: Record<SceneType, FieldDef[]> = {
  title: [
    { key: "kicker", label: "عنوانِ کوچک (اختیاری)", placeholder: "مثلاً «معرفی»" },
    { key: "title", label: "عنوان" },
    { key: "subtitle", label: "زیرعنوان (اختیاری)", kind: "area" },
  ],
  list: [
    { key: "title", label: "عنوان" },
    { key: "items", label: "موردها", kind: "lines", hint: "هر مورد در یک خط؛ حداکثر ۶ مورد" },
    { key: "numbered", label: "شماره‌دار", kind: "bool" },
  ],
  quote: [
    { key: "text", label: "متنِ نقل‌قول", kind: "area" },
    { key: "author", label: "گوینده (اختیاری)" },
  ],
  stat: [
    { key: "kicker", label: "عنوانِ کوچک (اختیاری)" },
    { key: "value", label: "عدد", placeholder: "مثلاً ۱۳۰۰" },
    { key: "prefix", label: "پیش‌وند (اختیاری)" },
    { key: "suffix", label: "پس‌وند (اختیاری)", placeholder: "+ یا ٪" },
    { key: "label", label: "توضیحِ عدد", kind: "area" },
    { key: "count_up", label: "شمارشِ تدریجیِ عدد", kind: "bool" },
  ],
  compare: [
    { key: "title", label: "عنوان (اختیاری)" },
    { key: "before_label", label: "برچسبِ «قبل»" },
    { key: "before", label: "متنِ قبل" },
    { key: "before_image", label: "تصویرِ قبل (اختیاری)", kind: "image" },
    { key: "after_label", label: "برچسبِ «بعد»" },
    { key: "after", label: "متنِ بعد" },
    { key: "after_image", label: "تصویرِ بعد (اختیاری)", kind: "image", hint: "اگر هر دو تصویر را بدهید، به‌صورتِ لغزندهٔ قبل/بعد نمایش داده می‌شود" },
  ],
  product: [
    { key: "name", label: "نامِ محصول" },
    { key: "price", label: "قیمت (اختیاری)", hint: "فقط قیمتِ واقعی را بنویسید" },
    { key: "badge", label: "برچسب (اختیاری)", placeholder: "مثلاً «جدید»" },
    { key: "features", label: "ویژگی‌ها", kind: "lines", hint: "هر ویژگی در یک خط؛ حداکثر ۴" },
    { key: "image", label: "تصویرِ محصول", kind: "image" },
  ],
  logo: [
    { key: "title", label: "نام (اختیاری؛ خالی = نامِ برند)" },
    { key: "tagline", label: "شعار (اختیاری)" },
  ],
  app: [
    { key: "caption", label: "عنوان", kind: "area" },
    { key: "bullets", label: "قابلیت‌ها", kind: "lines", hint: "هر قابلیت در یک خط؛ حداکثر ۴" },
    { key: "screenshot", label: "اسکرین‌شاتِ اپ (اختیاری)", kind: "image" },
  ],
  cta: [
    { key: "title", label: "عنوان" },
    { key: "button", label: "متنِ دکمه" },
    { key: "note", label: "یادداشتِ کوچک (اختیاری)", placeholder: "مثلاً نشانیِ سایت" },
  ],
};

export const DEFAULT_SCENE: Record<SceneType, Scene> = {
  title: { type: "title", duration: 4, kicker: "", title: "عنوانِ ویدیو", subtitle: "" },
  list: { type: "list", duration: 7, title: "سه قدمِ ساده", items: ["قدمِ اول", "قدمِ دوم", "قدمِ سوم"], numbered: true },
  quote: { type: "quote", duration: 5, text: "جمله‌ای که می‌ارزد به یاد بماند.", author: "" },
  stat: { type: "stat", duration: 4, kicker: "", value: "100", suffix: "+", label: "توضیحِ عدد", count_up: true },
  compare: { type: "compare", duration: 6, title: "", before_label: "قبل", after_label: "بعد", before: "وضعیتِ قبل", after: "وضعیتِ بعد" },
  product: { type: "product", duration: 6, name: "نامِ محصول", price: "", badge: "", features: ["ویژگیِ اول", "ویژگیِ دوم"] },
  logo: { type: "logo", duration: 3, title: "", tagline: "" },
  app: { type: "app", duration: 6, caption: "اپِ شما، در یک نگاه", bullets: ["قابلیتِ اول", "قابلیتِ دوم"] },
  cta: { type: "cta", duration: 4, title: "همین حالا شروع کنید", button: "ثبت‌نام", note: "" },
};

function ImagePicker({ value, sources, onPick, onUpload }: { value: string; sources: Source[]; onPick: (ref: string) => void; onUpload: (f: File) => void }) {
  const file = useRef<HTMLInputElement>(null);
  const current = sources.find((s) => s.ref === value);
  return (
    <div className="flex items-center gap-2">
      {current ? <img src={current.url} alt="" className="h-10 w-10 rounded-lg object-cover" /> : <span className="h-10 w-10 rounded-lg" style={{ background: "var(--surface-2)" }} />}
      <div className="min-w-0 flex-1">
        <Select value={value} onChange={(e) => onPick(e.target.value)}>
          <option value="">— بدونِ تصویر —</option>
          {sources.map((s) => (
            <option key={s.ref} value={s.ref}>
              {s.group}: {s.title}
            </option>
          ))}
        </Select>
      </div>
      <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} />
      <Button variant="secondary" size="sm" type="button" onClick={() => file.current?.click()}>
        <Icon name="upload" size={14} /> بارگذاری
      </Button>
    </div>
  );
}

function SceneFields({ sc, onChange, sources, onUpload }: { sc: Scene; onChange: (s: Scene) => void; sources: Source[]; onUpload: (f: File) => void }) {
  const set = (k: string, v: unknown) => onChange({ ...sc, [k]: v });
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {FIELDS[sc.type].map((f) => {
        const v = sc[f.key];
        const wide = f.kind === "area" || f.kind === "lines" || f.kind === "image";
        return (
          <div key={f.key} className={wide ? "sm:col-span-2" : ""}>
            {f.kind === "bool" ? (
              <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
                <input type="checkbox" checked={v !== false && !!v} onChange={(e) => set(f.key, e.target.checked)} /> {f.label}
              </label>
            ) : (
              <Field label={f.label} hint={f.hint}>
                {f.kind === "area" ? (
                  <TextArea rows={2} value={String(v ?? "")} onChange={(e) => set(f.key, e.target.value)} placeholder={f.placeholder} />
                ) : f.kind === "lines" ? (
                  <TextArea rows={3} value={(Array.isArray(v) ? (v as string[]) : []).join("\n")} onChange={(e) => set(f.key, e.target.value.split("\n"))} />
                ) : f.kind === "image" ? (
                  <ImagePicker value={String(v ?? "")} sources={sources} onPick={(r) => set(f.key, r)} onUpload={onUpload} />
                ) : (
                  <Input value={String(v ?? "")} onChange={(e) => set(f.key, e.target.value)} placeholder={f.placeholder} />
                )}
              </Field>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function SceneEditor({
  scenes,
  onChange,
  sources,
  onUpload,
  maxScenes,
}: {
  scenes: Scene[];
  onChange: (s: Scene[]) => void;
  sources: Source[];
  onUpload: (f: File) => void;
  maxScenes: number;
}) {
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
        <Card key={i}>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold" style={{ background: "var(--brand-soft, var(--surface-2))", color: "var(--brand)" }}>
              {fa(i + 1)}
            </span>
            <div className="w-52">
              <Select value={sc.type} onChange={(e) => onChange(scenes.map((x, k) => (k === i ? { ...DEFAULT_SCENE[e.target.value as SceneType], duration: x.duration } : x)))}>
                {(Object.keys(SCENE_LABELS) as SceneType[]).map((t) => (
                  <option key={t} value={t}>
                    {SCENE_LABELS[t]}
                  </option>
                ))}
              </Select>
            </div>
            <label className="flex items-center gap-1 text-sm" style={{ color: "var(--text-2)" }}>
              مدت
              <input
                type="number"
                min={1}
                max={30}
                step={0.5}
                value={sc.duration}
                onChange={(e) => onChange(scenes.map((x, k) => (k === i ? { ...x, duration: Number(e.target.value) } : x)))}
                className="u-input"
                style={{ width: 72 }}
              />
              ثانیه
            </label>
            <span className="flex-1" />
            <Button variant="ghost" size="sm" type="button" onClick={() => move(i, -1)} disabled={i === 0} title="بالا">
              <Icon name="up" size={14} />
            </Button>
            <Button variant="ghost" size="sm" type="button" onClick={() => move(i, 1)} disabled={i === scenes.length - 1} title="پایین">
              <Icon name="down" size={14} />
            </Button>
            <Button variant="ghost" size="sm" type="button" onClick={() => scenes.length < maxScenes && onChange([...scenes.slice(0, i + 1), { ...sc }, ...scenes.slice(i + 1)])} title="کپی">
              <Icon name="copy" size={14} />
            </Button>
            <Button variant="ghost" size="sm" type="button" onClick={() => scenes.length > 1 && onChange(scenes.filter((_, k) => k !== i))} disabled={scenes.length < 2} title="حذف">
              <Icon name="trash" size={14} />
            </Button>
          </div>
          <SceneFields sc={sc} onChange={(s) => onChange(scenes.map((x, k) => (k === i ? s : x)))} sources={sources} onUpload={onUpload} />
        </Card>
      ))}
      <Button variant="secondary" type="button" disabled={scenes.length >= maxScenes} onClick={() => onChange([...scenes, { ...DEFAULT_SCENE.title }])}>
        <Icon name="plus" size={15} /> افزودنِ صحنه
      </Button>
    </div>
  );
}
