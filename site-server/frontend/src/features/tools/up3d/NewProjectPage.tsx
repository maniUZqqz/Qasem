import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, ErrorBox, Field, Input, PageHeader, Select, Spinner, TextArea } from "../../../components/ui";
import { P, desc, errMsg, label, thumbUrl, up3d } from "./api";
import { Muted, useCatalog, useStatus, useToast } from "./shared";
import type { Asset, Template } from "./types";

/**
 * «تبلیغِ تازه»: محصول، سبک، کارگردانی ⇐ خلاصهٔ کار (brief) ⇐ کارِ برنامه‌ریزی ⇐ ویرایشگر.
 * همان فرمِ project_new.html ِ قدیمی؛ خروجی‌اش دقیقاً همان brief است که قالب‌ها و کارگردانِ AI می‌خوانند.
 */

type PickKind = "product" | "character" | "environment";

const ICONS: Record<PickKind, "box" | "users" | "store"> = { product: "box", character: "users", environment: "store" };

function Picker({ kind, list, value, onChange }: { kind: PickKind; list: Asset[]; value: string | null; onChange: (id: string) => void }) {
  return (
    <div className="u3d-pick">
      {list.map((a) => {
        const th = thumbUrl(kind, a);
        return (
          <button type="button" key={a.id} className={`u3d-opt ${a.id === value ? "on" : ""}`} onClick={() => onChange(a.id)}>
            <div className="im" style={th ? { backgroundImage: `url('${th}')` } : undefined}>
              {!th && <Icon name={ICONS[kind]} size={30} />}
            </div>
            <div className="tx">
              {label(a)}
              <small>{desc(a).slice(0, 70)}</small>
            </div>
          </button>
        );
      })}
    </div>
  );
}

type FileState = { text: string; ok: boolean; path: string | null };

export default function NewProjectPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { cat, error: catError } = useCatalog();
  const status = useStatus();
  const [templates, setTemplates] = useState<Template[]>([]);

  const [productName, setProductName] = useState("");
  const [brand, setBrand] = useState("");
  const [tagline, setTagline] = useState("");
  const [price, setPrice] = useState("");
  const [benefits, setBenefits] = useState("");
  const [labelColor, setLabelColor] = useState("#f4efe6");
  const [accentColor, setAccentColor] = useState("#b08d57");
  const [liquidColor, setLiquidColor] = useState("#e8b04a");
  const [product, setProduct] = useState<string | null>("perfume_bottle");
  const [character, setCharacter] = useState<string | null>(null);
  const [environment, setEnvironment] = useState<string | null>(null);
  const [voice, setVoice] = useState("");
  const [aspect, setAspect] = useState("9:16");
  const [tone, setTone] = useState("گرم و صمیمی");
  const [cta, setCta] = useState("");
  const [request, setRequest] = useState("");
  const [mode, setMode] = useState<"ai" | "template">("ai");
  const [template, setTemplate] = useState("showcase");
  const [labelFile, setLabelFile] = useState<FileState>({ text: "روی برچسبِ بدنهٔ محصول می‌نشیند", ok: false, path: null });
  const [modelFile, setModelFile] = useState<FileState>({ text: "GLB/OBJ/FBX — اگر بدهید، به‌جای شکلِ آماده می‌نشیند", ok: false, path: null });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const aiReady = status?.ai_ready ?? true;

  useEffect(() => {
    up3d
      .templates()
      .then(setTemplates)
      .catch((e) => setError(errMsg(e)));
  }, []);

  // پیش‌فرض‌ها از خودِ دفتر: دارایی‌ای که default دارد، وگرنه اولی
  useEffect(() => {
    if (!cat) return;
    const def = (list: Asset[]) => (list.find((a) => a.default) || list[0])?.id ?? null;
    setCharacter((v) => v ?? def(cat.character));
    setEnvironment((v) => v ?? def(cat.environment));
    setProduct((v) => (v && cat.product.some((p) => p.id === v) ? v : def(cat.product.filter((p) => p.id !== "custom_model"))));
  }, [cat]);

  // بدونِ کلیدِ AI، روش پیش‌فرض قالب است
  useEffect(() => {
    if (status && !status.ai_ready) setMode("template");
  }, [status]);

  // صدای هم‌جنس با مجری
  useEffect(() => {
    if (!cat) return;
    const g = cat.character.find((c) => c.id === character)?.gender;
    const best = cat.voice.find((v) => v.gender === g) || cat.voice[0];
    if (best) setVoice(best.id);
  }, [cat, character]);

  const uploadTo = async (file: File | undefined, set: (s: FileState) => void) => {
    if (!file) return;
    set({ text: "در حالِ فرستادن…", ok: false, path: null });
    try {
      const r = await up3d.upload(file);
      set({ text: "بارگذاری شد ✓", ok: true, path: r.path });
    } catch (e) {
      set({ text: errMsg(e), ok: false, path: null });
    }
  };

  const go = async () => {
    if (!productName.trim()) {
      toast("نامِ محصول لازم است", true);
      return;
    }
    const brief: Record<string, unknown> = {
      product_name: productName.trim(),
      brand: brand.trim(),
      tagline: tagline.trim(),
      price: price.trim(),
      cta: cta.trim(),
      benefits: benefits
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      request: request.trim(),
      tone,
      aspect,
      voice,
      product_asset: modelFile.path ? "custom_model" : product,
      character,
      environment,
      template,
      product_params: { label_color: labelColor, accent_color: accentColor, liquid_color: liquidColor },
    };
    if (labelFile.path) brief.label_image = labelFile.path;
    if (modelFile.path) brief.model_path = modelFile.path;
    setBusy(true);
    setError(null);
    try {
      const r = await up3d.createProject({ brief, mode, template });
      navigate(P.project(r.project.id));
    } catch (e) {
      setError(errMsg(e));
      setBusy(false);
    }
  };

  if (!cat) {
    return (
      <div className="py-10 text-center">
        {catError ? <ErrorBox message={catError} /> : <Spinner />}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="تبلیغِ تازه"
        actions={aiReady ? <Badge tone="ok">کارگردانِ AI آماده</Badge> : <Badge tone="warn">بدونِ کلیدِ AI ⇐ قالبِ آماده</Badge>}
      />
      <ErrorBox message={error} />

      <form
        className="grid gap-4 lg:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          void go();
        }}
      >
        <div className="space-y-4">
          <Card>
            <h2 className="mb-3 text-lg font-bold" style={{ color: "var(--text)" }}>
              ۱. محصول
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="نامِ محصول *">
                <Input value={productName} onChange={(e) => setProductName(e.target.value)} required placeholder="مثلاً عطرِ رز" />
              </Field>
              <Field label="برند">
                <Input value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="مثلاً UpMarket" />
              </Field>
            </div>
            <div className="mt-3">
              <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                شکلِ محصول
              </span>
              <Picker kind="product" list={cat.product.filter((p) => p.id !== "custom_model")} value={product} onChange={setProduct} />
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label="شعار (روی برچسب)">
                <Input value={tagline} onChange={(e) => setTagline(e.target.value)} placeholder="رایحهٔ ماندگار" />
              </Field>
              <Field label="قیمت (اختیاری)">
                <Input value={price} onChange={(e) => setPrice(e.target.value)} placeholder="۸۹۰ هزار تومان" />
              </Field>
            </div>
            <div className="mt-3">
              <Field label="ویژگی‌ها / توضیح">
                <TextArea
                  rows={4}
                  value={benefits}
                  onChange={(e) => setBenefits(e.target.value)}
                  placeholder={"هر ویژگی در یک خط؛ مثلاً:\nرایحه‌ای گرم و ماندگار تا پایانِ روز\nشیشه‌ای زیبا، هدیه‌ای به‌یادماندنی"}
                />
              </Field>
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label="عکس/لوگوی برچسب (اختیاری)" hint={labelFile.text}>
                <input type="file" accept="image/*" className="u-input" onChange={(e) => void uploadTo(e.target.files?.[0], setLabelFile)} />
              </Field>
              <Field label="مدلِ سه‌بعدیِ خودِ محصول (اختیاری)" hint={modelFile.text}>
                <input
                  type="file"
                  accept=".glb,.gltf,.obj,.fbx"
                  className="u-input"
                  onChange={(e) => void uploadTo(e.target.files?.[0], setModelFile)}
                />
              </Field>
            </div>
            <div className="mt-3 flex flex-wrap gap-4">
              <Field label="رنگِ برچسب">
                <input type="color" value={labelColor} onChange={(e) => setLabelColor(e.target.value)} className="u-input" style={{ width: 64, height: 38, padding: 2 }} />
              </Field>
              <Field label="رنگِ تزئین">
                <input type="color" value={accentColor} onChange={(e) => setAccentColor(e.target.value)} className="u-input" style={{ width: 64, height: 38, padding: 2 }} />
              </Field>
              <Field label="رنگِ عطر/مایع">
                <input type="color" value={liquidColor} onChange={(e) => setLiquidColor(e.target.value)} className="u-input" style={{ width: 64, height: 38, padding: 2 }} />
              </Field>
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <h2 className="mb-3 text-lg font-bold" style={{ color: "var(--text)" }}>
              ۲. سبک
            </h2>
            <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
              مجری
            </span>
            <Picker kind="character" list={cat.character} value={character} onChange={setCharacter} />
            <span className="mb-1.5 mt-3 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
              محیط
            </span>
            <Picker kind="environment" list={cat.environment} value={environment} onChange={setEnvironment} />
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <Field label="صدا">
                <Select value={voice} onChange={(e) => setVoice(e.target.value)}>
                  {cat.voice.map((v) => (
                    <option key={v.id} value={v.id}>
                      {label(v)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="قاب">
                <Select value={aspect} onChange={(e) => setAspect(e.target.value)}>
                  <option value="9:16">عمودی ۹:۱۶ (استوری/ریلز)</option>
                  <option value="16:9">افقی ۱۶:۹</option>
                  <option value="1:1">مربع ۱:۱</option>
                  <option value="4:5">۴:۵ (پست)</option>
                </Select>
              </Field>
              <Field label="لحن">
                <Select value={tone} onChange={(e) => setTone(e.target.value)}>
                  <option value="گرم و صمیمی">گرم و صمیمی</option>
                  <option value="لوکس و آرام">لوکس و آرام</option>
                  <option value="پرانرژی و شاد">پرانرژی و شاد</option>
                  <option value="رسمی و مطمئن">رسمی و مطمئن</option>
                </Select>
              </Field>
            </div>
            <div className="mt-3">
              <Field label="دعوت به خرید">
                <Input value={cta} onChange={(e) => setCta(e.target.value)} placeholder="همین حالا از آپ‌مارکت سفارش بدید!" />
              </Field>
            </div>
          </Card>

          <Card>
            <h2 className="mb-3 text-lg font-bold" style={{ color: "var(--text)" }}>
              ۳. کارگردانی
            </h2>
            <Field label="درخواستِ آزاد برای کارگردانِ AI">
              <TextArea
                rows={4}
                value={request}
                onChange={(e) => setRequest(e.target.value)}
                placeholder="مثلاً: یک خانم عطر را از روی میز بردارد، نزدیکِ صورتش نشان بدهد، کمی روی گردن بزند و با لبخند دعوت به خرید کند. ۱۲ ثانیه."
              />
            </Field>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label="روش">
                <Select value={mode} onChange={(e) => setMode(e.target.value as "ai" | "template")}>
                  <option value="ai" disabled={!aiReady}>
                    کارگردانِ هوشِ مصنوعی
                  </option>
                  <option value="template">قالبِ آماده (بی‌AI)</option>
                </Select>
              </Field>
              <Field label="قالب (و پشتیبانِ AI)">
                <Select value={template} onChange={(e) => setTemplate(e.target.value)}>
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.fa}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Button type="submit" disabled={busy} className="mt-4 w-full" style={{ padding: 12 }}>
              {busy ? "در حالِ ساخت…" : "ساختِ برنامهٔ تبلیغ ⇐"}
            </Button>
            <Muted className="mt-2">
              بعد از ساخت، صحنه را در ویرایشگر می‌بینید، تغییر می‌دهید و اول «انیمیک» (چند دقیقه) و بعد کیفیتِ بالاتر می‌گیرید.
            </Muted>
          </Card>
        </div>
      </form>
    </div>
  );
}
