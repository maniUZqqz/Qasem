import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Alert, Button, Card, ErrorBox } from "../../../components/ui";
import { api, pUrl, studioError } from "./api";
import { Loading, SectionHead } from "./common";
import { useProject } from "./shell";

type ItemT = { id: string; kind: "text" | "image"; value: string };
type Resp = { title: string; imported: boolean; hash: string; items: ItemT[]; preview: string; css: string; tags: number };

const FRAME_CSS = `
  body{margin:0;padding:16px;font-family:Vazirmatn,Tahoma,sans-serif;line-height:1.9;direction:rtl;color:#111;background:#fff}
  img{max-width:100%;height:auto}
  [data-te]{outline:1px dashed #8b7bff;outline-offset:2px;border-radius:3px;cursor:text;background:#8b7bff14}
  [data-te]:focus{outline:2px solid #6d5cff;background:#8b7bff2b}
  [data-te].changed{outline-color:#10b981;background:#10b98124}
  [data-te-img]{outline:2px dashed #8b7bff;outline-offset:2px;cursor:pointer}
  [data-te-img].changed{outline-color:#10b981}
  a{pointer-events:none}
  a [data-te]{pointer-events:auto}
`;

/**
 * ویرایشِ در جای متن و عکسِ قالب‌های کدی (پروژهٔ واردشده و قالبِ ویوها).
 * فقط متنِ ساده و آدرسِ ثابتِ عکس عوض می‌شود؛ سرور می‌سنجد که تگ‌های قالب بایت‌به‌بایت بمانند.
 * iframe اجازهٔ اجرای اسکریپت ندارد.
 */
export default function QuickEditPage() {
  const { slug, notify } = useProject();
  const { kind = "view", pk = "" } = useParams<{ kind: string; pk: string }>();
  const [data, setData] = useState<Resp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [count, setCount] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);
  const edits = useRef<Record<string, string>>({});
  const imgInput = useRef<HTMLInputElement>(null);
  const imgTarget = useRef<HTMLImageElement | null>(null);
  const url = `/studio/projects/${slug}/quick-edit/${kind}/${pk}/`;
  const backTo = kind === "page" ? pUrl(slug, `page/${pk}`) : pUrl(slug, `view/${pk}`);

  useEffect(() => {
    api
      .get<Resp>(url)
      .then((r) => setData(r.data))
      .catch((err) => setError(studioError(err)));
  }, [url]);

  const wire = useCallback(() => {
    const doc = frame.current?.contentDocument;
    if (!doc || !data) return;
    const byId = new Map(data.items.map((x) => [x.id, x]));
    doc.querySelectorAll<HTMLElement>("[data-te]").forEach((el) => {
      const id = el.dataset.te ?? "";
      el.contentEditable = "plaintext-only";
      if (el.contentEditable !== "plaintext-only") el.contentEditable = "true";
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          el.blur();
        }
      });
      el.addEventListener("input", () => {
        const value = (el.textContent ?? "").replace(/\s+/g, " ").trim();
        if (value !== byId.get(id)?.value) {
          edits.current[id] = value;
          el.classList.add("changed");
        } else {
          delete edits.current[id];
          el.classList.remove("changed");
        }
        setCount(Object.keys(edits.current).length);
      });
    });
    doc.querySelectorAll<HTMLImageElement>("img[data-te-img]").forEach((img) => {
      img.addEventListener("click", (e) => {
        e.preventDefault();
        imgTarget.current = img;
        imgInput.current?.click();
      });
    });
    doc.addEventListener("click", (e) => {
      const a = (e.target as Element)?.closest?.("a");
      if (a) e.preventDefault();
    });
    doc.addEventListener("submit", (e) => e.preventDefault());
  }, [data]);

  async function pickImage(file: File | undefined) {
    const img = imgTarget.current;
    if (!file || !img) return;
    const form = new FormData();
    form.append("file", file);
    setError(null);
    try {
      const { data: d } = await api.post<{ url: string; preview: string }>(`/studio/projects/${slug}/quick-edit/upload/`, form);
      edits.current[img.dataset.teImg ?? ""] = d.url;
      img.src = d.preview;
      img.classList.add("changed");
      setCount(Object.keys(edits.current).length);
    } catch (err) {
      setError(studioError(err));
    }
  }

  async function save() {
    if (!data) return;
    setBusy(true);
    setError(null);
    try {
      const { data: d } = await api.post<Resp>(url, { hash: data.hash, edits: edits.current });
      edits.current = {};
      setCount(0);
      setData(d);
      notify("ذخیره شد. برای دیدن روی سایت، پیش‌نمایش یا انتشار را بزن.");
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <Loading error={error} />;
  const texts = data.items.filter((x) => x.kind === "text").length;
  const images = data.items.filter((x) => x.kind === "image").length;
  const srcDoc = `<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>${data.css.replace(/<\//g, "<\\/")}</style><style>${FRAME_CSS}</style></head><body>${data.preview}</body></html>`;

  return (
    <Card>
      <div className="space-y-3" data-testid="quick-edit">
        <SectionHead title={`ویرایشِ متن و عکس: ${data.title}`} hint="روی هر متنی که نقطه‌چین دارد کلیک کن و بنویس. روی عکسِ نقطه‌چین کلیک کن تا عوضش کنی." />
        <Alert tone="info">
          این نمای ساده است: جاهایی که از داده می‌آیند با «…» نشان داده می‌شوند و بخش‌های شرطی همه با هم دیده می‌شوند. کدهای این قالب ({data.tags.toLocaleString("fa-IR")} تگ) دست نمی‌خورند.
          {data.imported && " عکسِ تازه در پوشهٔ static/site-media ِ پروژه ذخیره می‌شود؛ اگر پروژه این پوشه را سرو نمی‌کند، روی سایت دیده نمی‌شود."}
        </Alert>
        <ErrorBox message={error} />
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" disabled={busy || count === 0} data-testid="quick-save" onClick={() => void save()}>
            {busy ? "…" : count ? `ذخیرهٔ ${count.toLocaleString("fa-IR")} تغییر` : "تغییری نیست"}
          </Button>
          <Link to={backTo} className="no-underline">
            <Button type="button" variant="ghost">بازگشت به حالتِ کد</Button>
          </Link>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            {texts.toLocaleString("fa-IR")} متن و {images.toLocaleString("fa-IR")} عکس قابلِ ویرایش است
          </span>
        </div>
        <input ref={imgInput} type="file" accept="image/*" hidden onChange={(e) => void pickImage(e.target.files?.[0])} />
        <iframe
          key={data.hash}
          ref={frame}
          title="ویرایشِ قالب"
          sandbox="allow-same-origin"
          srcDoc={srcDoc}
          onLoad={wire}
          style={{ width: "100%", height: 620, border: "1px solid var(--line)", borderRadius: 12, background: "#fff" }}
        />
      </div>
    </Card>
  );
}
