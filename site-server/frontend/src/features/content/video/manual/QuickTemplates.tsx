import { useState } from "react";

import { Spinner } from "../../../../components/ui";
import { toApi } from "./model";
import { DirectorStep, directorApply, soundError } from "./soundApi";
import type { SoundWiring } from "./SoundQuick";

/**
 * «قالب‌های آماده»: تیترِ شروع، کارتِ پایانی و ۹:۱۶‌کردنِ همهٔ قطعه‌ها — همان ابزارهایی که «کارگردان» به کار می‌برد، این‌جا یک‌کلیکی.
 * نتیجه یک گامِ برگشت (Ctrl+Z) است و کاملاً قابل‌ویرایش می‌ماند.
 */
export default function QuickTemplates({ storeId, sound }: { storeId: string; sound: SoundWiring }) {
  const [intro, setIntro] = useState("");
  const [cta, setCta] = useState("همین حالا سفارش بده");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function run(key: string, label: string, steps: DirectorStep[]) {
    if (busy) return;
    setBusy(key);
    setMsg(null);
    try {
      const res = await directorApply(storeId, sound.root, steps);
      const lines = res.results.map((r) => r.message || (r.ok ? "انجام شد." : "انجام نشد."));
      if (res.project && res.results.some((r) => r.ok)) {
        const next = res.project;
        sound.applyRoot(label, () => next);
      }
      setMsg({ ok: res.results.every((r) => r.ok), text: lines.join(" — ") });
    } catch (err) {
      setMsg({ ok: false, text: soundError(err) });
    } finally {
      setBusy(null);
    }
  }

  const disabled = !!busy || sound.nested || toApi(sound.root).tracks.every((t) => t.clips.length === 0);
  return (
    <div className="ws-card" data-testid="quick-templates">
      <div className="ws-card-title">قالب‌های آماده (شروع و پایان)</div>
      <p className="ws-hint">همان ابزارهای «کارگردان»، یک‌کلیکی روی پروژهٔ شما. بعدش هر چیز را می‌توانید دستی عوض کنید.</p>
      {sound.nested && <p className="ws-hint">اول از توالیِ تودرتو بیرون بیایید.</p>}
      <label className="ws-field"><span>تیترِ ثانیه‌های اول (قلاب)</span>
        <input className="u-input" value={intro} onChange={(e) => setIntro(e.target.value)} maxLength={60} placeholder="مثلاً: ۳۰٪ تخفیفِ ویژه" data-testid="qt-intro-text" />
      </label>
      <button type="button" className="ws-btn" disabled={disabled || !intro.trim()} data-testid="qt-intro"
        onClick={() => void run("intro", "تیترِ شروع", [{ tool: "add_title", params: { text: intro.trim(), at: 0.25, duration: 2.6, template: "title_big" } }])}>
        {busy === "intro" ? <Spinner size={12} /> : "🎬"} افزودنِ تیترِ شروع
      </button>
      <label className="ws-field"><span>جملهٔ کارتِ پایانی</span>
        <input className="u-input" value={cta} onChange={(e) => setCta(e.target.value)} maxLength={60} data-testid="qt-cta-text" />
      </label>
      <button type="button" className="ws-btn" disabled={disabled || !cta.trim()} data-testid="qt-outro"
        onClick={() => void run("outro", "کارتِ پایانی", [{ tool: "end_card", params: { text: cta.trim(), duration: 2.5 } }])}>
        {busy === "outro" ? <Spinner size={12} /> : "🏁"} افزودنِ کارتِ پایانی
      </button>
      <button type="button" className="ws-btn" disabled={disabled} data-testid="qt-reframe-all" title="همهٔ ویدیوها و عکس‌ها را به ۹:۱۶ می‌برد و دنبالِ سوژه می‌رود"
        onClick={() => void run("reframe", "۹:۱۶ خودکار برای همه", [{ tool: "reframe", params: { clip: "all", aspect: "9:16", follow: "auto" } }])}>
        {busy === "reframe" ? <Spinner size={12} /> : "📱"} همهٔ قطعه‌ها ۹:۱۶ (دنبالِ سوژه)
      </button>
      {msg && <p className={`ws-hint ${msg.ok ? "" : "is-warn"}`} data-testid="qt-result" style={{ color: msg.ok ? "var(--ok)" : "var(--warn)" }}>{msg.text}</p>}
    </div>
  );
}
