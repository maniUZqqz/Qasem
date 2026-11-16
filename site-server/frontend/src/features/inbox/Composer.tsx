import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "../../components/ui";
import { Canned, Member } from "./api";

type Mode = "reply" | "note";

type Suggestion = { key: string; title: string; hint: string; insert: string; cannedId?: number };

/** آخرین «توکن» پیش از مکان‌نما: `/سلام` یا `@sa`؛ برای باز کردن فهرست پیشنهاد. */
function tokenAt(text: string, caret: number): { start: number; mark: string; term: string } | null {
  const before = text.slice(0, caret);
  const match = /(^|\s)([/@])([^\s]*)$/.exec(before);
  if (!match) return null;
  return { start: caret - match[2].length - match[3].length, mark: match[2], term: match[3] };
}

export default function Composer({
  canWrite,
  canned,
  members,
  draft,
  setDraft,
  onSend,
  disabledReason,
  busy,
}: {
  canWrite: boolean;
  canned: Canned[];
  members: Member[];
  draft: string;
  setDraft: (text: string) => void;
  onSend: (text: string, mode: Mode, cannedId?: number) => Promise<void>;
  disabledReason?: string;
  busy: boolean;
}) {
  const [mode, setMode] = useState<Mode>("reply");
  const [cannedId, setCannedId] = useState<number | undefined>();
  const [caret, setCaret] = useState(0);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLTextAreaElement>(null);

  const token = tokenAt(draft, caret);
  const suggestions = useMemo<Suggestion[]>(() => {
    if (!token) return [];
    const term = token.term.toLowerCase();
    if (token.mark === "/") {
      return canned
        .filter((c) => !term || c.shortcut.toLowerCase().startsWith(term) || c.title.includes(token.term))
        .slice(0, 8)
        .map((c) => ({ key: `c${c.id}`, title: c.title, hint: c.text, insert: c.text, cannedId: c.id }));
    }
    if (mode !== "note") return [];
    return members
      .filter((m) => !term || m.username.toLowerCase().startsWith(term) || m.name.includes(token.term))
      .slice(0, 8)
      .map((m) => ({ key: `m${m.username}`, title: m.name, hint: `@${m.username}`, insert: `@${m.username} ` }));
  }, [token?.mark, token?.term, canned, members, mode]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => setActive(0), [token?.term, token?.mark]);

  const apply = (s: Suggestion) => {
    if (!token) return;
    const next = draft.slice(0, token.start) + s.insert + draft.slice(caret);
    setDraft(next);
    setCannedId(s.cannedId ?? cannedId);
    window.setTimeout(() => {
      const pos = token.start + s.insert.length;
      box.current?.focus();
      box.current?.setSelectionRange(pos, pos);
      setCaret(pos);
    }, 0);
  };

  const submit = async () => {
    const text = draft.trim();
    if (!text || busy || !canWrite) return;
    await onSend(text, mode, mode === "reply" ? cannedId : undefined);
    setCannedId(undefined);
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (suggestions.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((a) => (a + 1) % suggestions.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => (a - 1 + suggestions.length) % suggestions.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        apply(suggestions[active]);
        return;
      }
      if (e.key === "Escape") {
        setCaret(0);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };

  if (!canWrite) {
    return (
      <div className="ib-composer" style={{ color: "var(--text-3)", fontSize: ".8rem" }}>
        {disabledReason || "نقش شما فقط اجازهٔ دیدن دارد؛ برای پاسخ دادن از مالک فروشگاه نقش «پشتیبانی» بگیرید."}
      </div>
    );
  }

  return (
    <div className={`ib-composer ${mode === "note" ? "note" : ""}`}>
      {suggestions.length > 0 && (
        <div className="ib-suggest" role="listbox" aria-label="پیشنهادها">
          {suggestions.map((s, i) => (
            <button key={s.key} type="button" role="option" aria-selected={i === active} className={i === active ? "on" : ""} onMouseDown={(e) => { e.preventDefault(); apply(s); }}>
              <b>{s.title}</b>
              <small>{s.hint}</small>
            </button>
          ))}
        </div>
      )}
      <div className="ib-modes">
        <button type="button" className={`ib-mode ${mode === "reply" ? "on" : ""}`} onClick={() => setMode("reply")}>
          پاسخ به مشتری
        </button>
        <button type="button" className={`ib-mode ${mode === "note" ? "on" : ""}`} onClick={() => setMode("note")}>
          یادداشت داخلی
        </button>
        <span className="mr-auto text-[11px]" style={{ color: "var(--text-3)", marginInlineStart: "auto" }}>
          {mode === "reply" ? "برای پاسخ آماده «/» بزنید" : "فقط تیم می‌بیند؛ با «@» همکار را صدا بزنید"}
        </span>
      </div>
      <textarea
        className="u-input"
        ref={box}
        value={draft}
        rows={2}
        placeholder={mode === "reply" ? "پاسخ را بنویسید… (Enter = ارسال، Shift+Enter = خط تازه)" : "یادداشت داخلی…"}
        aria-label={mode === "reply" ? "متن پاسخ" : "متن یادداشت"}
        onChange={(e) => {
          setDraft(e.target.value);
          setCaret(e.target.selectionStart ?? e.target.value.length);
        }}
        onKeyUp={(e) => setCaret((e.target as HTMLTextAreaElement).selectionStart ?? 0)}
        onClick={(e) => setCaret((e.target as HTMLTextAreaElement).selectionStart ?? 0)}
        onKeyDown={onKey}
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px]" style={{ color: "var(--text-3)" }}>
          {draft.length ? `${draft.length.toLocaleString("fa-IR")} نویسه` : ""}
        </span>
        <Button size="sm" disabled={!draft.trim() || busy} onClick={() => void submit()}>
          {mode === "reply" ? "ارسال" : "ثبت یادداشت"}
        </Button>
      </div>
    </div>
  );
}
