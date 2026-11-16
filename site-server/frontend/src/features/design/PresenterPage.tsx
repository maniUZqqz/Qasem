import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import Icon from "../../components/Icon";
import { Button, ErrorBox, Spinner } from "../../components/ui";
import { fa } from "./api";
import { useDocEditor } from "./hooks";
import { PageCanvas, useWidth } from "./parts";
import "./design.css";

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${fa(String(m).padStart(2, "0"))}:${fa(String(s).padStart(2, "0"))}`;
}

/** نمای ارائه‌دهنده: اسلایدِ جاری، اسلایدِ بعدی، یادداشتِ گوینده و زمان‌سنج؛ «?show=1» فقط اسلاید (برای نمایشگرِ مخاطب). */
export default function PresenterPage() {
  const { id = "", docId = "" } = useParams<{ id: string; docId: string }>();
  const [qs] = useSearchParams();
  const audience = qs.get("show") === "1";
  const nav = useNavigate();
  const ed = useDocEditor(id, Number(docId));
  const [i, setI] = useState(0);
  const [sec, setSec] = useState(0);
  const [running, setRunning] = useState(true);
  const stage = useRef<HTMLDivElement>(null);
  const small = useRef<HTMLDivElement>(null);
  const w = useWidth(stage, 360);
  const sw = useWidth(small, 160);
  const pages = ed.scene?.pages ?? [];
  const n = pages.length;
  const go = useCallback((d: number) => setI((x) => Math.max(0, Math.min(n - 1, x + d))), [n]);

  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setSec((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, [running]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft" || e.key === " " || e.key === "PageDown" || e.key === "ArrowDown") { e.preventDefault(); go(1); }          // راست‌به‌چپ: چپ = بعدی
      else if (e.key === "ArrowRight" || e.key === "PageUp" || e.key === "ArrowUp") { e.preventDefault(); go(-1); }
      else if (e.key === "Home") setI(0);
      else if (e.key === "End") setI(n - 1);
      else if (e.key === "Escape") nav(`/stores/${id}/design/deck/${docId}`);
      else if (e.key.toLowerCase() === "f") void document.documentElement.requestFullscreen?.().catch(() => undefined);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, n, nav, id, docId]);

  if (ed.error && !ed.scene) return <div className="ds-page"><ErrorBox message={ed.error} /></div>;
  if (!ed.doc || !ed.scene || !n) return <div className="ds-page"><Spinner /></div>;
  const cur = pages[Math.min(i, n - 1)];
  const next = pages[i + 1];
  const aspect = cur.w / cur.h;
  const stageW = audience ? Math.min(w, Math.floor((window.innerHeight - 40) * aspect)) : Math.min(w, 1000);

  return (
    <div className={`ds-present ${audience ? "is-audience" : ""}`}>
      <div className="ds-present-main" ref={stage}>
        <PageCanvas storeId={id} docId={ed.doc.id} page={cur} rev={ed.doc.rev} width={stageW} pointerMode="play" />
        <div className="ds-present-bar" aria-label="کنترل">
          <Button variant="secondary" size="sm" type="button" onClick={() => go(-1)} disabled={i <= 0} aria-label="قبلی"><Icon name="next" size={14} /></Button>
          <b>{fa(i + 1)} / {fa(n)}</b>
          <Button variant="secondary" size="sm" type="button" onClick={() => go(1)} disabled={i >= n - 1} aria-label="بعدی"><Icon name="back" size={14} /></Button>
          {!audience ? <Link to={`/stores/${id}/design/deck/${docId}/present?show=1`} target="_blank"><Button size="sm" type="button"><Icon name="play" size={14} /> پنجرهٔ نمایش (مخاطب)</Button></Link> : null}
          <Link to={`/stores/${id}/design/deck/${docId}`}><Button size="sm" variant="ghost" type="button">خروج (Esc)</Button></Link>
        </div>
      </div>
      {!audience ? (
        <aside className="ds-present-side">
          <div className="ds-timer"><span>{fmt(sec)}</span><Button size="sm" variant="secondary" type="button" onClick={() => setRunning(!running)}>{running ? "توقف" : "ادامه"}</Button><Button size="sm" variant="ghost" type="button" onClick={() => setSec(0)}>از نو</Button></div>
          <div className="ds-sub">اسلایدِ بعدی</div>
          <div ref={small}>{next ? <PageCanvas storeId={id} docId={ed.doc.id} page={next} rev={ed.doc.rev} width={Math.min(sw, 360)} pointerMode="play" /> : <p className="ds-muted">پایان</p>}</div>
          <div className="ds-sub">یادداشتِ گوینده</div>
          <div className="ds-notes">{cur.notes ? cur.notes.split("\n").map((l, k) => <p key={k}>{l}</p>) : <p className="ds-muted">برای این اسلاید یادداشتی نیست.</p>}</div>
          <p className="ds-muted">کلیدها: ← بعدی، → قبلی، فاصله بعدی، F تمام‌صفحه، Esc خروج</p>
        </aside>
      ) : null}
    </div>
  );
}
