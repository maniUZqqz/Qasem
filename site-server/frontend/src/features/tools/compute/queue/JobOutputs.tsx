import { useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import Icon from "../../../../components/Icon";
import { Button, Spinner } from "../../../../components/ui";
import type { QueueOutput } from "./model";

/**
 * خروجیِ یک کارِ پردازشی در جزئیاتش (۱۴۰۵/۰۸/۲۱، خواستهٔ مالک: «هر پردازش انجام شد خروجی را در جزئیاتش بشود باز کرد و دید»).
 * فایل‌ها با همان ورودِ پنل (JWT) گرفته می‌شوند، نه با نشانیِ خام: عکس و متن خودشان باز می‌شوند؛ ویدیو و صدا با یک کلیک
 * (ممکن است بزرگ باشند). خروجیِ Ollama (ollama.json) به‌جای JSON ِ خام، متنِ جواب را نشان می‌دهد.
 */

const MAX_TEXT = 20000;

function apiPath(url: string): string {
  return url.replace(/^\/api\/v1/, "");
}

function humanSize(n?: number | null): string {
  if (!n || n <= 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** JSON ِ Ollama ⇒ متنِ جواب؛ JSON ِ دیگر ⇒ مرتب؛ بقیه همان‌طور */
function readable(name: string, raw: string): string {
  if (name.toLowerCase().endsWith(".json")) {
    try {
      const o = JSON.parse(raw);
      const t = o?.response || o?.message?.content || o?.thinking || o?.message?.thinking;
      if (typeof t === "string" && t.trim()) return t.trim();
      return JSON.stringify(o, null, 2);
    } catch {
      /* not JSON */
    }
  }
  return raw;
}

async function download(out: QueueOutput) {
  const { data } = await api.get<Blob>(apiPath(out.url), { responseType: "blob" });
  const href = URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = href;
  a.download = out.name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 30000);
}

function OutputView({ out }: { out: QueueOutput }) {
  const auto = out.media === "image" || out.media === "text";
  const [show, setShow] = useState(auto);
  const [src, setSrc] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [dlErr, setDlErr] = useState(false);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    if (!show || out.media === "file") return;
    let alive = true;
    api
      .get<Blob>(apiPath(out.url), { responseType: "blob" })
      .then(async ({ data }) => {
        if (!alive) return;
        if (out.media === "text") {
          const raw = await data.text();
          if (alive) setText(readable(out.name, raw).slice(0, MAX_TEXT));
        } else {
          urlRef.current = URL.createObjectURL(data);
          setSrc(urlRef.current);
        }
      })
      .catch((e) => alive && setErr(errorMessage(e)));
    return () => {
      alive = false;
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, [show, out.url, out.media, out.name]);

  const loading = show && !err && !src && text === null && out.media !== "file";

  return (
    <div className="nmq-out">
      <div className="nmq-out-head">
        <span dir="ltr" className="nmq-mono">
          {out.name}
        </span>
        {humanSize(out.size) && <span className="nmq-out-size">{humanSize(out.size)}</span>}
        <span className="flex-1" />
        {!show && out.media !== "file" && (
          <Button size="sm" variant="secondary" onClick={() => setShow(true)}>
            <Icon name="play" size={13} /> {out.media === "video" ? "نمایشِ ویدیو" : out.media === "audio" ? "پخشِ صدا" : "نمایش"}
          </Button>
        )}
        <Button
          size="sm"
          variant={dlErr ? "danger" : "ghost"}
          onClick={() => void download(out).catch(() => setDlErr(true))}
          title={dlErr ? "دانلود نشد — دوباره بزنید" : "دانلود"}
        >
          <Icon name="download" size={13} /> دانلود
        </Button>
      </div>
      {loading && <Spinner size={16} />}
      {err && <div className="nmq-note">باز نشد: {err}</div>}
      {src && out.media === "image" && <img src={src} alt={out.name} className="nmq-out-img" />}
      {src && out.media === "video" && <video src={src} controls className="nmq-out-media" />}
      {src && out.media === "audio" && <audio src={src} controls className="nmq-out-audio" />}
      {text !== null && (
        <pre className="nmq-io" dir="auto">
          {text || "(خالی)"}
        </pre>
      )}
    </div>
  );
}

export default function JobOutputs({ outputs }: { outputs: QueueOutput[] }) {
  return (
    <div>
      <div className="nmq-detail-head">
        <b>خروجی ({outputs.length})</b>
      </div>
      <div className="nmq-outs">
        {outputs.map((o) => (
          <OutputView key={o.url} out={o} />
        ))}
      </div>
    </div>
  );
}
