import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, ErrorBox, Field, Input, PageHeader, Select, Spinner, TextArea } from "../../../components/ui";
import { P, desc, errMsg, fa, label, thumbUrl, up3d } from "./api";
import { Advanced, Muted, Section, useCatalog, useStatus, useToast } from "./shared";
import type { Asset, Template } from "./types";

/**
 * «تبلیغِ تازه» — سه گامِ شماره‌دار + کارتِ چسبانِ «چه چیزی ساخته می‌شود»:
 *   ۱ محصول (نام، برند، شکل، شعار، قیمت، ویژگی‌ها؛ پیشرفته: عکسِ برچسب، مدلِ سه‌بعدی، رنگ‌ها)
 *   ۲ مجری و صحنه (مجری، محیط، صدا، قاب، لحن)
 *   ۳ پیام و کارگردانی (دعوت به خرید، درخواستِ آزاد، روش: AI یا قالب، قالب)
 * خروجی دقیقاً همان brief ِ قبلی است که قالب‌ها و کارگردانِ AI می‌خوانند (هیچ فیلدی کم نشده).
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

const ASPECT_FA: Record<string, string> = { "9:16": "عمودی ۹:۱۶ (استوری/ریلز)", "16:9": "افقی ۱۶:۹", "1:1": "مربع ۱:۱", "4:5": "۴:۵ (پست)" };

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
  const [screenFiles, setScreenFiles] = useState<FileState[]>(() => [0, 1, 2, 3].map(() => ({ text: "اسکرین‌شاتِ اپ (اختیاری)", ok: false, path: null })));
  const [logoFile, setLogoFile] = useState<FileState>({ text: "PNG/JPG؛ ترجیحاً با زمینهٔ شفاف", ok: false, path: null });
  const [brandColor, setBrandColor] = useState("#126f85");
  const [brandColor2, setBrandColor2] = useState("#163f75");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const aiReady = status?.ai_ready ?? true;
  const chosenTplMeta = templates.find((t) => t.id === template);
  const isAd = chosenTplMeta?.group === "ad";
  const tplInputs = chosenTplMeta?.inputs || [];
  const fixedAsset = isAd && !!chosenTplMeta?.asset;      // شکلِ محصول را خودِ قالب می‌گذارد

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

  // قالب‌های تبلیغاتیِ بی‌مجری بی‌AI ساخته می‌شوند (کارگردانِ AI مجری می‌چیند)
  useEffect(() => {
    if (isAd) setMode("template");
  }, [isAd]);

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
      document.getElementById("u3d-product-name")?.focus();
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
    if (isAd) {
      const shots = screenFiles.map((s) => s.path).filter((p): p is string => !!p);
      if (tplInputs.includes("screens") && shots.length) brief.screens = shots;
      if (tplInputs.includes("logo") && logoFile.path) brief.logo_image = logoFile.path;
      if (tplInputs.includes("brand_colors")) {
        brief.brand_color = brandColor;
        brief.brand_color_2 = brandColor2;
      }
      if (productName.trim() === "" && brand.trim()) brief.product_name = brand.trim();
    }
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

  const chosenProduct = cat.product.find((p) => p.id === product);
  const chosenChar = cat.character.find((c) => c.id === character);
  const chosenEnv = cat.environment.find((e) => e.id === environment);
  const chosenVoice = cat.voice.find((v) => v.id === voice);
  const chosenTpl = templates.find((t) => t.id === template);
  // قالبِ تبلیغاتیِ بی‌مجری: شکلِ محصول را خودِ قالب می‌گذارد، مجری و گفتار ندارد و صحنه (استیج) را خودش می‌چیند
  const adShape = isAd && chosenTplMeta?.asset ? cat.product.find((p) => p.id === chosenTplMeta.asset) : undefined;

  const summary = (
    <Card>
      <h2 className="text-base font-bold" style={{ color: "var(--text)" }}>
        چه چیزی ساخته می‌شود
      </h2>
      <table className="u3d-kv mt-2 w-full">
        <tbody>
          <tr>
            <td>محصول</td>
            <td>
              {productName.trim() || <span style={{ color: "var(--bad)" }}>نام لازم است</span>}
              {brand.trim() ? ` · ${brand.trim()}` : ""}
              {" · "}
              {adShape ? label(adShape) : modelFile.path ? "مدلِ خودتان" : label(chosenProduct)}
            </td>
          </tr>
          {isAd ? (
            <>
              <tr>
                <td>مجری / صحنه</td>
                <td>بی‌مجری · استیجِ آماده با نورِ استودیویی و دوربینِ سینمایی (بعد از ساخت در ویرایشگر قابلِ تغییر است)</td>
              </tr>
              <tr>
                <td>گفتار / قاب</td>
                <td>بی‌گفتار (فقط تصویر و نوشته‌های خودِ شما) · {ASPECT_FA[aspect] || aspect}</td>
              </tr>
            </>
          ) : (
            <>
              <tr>
                <td>مجری / محیط</td>
                <td>
                  {label(chosenChar)} · {label(chosenEnv)}
                </td>
              </tr>
              <tr>
                <td>صدا / قاب</td>
                <td>
                  {label(chosenVoice)} · {ASPECT_FA[aspect] || aspect}
                </td>
              </tr>
              <tr>
                <td>لحن</td>
                <td>{tone}</td>
              </tr>
            </>
          )}
          <tr>
            <td>روش</td>
            <td>
              {mode === "ai" ? "کارگردانِ هوشِ مصنوعی" : "قالبِ آماده"} · {chosenTpl?.fa || template}
            </td>
          </tr>
        </tbody>
      </table>
      <div className="mt-3">
        {isAd ? (
          <Badge tone="ok">قالبِ آماده — بی‌نیاز به AI</Badge>
        ) : aiReady ? (
          <Badge tone="ok">کارگردانِ AI آماده</Badge>
        ) : (
          <Badge tone="warn">بدونِ کلیدِ AI ⇐ قالبِ آماده</Badge>
        )}
      </div>
      <Button type="submit" disabled={busy} className="mt-3 w-full" style={{ padding: 12 }}>
        {busy ? "در حالِ ساخت…" : "ساختِ برنامهٔ تبلیغ ⇐"}
      </Button>
      <div className="mt-3 text-xs font-bold" style={{ color: "var(--text-3)" }}>
        بعد چه می‌شود
      </div>
      <div className="u3d-check mt-1">
        <div className="neutral">
          <i>۱</i>
          <span>برنامه (صحنه، حرکت، گفتار، دوربین) در چند ثانیه نوشته می‌شود.</span>
        </div>
        <div className="neutral">
          <i>۲</i>
          <span>در ویرایشگر می‌بینید و تغییر می‌دهید (پنج گام).</span>
        </div>
        <div className="neutral">
          <i>۳</i>
          <span>اول «انیمیک» (چند دقیقه)، بعد کیفیتِ بالاتر؛ ویدئو را دانلود می‌کنید.</span>
        </div>
      </div>
    </Card>
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="تبلیغِ تازه"
        subtitle="سه گام: محصول ⇐ مجری و صحنه ⇐ پیام و کارگردانی. فقط نامِ محصول لازم است؛ بقیه پیش‌فرضِ خوب دارد."
        actions={
          isAd ? (
            <Badge tone="ok">قالبِ آماده — بی‌نیاز به AI</Badge>
          ) : aiReady ? (
            <Badge tone="ok">کارگردانِ AI آماده</Badge>
          ) : (
            <Badge tone="warn">بدونِ کلیدِ AI ⇐ قالبِ آماده</Badge>
          )
        }
      />
      <ErrorBox message={error} />

      <form
        className="u3d-flow"
        onSubmit={(e) => {
          e.preventDefault();
          void go();
        }}
      >
        <div className="u3d-main">
          <Section n={1} title="محصول" help="نامِ محصول و شکلِ سه‌بعدی‌اش. شعار و قیمت روی برچسب و روی تصویر می‌نشینند؛ ویژگی‌ها به جمله‌های گفتار تبدیل می‌شوند.">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="نامِ محصول *">
                <Input id="u3d-product-name" value={productName} onChange={(e) => setProductName(e.target.value)} required placeholder="مثلاً عطرِ رز" />
              </Field>
              <Field label="برند">
                <Input value={brand} onChange={(e) => setBrand(e.target.value)} placeholder="مثلاً UpMarket" />
              </Field>
            </div>
            {fixedAsset ? (
              <Muted className="text-xs">
                این قالب شکلِ محصول را خودش می‌گذارد ({chosenTplMeta?.hint || chosenTplMeta?.fa}).
              </Muted>
            ) : (
              <div>
                <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                  شکلِ محصول
                </span>
                <Picker kind="product" list={cat.product.filter((p) => p.id !== "custom_model" && p.ai !== false)} value={product} onChange={setProduct} />
                {modelFile.path && <Muted className="mt-1 text-xs">مدلِ سه‌بعدیِ خودتان بارگذاری شده و به‌جای شکلِ آماده می‌نشیند.</Muted>}
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="شعار (روی برچسب)">
                <Input value={tagline} onChange={(e) => setTagline(e.target.value)} placeholder="رایحهٔ ماندگار" />
              </Field>
              <Field label="قیمت (اختیاری)">
                <Input value={price} onChange={(e) => setPrice(e.target.value)} placeholder="۸۹۰ هزار تومان" />
              </Field>
            </div>
            <Field label="ویژگی‌ها / توضیح" hint="هر ویژگی در یک خط؛ هر خط یک جملهٔ گفتار می‌شود">
              <TextArea
                rows={4}
                value={benefits}
                onChange={(e) => setBenefits(e.target.value)}
                placeholder={"مثلاً:\nرایحه‌ای گرم و ماندگار تا پایانِ روز\nشیشه‌ای زیبا، هدیه‌ای به‌یادماندنی"}
              />
            </Field>
            <Advanced title="تنظیماتِ پیشرفتهٔ محصول" hint="عکسِ برچسب، مدلِ سه‌بعدیِ خودتان، رنگ‌ها">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="عکس/لوگوی برچسب (اختیاری)" hint={labelFile.text}>
                  <input type="file" accept="image/*" className="u-input" onChange={(e) => void uploadTo(e.target.files?.[0], setLabelFile)} />
                </Field>
                <Field label="مدلِ سه‌بعدیِ خودِ محصول (اختیاری)" hint={modelFile.text}>
                  <input type="file" accept=".glb,.gltf,.obj,.fbx" className="u-input" onChange={(e) => void uploadTo(e.target.files?.[0], setModelFile)} />
                </Field>
              </div>
              <div className="flex flex-wrap gap-4">
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
            </Advanced>
          </Section>

          <Section n={2} title="مجری و صحنه" help="چه کسی و کجا محصول را معرفی می‌کند. صدا خودکار هم‌جنسِ مجری انتخاب می‌شود؛ قاب برای استوری عمودی است.">
            {isAd ? (
              <Muted className="text-xs">
                قالبِ «{chosenTplMeta?.fa}» مجری ندارد و صحنه (استیج)، نورِ استودیویی و دوربینِ سینمایی را خودش می‌چیند؛ بعد از ساخت در ویرایشگر همه‌چیز قابلِ تغییر است
                (نور، محیط، نگاهِ تصویر، حرکتِ دوربین).
              </Muted>
            ) : (
              <>
                <div>
                  <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                    مجری
                  </span>
                  <Picker kind="character" list={cat.character} value={character} onChange={setCharacter} />
                </div>
                <div>
                  <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                    محیط
                  </span>
                  <Picker kind="environment" list={cat.environment.filter((e) => e.ai !== false && !e.min_engine)} value={environment} onChange={setEnvironment} />
                </div>
              </>
            )}
            <div className={`grid gap-3 ${isAd ? "sm:grid-cols-1" : "sm:grid-cols-3"}`}>
              {!isAd && (
                <Field label="صدا">
                  <Select value={voice} onChange={(e) => setVoice(e.target.value)}>
                    {cat.voice.map((v) => (
                      <option key={v.id} value={v.id}>
                        {label(v)}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
              <Field label="قاب">
                <Select value={aspect} onChange={(e) => setAspect(e.target.value)}>
                  {Object.entries(ASPECT_FA).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </Select>
              </Field>
              {!isAd && (
                <Field label="لحن">
                  <Select value={tone} onChange={(e) => setTone(e.target.value)}>
                    <option value="گرم و صمیمی">گرم و صمیمی</option>
                    <option value="لوکس و آرام">لوکس و آرام</option>
                    <option value="پرانرژی و شاد">پرانرژی و شاد</option>
                    <option value="رسمی و مطمئن">رسمی و مطمئن</option>
                  </Select>
                </Field>
              )}
            </div>
          </Section>

          <Section n={3} title="پیام و کارگردانی" help="دعوت به خرید در پایانِ ویدئو می‌آید. با کلیدِ AI، کارگردان از درخواستِ آزادِ شما صحنه می‌نویسد؛ بی‌آن، قالبِ آماده.">
            <Field label="دعوت به خرید">
              <Input value={cta} onChange={(e) => setCta(e.target.value)} placeholder="همین حالا از آپ‌مارکت سفارش بدید!" />
            </Field>
            <Field label="درخواستِ آزاد برای کارگردانِ AI (اختیاری)">
              <TextArea
                rows={4}
                value={request}
                onChange={(e) => setRequest(e.target.value)}
                placeholder="مثلاً: یک خانم عطر را از روی میز بردارد، نزدیکِ صورتش نشان بدهد، کمی روی گردن بزند و با لبخند دعوت به خرید کند. ۱۲ ثانیه."
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="روش">
                <Select value={mode} onChange={(e) => setMode(e.target.value as "ai" | "template")}>
                  <option value="ai" disabled={!aiReady}>
                    کارگردانِ هوشِ مصنوعی
                  </option>
                  <option value="template">قالبِ آماده (بی‌AI)</option>
                </Select>
              </Field>
              <Field label="قالب (و پشتیبانِ AI)" hint={chosenTplMeta?.hint || "اگر AI نتواند، همین قالب ساخته می‌شود"}>
                <Select value={template} onChange={(e) => setTemplate(e.target.value)}>
                  <optgroup label="قالب‌های تبلیغاتیِ آماده (بی‌مجری، موتورِ ۱٫۳)">
                    {templates
                      .filter((t) => t.group === "ad")
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.fa}
                        </option>
                      ))}
                  </optgroup>
                  <optgroup label="با مجری">
                    {templates
                      .filter((t) => t.group !== "ad")
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.fa}
                        </option>
                      ))}
                  </optgroup>
                </Select>
              </Field>
            </div>
            {isAd && (tplInputs.includes("screens") || tplInputs.includes("logo") || tplInputs.includes("brand_colors")) && (
              <div className="space-y-3 rounded-lg p-3" style={{ border: "1px solid var(--border)" }}>
                <div className="text-sm font-bold" style={{ color: "var(--text)" }}>
                  ورودی‌های ویژهٔ این قالب
                </div>
                {tplInputs.includes("screens") && (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {screenFiles.map((s, i) => (
                      <Field key={i} label={`اسکرین‌شاتِ ${["اول", "دوم", "سوم", "چهارم"][i]}`} hint={s.text}>
                        <input
                          type="file"
                          accept="image/*"
                          className="u-input"
                          onChange={(e) => void uploadTo(e.target.files?.[0], (st) => setScreenFiles((arr) => arr.map((x, j) => (j === i ? st : x))))}
                        />
                      </Field>
                    ))}
                    <Muted className="text-xs sm:col-span-2">
                      اگر اسکرین‌شات ندهید، سه صفحهٔ نمونه با رنگ، نام، شعار و ویژگی‌هایی که نوشته‌اید ساخته می‌شود (ماکتِ گرافیکی، نه تصویرِ واقعیِ اپ).
                    </Muted>
                  </div>
                )}
                {tplInputs.includes("logo") && (
                  <Field label="لوگو (اختیاری)" hint={logoFile.ok ? logoFile.text : "اگر ندهید، نامِ برند به‌صورتِ حروفِ سه‌بعدی ساخته می‌شود"}>
                    <input type="file" accept="image/*" className="u-input" onChange={(e) => void uploadTo(e.target.files?.[0], setLogoFile)} />
                  </Field>
                )}
                {tplInputs.includes("brand_colors") && (
                  <div className="flex flex-wrap gap-4">
                    <Field label="رنگِ اصلیِ برند">
                      <input type="color" value={brandColor} onChange={(e) => setBrandColor(e.target.value)} className="u-input" style={{ width: 64, height: 38, padding: 2 }} />
                    </Field>
                    <Field label="رنگِ دومِ برند">
                      <input type="color" value={brandColor2} onChange={(e) => setBrandColor2(e.target.value)} className="u-input" style={{ width: 64, height: 38, padding: 2 }} />
                    </Field>
                  </div>
                )}
              </div>
            )}
            <Button type="submit" disabled={busy} className="w-full" style={{ padding: 12 }}>
              {busy ? "در حالِ ساخت…" : "ساختِ برنامهٔ تبلیغ ⇐"}
            </Button>
            <Muted className="text-xs">بعد از ساخت، صحنه را در ویرایشگر می‌بینید، تغییر می‌دهید و اول «انیمیک» (چند دقیقه) و بعد کیفیتِ بالاتر می‌گیرید.</Muted>
          </Section>
        </div>

        <aside className="u3d-aside">{summary}</aside>
      </form>
    </div>
  );
}
