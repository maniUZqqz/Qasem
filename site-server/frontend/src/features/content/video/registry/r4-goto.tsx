import { useState } from "react";

import { fa } from "../../../../components/ui";
import { projectLength, timecode } from "../manual/model";
import { parseTime } from "../manual/r4ops";
import type { PanelProps } from "./types";

/** رفتن به یک زمانِ دقیق: «۱:۲۳»، «۰:۰۵»، «۸۳» (ثانیه) یا «۱:۰۲:۰۳» */
export default function GotoPanel({ api, onClose }: PanelProps) {
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const len = projectLength(api.project);
  const go = () => {
    const v = parseTime(text);
    if (v === null) {
      setErr("زمان خوانده نشد؛ مثلاً ۱:۲۳ یا ۸۳ (ثانیه).");
      return;
    }
    api.seek(v);
    setErr(null);
    onClose();
  };
  return (
    <div data-testid="goto-panel">
      <p className="ws-hint">الان: <b dir="ltr">{timecode(api.time, api.fps)}</b> · طولِ پروژه: <b dir="ltr">{timecode(len, api.fps)}</b></p>
      <div className="mk-top">
        <input className="u-input" dir="ltr" autoFocus value={text} placeholder="مثلاً 1:23 یا 83" aria-label="زمان" data-testid="goto-input"
          onChange={(e) => { setText(e.target.value); setErr(null); }} onKeyDown={(e) => { if (e.key === "Enter") go(); }} />
        <button type="button" className="ws-btn primary" onClick={go} data-testid="goto-go">برو</button>
      </div>
      {err && <p className="ws-hint" role="alert" data-testid="goto-error">{err}</p>}
      <p className="ws-hint">ثانیه ({fa(83)}) یا دقیقه:ثانیه ({fa("1:23")}) یا ساعت:دقیقه:ثانیه؛ ارقامِ فارسی هم درست است.</p>
    </div>
  );
}
