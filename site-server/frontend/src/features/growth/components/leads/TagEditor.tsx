import { FormEvent, useState } from "react";

import Icon from "../../../../components/Icon";
import { Button, Input } from "../../../../components/ui";
import { tagTone } from "../../format";
import type { Tag } from "../../types";

/** The lead's tags as chips with a remove cross, and a small box to add one. Reports the new list of names. */
export default function TagEditor({ tags, busy, onChange }: { tags: Tag[]; busy: boolean; onChange: (names: string[]) => void }) {
  const [text, setText] = useState("");
  const names = tags.map((t) => t.name);

  const add = (e: FormEvent) => {
    e.preventDefault();
    const fresh = text
      .split(/[,،]+/)
      .map((s) => s.trim())
      .filter((s) => s && !names.includes(s));
    if (fresh.length) onChange([...names, ...fresh]);
    setText("");
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="tag-editor">
      {tags.map((t) => (
        <span key={t.id} className={`u-badge u-badge-${tagTone(t.color)}`} data-testid="tag-chip">
          {t.name}
          <button
            type="button"
            onClick={() => onChange(names.filter((n) => n !== t.name))}
            disabled={busy}
            aria-label={`برداشتنِ برچسبِ ${t.name}`}
            style={{ background: "none", border: 0, color: "inherit", cursor: "pointer", display: "inline-flex", padding: 0 }}
          >
            <Icon name="x" size={11} />
          </button>
        </span>
      ))}
      <form onSubmit={add} className="flex items-center gap-1.5">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="برچسبِ تازه"
          aria-label="برچسبِ تازه"
          style={{ width: 130, padding: "5px 10px" }}
          data-testid="tag-input"
        />
        <Button type="submit" size="sm" variant="secondary" disabled={busy || !text.trim()} data-testid="tag-add">
          <Icon name="plus" size={13} />
        </Button>
      </form>
    </div>
  );
}
