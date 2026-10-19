import { useEffect, useRef, useState } from "react";

import { openTool } from "../../../../components/Layout";
import { Badge, Button, Field, Table, TextArea } from "../../../../components/ui";
import { fa } from "../api";
import { ButtonTabs, Muted } from "../shared";
import type { Issue, SceneDoc, Version } from "../types";
import { curlCode, pythonCode } from "./model";

/** کارتِ زیرِ خطِ زمان: ایرادها، ویرایش با AI، کد (JSON / Python / API)، نسخه‌ها. */

export function IssuesPanel({ issues, onPick }: { issues: Issue[]; onPick: (path: string) => void }) {
  if (!issues.length) return <ul className="u3d-issues"><li className="ok">صحنه معتبر است ✓ — آمادهٔ رندر.</li></ul>;
  return (
    <ul className="u3d-issues">
      {issues.map((i, k) => (
        <li key={k} className={`${i.level} clickable`} onClick={() => onPick(i.path)}>
          {i.message} <span className="u3d-mono text-xs" style={{ color: "var(--text-3)" }}>{i.path}</span>
        </li>
      ))}
    </ul>
  );
}

export function IssueCount({ issues }: { issues: Issue[] }) {
  const e = issues.filter((i) => i.level === "error").length;
  const w = issues.filter((i) => i.level === "warning").length;
  return <Badge tone={e ? "bad" : w ? "warn" : "ok"}>{e ? `${fa(e)} خطا` : w ? `${fa(w)} هشدار` : "بی‌ایراد"}</Badge>;
}

export type AiOut = { version?: number; diff?: string[]; repairs?: string[]; error?: string } | null;

export function AiPanel({
  aiReady,
  busy,
  out,
  onEdit,
  onReplan,
}: {
  aiReady: boolean;
  busy: boolean;
  out: AiOut;
  onEdit: (instruction: string) => void;
  onReplan: () => void;
}) {
  const [ins, setIns] = useState("");
  return (
    <div className="space-y-3">
      <Field label="چه چیزی عوض شود؟">
        <TextArea
          rows={3}
          value={ins}
          onChange={(e) => setIns(e.target.value)}
          placeholder="مثلاً: شاتِ دوم نمای نزدیکِ چهره باشد، جملهٔ آخر کوتاه‌تر و پرانرژی‌تر شود، و در پایان دست تکان بدهد."
        />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={!aiReady || busy || !ins.trim()} onClick={() => onEdit(ins.trim())}>
          {busy ? "کارگردان در حالِ ویرایش…" : "اعمالِ ویرایش"}
        </Button>
        <Button variant="secondary" disabled={!aiReady || busy} onClick={onReplan}>
          برنامه‌ریزیِ دوباره از اول
        </Button>
        {!aiReady && (
          <span className="text-xs" style={{ color: "var(--warn)" }}>
            کلیدِ AI در{" "}
            <button type="button" className="underline" onClick={() => openTool("/admin/up3d/aisettings/1/change/")} style={{ color: "var(--brand-strong)" }}>
              تنظیمات
            </button>{" "}
            وارد نشده
          </span>
        )}
      </div>
      {out && (
        <div className="text-sm" style={{ color: "var(--text-2)" }}>
          {out.error ? (
            <span style={{ color: "var(--bad)" }}>{out.error}</span>
          ) : (
            <>
              <b style={{ color: "var(--ok)" }}>نسخهٔ {fa(out.version ?? 0)} ساخته شد.</b>
              <ul style={{ listStyle: "disc", paddingInlineStart: "1.3em" }}>
                {(out.diff || []).map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
              {out.repairs && out.repairs.length > 0 && (
                <Muted className="text-xs">ترمیم‌ها: {out.repairs.join("، ")}</Muted>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

type CodeTab = "json" | "py" | "api";

export function CodePanel({ doc, pid, origin, onApplyJson }: { doc: SceneDoc; pid: number; origin: string; onApplyJson: (text: string) => void }) {
  const [tab, setTab] = useState<CodeTab>("json");
  const [text, setText] = useState(() => JSON.stringify(doc, null, 1));
  const ref = useRef<HTMLTextAreaElement>(null);

  // سندِ تازه (از خطِ زمان، AI، نسخه) به متن می‌آید مگر کاربر همین حالا داخلش می‌نویسد
  useEffect(() => {
    if (document.activeElement !== ref.current) setText(JSON.stringify(doc, null, 1));
  }, [doc]);

  return (
    <div>
      <ButtonTabs<CodeTab>
        tabs={[
          { id: "json", label: "سندِ صحنه (JSON)" },
          { id: "py", label: "Python SDK" },
          { id: "api", label: "API (curl)" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "json" && (
        <>
          <textarea ref={ref} className="u-input u3d-code-ed" spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="secondary" onClick={() => onApplyJson(text)}>
              اعمالِ JSON روی ویرایشگر
            </Button>
            <Muted className="text-xs">همان سندی که AI و ویرایشگر می‌سازند؛ قالب در «راهنما».</Muted>
          </div>
        </>
      )}
      {tab === "py" && <pre className="u3d-pre">{pythonCode(doc, origin)}</pre>}
      {tab === "api" && <pre className="u3d-pre">{curlCode(pid, origin)}</pre>}
    </div>
  );
}

export function VersionsTable({ versions, current, onRestore }: { versions: Version[]; current: number | null; onRestore: (n: number) => void }) {
  return (
    <Table>
      <thead>
        <tr>
          <th>نسخه</th>
          <th>منبع</th>
          <th>یادداشت</th>
          <th>وضعیت</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {versions.map((v) => (
          <tr key={v.number}>
            <td className="u-num">{fa(v.number)}</td>
            <td className="u3d-mono">{v.source}</td>
            <td className="text-xs">{v.note}</td>
            <td>{v.valid ? <Badge tone="ok">معتبر</Badge> : <Badge tone="bad">ایراد</Badge>}</td>
            <td>
              {v.number !== current ? (
                <Button size="sm" variant="secondary" onClick={() => onRestore(v.number)}>
                  بازگردانی
                </Button>
              ) : (
                <span className="text-xs" style={{ color: "var(--text-3)" }}>
                  فعلی
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
