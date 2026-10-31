import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Button, Card, ErrorBox, Input } from "../../../components/ui";
import { api, pUrl, studioError } from "./api";
import AiBox from "./AiBox";
import { Check, CodeArea, docHtml, Help, Loading, Mono, PreviewFrame, SectionHead, stripTemplate } from "./common";
import { useProject } from "./shell";
import type { PageResp, PageT } from "./types";

/** ویرایشِ یک صفحه (بدنه + CSS) یا یک قالبِ واردشده (کلِ فایل) */
export default function PageEditPage() {
  const { slug, notify } = useProject();
  const { pk = "" } = useParams<{ pk: string }>();
  const [data, setData] = useState<PageResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [css, setCss] = useState("");
  const [inMenu, setInMenu] = useState(true);
  const [busy, setBusy] = useState(false);
  const [html, setHtml] = useState("");

  useEffect(() => {
    api
      .get<PageResp>(`/studio/projects/${slug}/pages/${pk}/`)
      .then((r) => {
        setData(r.data);
        setTitle(r.data.page.title);
        setBody(r.data.page.body_html ?? "");
        setCss(r.data.page.css ?? "");
        setInMenu(r.data.page.in_menu);
      })
      .catch((err) => setError(studioError(err)));
  }, [slug, pk]);

  useEffect(() => {
    if (!data) return;
    const imported = data.page.is_imported;
    const t = window.setTimeout(() => setHtml(imported ? stripTemplate(body) : docHtml(data.shared, body, css)), 250);
    return () => window.clearTimeout(t);
  }, [data, body, css]);

  if (!data) return <Loading error={error} />;
  const page = data.page;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (page.has_design && !page.is_imported) {
        const { data: chk } = await api.post<{ has_design: boolean; custom: number; new_custom: number; dirty: boolean }>(
          `/studio/projects/${slug}/builder/pages/${pk}/roundtrip-check/`,
          { body_html: body, css },
        );
        const parts: string[] = [];
        if (chk.new_custom > 0) {
          parts.push(`با این تغییر ${chk.new_custom} بخش در ویرایشگرِ دیداری به «کدِ سفارشی» تبدیل می‌شود: چیزی از دست نمی‌رود ولی آن بخش دیگر با کلیک و تنظیمات ویرایش نمی‌شود.`);
        }
        if (chk.dirty) parts.push("این صفحه در ویرایشگرِ دیداری پیش‌نویسِ منتشرنشده دارد؛ با این ذخیره آن پیش‌نویس به «نسخه‌ها» می‌رود.");
        if (parts.length && !window.confirm(`${parts.join("\n\n")}\n\nذخیره شود؟`)) {
          setBusy(false);
          return;
        }
      }
      const { data: d } = await api.put<{ page: PageT; message: string }>(`/studio/projects/${slug}/pages/${pk}/`, {
        title,
        body_html: body,
        css,
        in_menu: inMenu,
      });
      setData({ ...data!, page: d.page, drift: false });
      notify(d.message);
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  async function reloadFromDisk() {
    try {
      const { data: d } = await api.post<{ page: PageT; message: string }>(`/studio/projects/${slug}/pages/${pk}/reload/`, {});
      setBody(d.page.body_html ?? "");
      setData({ ...data!, page: d.page, drift: false });
      if (d.message) notify(d.message);
    } catch (err) {
      notify(studioError(err), "bad");
    }
  }

  return (
    <form onSubmit={save} className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
        <Link to={pUrl(slug, "frontend")} className="u-back">
          <Icon name="back" size={14} />
          فرانت
        </Link>
        <span>›</span>
        <b style={{ color: "var(--text)" }}>{page.title}</b>
      </div>

      {page.is_imported && (
        <Alert
          tone="info"
          action={
            <Link to={pUrl(slug, `quick-edit/page/${pk}`)} className="no-underline">
              <Button type="button" size="sm" data-testid="quick-edit-link">ویرایشِ متن و عکس</Button>
            </Link>
          }
        >
          این قالب کد است. متن‌ها و عکس‌هایش را می‌توانی بی‌دست‌زدن به کدها مستقیم ویرایش کنی.
        </Alert>
      )}

      {page.is_imported && data.drift && (
        <Alert
          tone="warn"
          action={
            <Button type="button" size="sm" onClick={reloadFromDisk}>
              نسخهٔ دیسک را بیاور
            </Button>
          }
        >
          این فایل بیرون از استودیو (روی دیسک) عوض شده و با نسخهٔ این‌جا فرق دارد. اگر همین‌جا ویرایش کنی، «تولیدِ کد» برای
          امنیت رویش نمی‌نویسد.
        </Alert>
      )}

      {!page.is_imported && (
        <Alert
          tone={page.has_design ? "warn" : "info"}
          action={
            <Link to={pUrl(slug, `builder/page/${page.id}`)} className="no-underline">
              <Button type="button" size="sm">بازکردن در ویرایشگرِ دیداری</Button>
            </Link>
          }
        >
          {page.has_design
            ? "حالتِ پیشرفته: این صفحه با ویرایشگرِ دیداری ساخته شده. اگر کد را این‌جا عوض کنی، بخش‌هایی که قابلِ تشخیص نباشند در ویرایشگر به «کدِ سفارشی» تبدیل می‌شوند."
            : "حالتِ پیشرفته: ویرایشِ مستقیمِ کدِ این صفحه. اگر با کد کار نداری، از ویرایشگرِ دیداری استفاده کن."}
        </Alert>
      )}

      <AiBox
        slug={slug}
        endpoint={`ai/page/${page.id}/`}
        title={page.is_imported ? "این قالب را با هوشِ مصنوعی ویرایش کن" : "بدنهٔ همین صفحه را با هوشِ مصنوعی ویرایش کن"}
        placeholder={
          page.is_imported
            ? "مثلاً: دکمهٔ خرید را بزرگ‌تر و سبز کن و یک بخشِ «سؤال‌های پرتکرار» زیرِ محصول اضافه کن"
            : "مثلاً: بخشِ هیرو را دو ستونه کن، سمتِ چپ یک تصویر و سمتِ راست تیتر و دکمه؛ یک بخشِ «چرا ما» با سه کارت اضافه کن"
        }
        note={
          page.is_imported
            ? "فقط همین فایل عوض می‌شود. قبل از اعمال، Diff را می‌بینی."
            : "فقط بدنه و CSSِ همین صفحه — هدر، فوتر، صفحه‌های دیگر و بک‌اند دست نمی‌خورند. قبل از اعمال، Diff را می‌بینی."
        }
        withSection={!page.is_imported}
        recent={data.recent}
      />

      <ErrorBox message={error} />

      {page.is_imported ? (
        <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <Card>
            <SectionHead
              title={<Mono className="text-sm">{page.file_path}</Mono>}
              action={
                <Button type="submit" size="sm" disabled={busy}>
                  {busy ? "…" : "ذخیره"}
                </Button>
              }
            />
            <CodeArea value={body} onChange={setBody} minHeight="calc(100vh - 360px)" />
            <Help>کلِ فایلِ قالب است (همراهِ extends و block ها). با «تولیدِ کد» در پروژه نوشته می‌شود و یک نسخه در تاریخچه ثبت می‌شود.</Help>
          </Card>
          <Card className="self-start lg:sticky lg:top-4">
            <SectionHead title="پیش‌نمایشِ تقریبی" hint="بی‌دادهٔ جنگو؛ ظاهرِ دقیق در «پیش‌نمایشِ زنده»" />
            <PreviewFrame html={html} height="calc(100vh - 330px)" />
          </Card>
        </div>
      ) : (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-3">
              <div className="w-72 max-w-full">
                <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="عنوانِ صفحه" />
              </div>
              <Mono>/{page.slug}</Mono>
              <span className="text-sm" style={{ color: "var(--text-3)" }}>
                ⇒ <Mono>templates/{page.template_path}</Mono>
              </span>
              <Check label="در منو" checked={inMenu} onChange={setInMenu} />
              <div className="ms-auto flex gap-2">
                <Link to={pUrl(slug, "frontend")} className="no-underline">
                  <Button type="button" variant="ghost">بازگشت</Button>
                </Link>
                <Button type="submit" disabled={busy}>
                  {busy ? "…" : "ذخیره"}
                </Button>
              </div>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-4">
              <Card>
                <SectionHead
                  title="بدنهٔ صفحه"
                  hint={
                    <>
                      داخلِ <Mono>{"{% block content %}"}</Mono> · قالبِ جنگو مجاز است
                    </>
                  }
                />
                <CodeArea value={body} onChange={setBody} minHeight={360} />
                <Help>
                  متغیرها: <Mono>products</Mono>، <Mono>categories</Mono> (صفحه‌های کاتالوگ)، <Mono>cart</Mono>، <Mono>SITE_TITLE</Mono>،{" "}
                  <Mono>MENU</Mono>.
                </Help>
              </Card>
              <Card>
                <SectionHead title="CSSِ همین صفحه" hint={<Mono>static/css/pages/{page.css_name}.css</Mono>} />
                <CodeArea value={css} onChange={setCss} minHeight={160} />
              </Card>
            </div>
            <Card className="self-start lg:sticky lg:top-4">
              <SectionHead title="پیش‌نمایشِ بدنه" hint="با هدر/فوتر و CSSِ مشترکِ پروژه · بی‌داده" />
              <PreviewFrame html={html} height={560} address={`/${page.slug}`} />
              <Help>داده‌های واقعی (محصول‌ها…) در «پیش‌نمایشِ زنده» می‌آیند.</Help>
            </Card>
          </div>
        </>
      )}
    </form>
  );
}
