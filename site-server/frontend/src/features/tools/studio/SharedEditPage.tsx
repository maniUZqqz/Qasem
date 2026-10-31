import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Button, Card, ErrorBox } from "../../../components/ui";
import { api, pUrl, studioError } from "./api";
import AiBox from "./AiBox";
import { CodeArea, docHtml, Loading, Mono, PreviewFrame, SectionHead } from "./common";
import { useProject } from "./shell";
import type { SharedKind, SharedPart, SharedResp } from "./types";

const PLACEHOLDER: Record<SharedKind, string> = {
  header: "مثلاً: یک نوارِ بالای هدر با «ارسالِ رایگان برای خریدِ بالای ۵۰۰ هزار تومان» اضافه کن",
  footer: "مثلاً: سه ستون بساز: دربارهٔ ما، لینک‌ها، نماد اعتماد؛ و آیکونِ اینستاگرام",
  base_css: "مثلاً: رنگ‌ها را گرم‌تر کن، گوشه‌ها گردتر و سایهٔ کارت‌ها نرم‌تر",
};

const SAMPLE =
  '<section class="section"><div class="wrap"><h1>نمونهٔ بدنهٔ صفحه</h1><p>محتوای صفحه این‌جا می‌آید.</p><a class="btn" href="#">یک دکمه</a></div></section>';

/** هدر / فوتر / CSSِ مشترک */
export default function SharedEditPage() {
  const { slug, notify } = useProject();
  const { kind = "header" } = useParams<{ kind: string }>();
  const [data, setData] = useState<SharedResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [html, setHtml] = useState("");

  useEffect(() => {
    setData(null);
    api
      .get<SharedResp>(`/studio/projects/${slug}/shared/${kind}/`)
      .then((r) => {
        setData(r.data);
        setContent(r.data.part.content);
      })
      .catch((err) => setError(studioError(err)));
  }, [slug, kind]);

  useEffect(() => {
    if (!data) return;
    const t = window.setTimeout(() => {
      const v = content.trim();
      const sh = { ...data.shared };
      if (kind === "header" && v) sh.header = v;
      if (kind === "footer" && v) sh.footer = v;
      if (kind === "base_css" && v) sh.base_css = v;
      setHtml(docHtml(sh, SAMPLE, "", "فروشگاه"));
    }, 250);
    return () => window.clearTimeout(t);
  }, [data, content, kind]);

  if (!data) return <Loading error={error} />;
  const part = data.part;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data: d } = await api.put<{ part: SharedPart; message: string }>(`/studio/projects/${slug}/shared/${kind}/`, { content });
      setData({ ...data!, part: d.part });
      notify(d.message);
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
        <Link to={pUrl(slug, "frontend")} className="u-back">
          <Icon name="back" size={14} />
          فرانت
        </Link>
        <span>›</span>
        <b style={{ color: "var(--text)" }}>{part.kind_display}</b>
      </div>

      <Alert
        tone="warn"
        action={
          kind === "header" || kind === "footer" ? (
            <Link to={pUrl(slug, `builder/${kind}`)} className="no-underline">
              <Button type="button" size="sm">ویرایشِ دیداری</Button>
            </Link>
          ) : undefined
        }
      >
        حالتِ پیشرفته: این بخش روی <b>همهٔ</b> صفحه‌ها اثر می‌گذارد. خالی بگذاری، پیش‌فرضِ استودیو استفاده می‌شود.
        {(kind === "header" || kind === "footer") && " اگر این بخش را در ویرایشگرِ دیداری ساخته‌ای و این‌جا کدش را عوض کنی، قسمت‌هایی که قابلِ تشخیص نباشند در ویرایشگر به «کدِ سفارشی» تبدیل می‌شوند؛ چیزی از دست نمی‌رود."}
      </Alert>

      <AiBox
        slug={slug}
        endpoint={`ai/shared/${kind}/`}
        title={`${part.kind_display} را با هوشِ مصنوعی عوض کن`}
        placeholder={PLACEHOLDER[part.kind] ?? ""}
        note="فقط همین بخش عوض می‌شود؛ قبل از اعمال Diff را می‌بینی."
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <form onSubmit={save} className="space-y-3">
            <SectionHead title={part.kind_display} hint={<>⇒ <Mono>{data.target_file}</Mono></>} />
            <ErrorBox message={error} />
            <CodeArea value={content} onChange={setContent} minHeight={420} placeholder={data.placeholder} />
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={busy}>
                {busy ? "…" : "ذخیره"}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setContent(data.default_content)}>
                پیش‌فرض را بیاور
              </Button>
              <Link to={pUrl(slug, "frontend")} className="no-underline">
                <Button type="button" variant="ghost">بازگشت</Button>
              </Link>
            </div>
          </form>
        </Card>
        <Card className="self-start lg:sticky lg:top-4">
          <SectionHead title="پیش‌نمایش" />
          <PreviewFrame html={html} height={520} />
        </Card>
      </div>
    </div>
  );
}
