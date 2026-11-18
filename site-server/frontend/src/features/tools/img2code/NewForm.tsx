import { DragEvent, useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Alert, Button, Card, ErrorBox, Field, Input, Select, fa } from "../../../components/ui";
import { Engine, Item, Lang, Mode, Options, i2cApi } from "./api";

type Tab = "upload" | "url";

/**
 * فرمِ «تبدیلِ تازه»: بارگذاریِ اسکرین‌شات یا نشانیِ صفحه + حالت (دقیق / واکنش‌گرا) + زبان.
 * فقط یک کارِ پس‌زمینه می‌سازد؛ پیشرفتش در کارتِ بالای تاریخچه می‌آید.
 */
export default function NewForm({ storeId, options, engine, onCreated }: { storeId: string; options: Options; engine: Engine; onCreated: (item: Item) => void }) {
  const [tab, setTab] = useState<Tab>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [width, setWidth] = useState(1280);
  const [domText, setDomText] = useState(true);
  const [mode, setMode] = useState<Mode>("responsive");
  const [lang, setLang] = useState<Lang>("auto");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const u = URL.createObjectURL(file);
    setPreview(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  function pick(f: File | undefined | null) {
    setError(null);
    if (!f) return;
    if (!/^image\/(png|jpe?g|webp)$/.test(f.type)) {
      setError("فقط تصویرِ PNG، JPG یا WebP پذیرفته می‌شود.");
      return;
    }
    if (f.size > options.limits.max_upload_mb * 1024 * 1024) {
      setError(`حجمِ فایل زیاد است؛ حداکثر ${fa(options.limits.max_upload_mb)} مگابایت.`);
      return;
    }
    setFile(f);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDrag(false);
    pick(e.dataTransfer.files?.[0]);
  }

  const canSubmit = !busy && engine.ready && (tab === "upload" ? !!file : url.trim().length > 3) && (tab === "upload" || engine.url_ok);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const item =
        tab === "upload" && file
          ? await i2cApi.createUpload(storeId, file, { mode, lang, title: title.trim() })
          : await i2cApi.createUrl(storeId, { url: url.trim(), mode, lang, width, dom_text: domText, title: title.trim() });
      setFile(null);
      setUrl("");
      setTitle("");
      onCreated(item);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="i2c-form" >
      <div data-testid="i2c-form">
        <div className="i2c-tabs" role="tablist" aria-label="منبعِ تصویر">
          <button type="button" role="tab" aria-selected={tab === "upload"} data-testid="i2c-tab-upload" className={`u-btn ${tab === "upload" ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setTab("upload")}>
            <Icon name="upload" size={15} /> بارگذاریِ تصویر
          </button>
          <button type="button" role="tab" aria-selected={tab === "url"} data-testid="i2c-tab-url" className={`u-btn ${tab === "url" ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setTab("url")}>
            <Icon name="link" size={15} /> نشانیِ صفحه
          </button>
        </div>

        {tab === "upload" ? (
          <div
            className={`i2c-drop ${drag ? "is-drag" : ""} ${file ? "has-file" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
            onClick={() => input.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
            data-testid="i2c-drop"
          >
            <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden data-testid="i2c-file" onChange={(e) => pick(e.target.files?.[0])} />
            {preview ? (
              <div className="i2c-drop-preview">
                <img src={preview} alt="پیش‌نمایشِ تصویرِ انتخاب‌شده" />
                <span>{file?.name} · {fa(Math.round((file?.size ?? 0) / 1024))} کیلوبایت — برای عوض‌کردن بزنید</span>
              </div>
            ) : (
              <div className="i2c-drop-empty">
                <Icon name="image" size={30} />
                <b>اسکرین‌شاتِ صفحه را این‌جا بیندازید یا بزنید و انتخاب کنید</b>
                <span>PNG، JPG یا WebP؛ تا {fa(options.limits.max_upload_mb)} مگابایت و {fa(options.limits.max_megapixels)} مگاپیکسل</span>
              </div>
            )}
          </div>
        ) : (
          <div className="i2c-url">
            <Field label="نشانیِ صفحه" hint="سرور با مرورگرِ بی‌سر از کلِ صفحه عکس می‌گیرد. فقط سایت‌های عمومیِ اینترنت (نه شبکهٔ داخلی).">
              <Input dir="ltr" inputMode="url" placeholder="https://example.com/" value={url} onChange={(e) => setUrl(e.target.value)} data-testid="i2c-url" />
            </Field>
            <div className="i2c-row">
              <Field label="پهنای مرورگر">
                <Select value={width} onChange={(e) => setWidth(Number(e.target.value))} data-testid="i2c-width">
                  {options.widths.map((w) => (
                    <option key={w.key} value={w.key}>{w.label}</option>
                  ))}
                </Select>
              </Field>
              <label className="i2c-check">
                <input type="checkbox" checked={domText} onChange={(e) => setDomText(e.target.checked)} data-testid="i2c-domtext" />
                <span>
                  <b>متن‌ها از خودِ صفحه خوانده شود (دقیق)</b>
                  <small>بدونِ OCR؛ فارسیِ درست و بدونِ غلطِ املایی</small>
                </span>
              </label>
            </div>
            {!engine.url_ok && <Alert tone="warn" title="گرفتنِ عکس از نشانی روی سرور آماده نیست">تصویرِ صفحه را خودتان بارگذاری کنید.</Alert>}
          </div>
        )}

        {tab === "upload" && (
          <div className="i2c-hint-url" data-testid="i2c-url-hint">
            <span>
              <b>برای متنِ دقیق، نشانیِ صفحه را بدهید.</b> متنِ تصویرِ بارگذاری‌شده با OCR خوانده می‌شود و در نوشته‌های ریزِ فارسی گاهی یک حرف را اشتباه می‌خواند (خط‌های مشکوک را در نتیجه با کادرِ زرد نشان می‌دهیم).
              با نشانی، نوشته‌ها مستقیم از خودِ صفحه برداشته می‌شود و غلطِ املایی ندارد.
            </span>
            <Button size="sm" variant="secondary" onClick={() => setTab("url")} data-testid="i2c-hint-url-btn">
              <Icon name="link" size={14} /> تبدیل با نشانیِ صفحه
            </Button>
          </div>
        )}

        <div className="i2c-opts">
          <fieldset className="i2c-modes">
            <legend>حالت</legend>
            {options.modes.map((m) => (
              <label key={m.key} className={`i2c-mode ${mode === m.key ? "is-on" : ""}`} data-testid={`i2c-mode-${m.key}`}>
                <input type="radio" name="i2c-mode" value={m.key} checked={mode === m.key} onChange={() => setMode(m.key)} />
                <span><b>{m.label}</b><small>{m.hint}</small></span>
              </label>
            ))}
          </fieldset>
          <div className="i2c-side">
            <Field label="زبانِ متن">
              <Select value={lang} onChange={(e) => setLang(e.target.value as Lang)} data-testid="i2c-lang">
                {options.langs.map((l) => (
                  <option key={l.key} value={l.key}>{l.label}</option>
                ))}
              </Select>
            </Field>
            <Field label="عنوان (اختیاری)">
              <Input value={title} maxLength={160} onChange={(e) => setTitle(e.target.value)} placeholder="مثلاً صفحهٔ فرودِ چغر" data-testid="i2c-title" />
            </Field>
          </div>
        </div>

        {!engine.ready && <Alert tone="bad" title="موتورِ تبدیل روی این سرور نصب نیست">{engine.messages[0]}</Alert>}
        {engine.ready && engine.messages.map((m) => (
          <Alert key={m} tone="warn">{m}</Alert>
        ))}
        <ErrorBox message={error} />
        <div className="i2c-actions">
          <Button disabled={!canSubmit} onClick={() => void submit()} data-testid="i2c-submit">
            {busy ? "در حال فرستادن…" : "شروعِ تبدیل"}
          </Button>
          <span className="i2c-note">تبدیل روی سرور و در پس‌زمینه انجام می‌شود (چند ثانیه تا یک دقیقه)؛ می‌توانید صفحه را ببندید.</span>
        </div>
      </div>
    </Card>
  );
}
