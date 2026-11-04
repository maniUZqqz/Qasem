import { FormEvent, useState } from "react";

import Icon from "../../../../components/Icon";
import { Alert, Button, Card, EmptyState, TextArea } from "../../../../components/ui";
import { g, problem, useGet } from "../../api";
import { faDateTime } from "../../format";
import type { Note } from "../../types";
import { ConfirmDialog } from "../Modal";
import { LoadState } from "../bits";

/** The «یادداشت‌ها» tab: the team's notes on the lead; add, edit, delete (each is written to the history). */
export default function NotesTab({ leadId, onChanged }: { leadId: number; onChanged: () => void }) {
  const { data, loading, error, reload } = useGet<Note[]>(`/leads/${leadId}/notes/`);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [editId, setEditId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [removing, setRemoving] = useState<Note | null>(null);

  const run = async (fn: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true);
    setMessage(null);
    try {
      await fn();
      reload();
      onChanged();
      return true;
    } catch (err) {
      setMessage(problem(err).message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (await run(() => g.post(`/leads/${leadId}/notes/`, { body: text }))) setText("");
  };

  return (
    <div className="space-y-4" data-testid="notes-tab">
      <Card>
        <form onSubmit={add} className="space-y-3">
          <TextArea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="یادداشتِ تازه: چه گفتید، چه شنیدید، قدمِ بعدی چیست…" aria-label="یادداشتِ تازه" data-testid="note-input" />
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={busy || !text.trim()} data-testid="note-add">
              <Icon name="plus" size={15} />
              افزودنِ یادداشت
            </Button>
            {message && (
              <span className="text-sm" style={{ color: "var(--bad)" }} role="alert" data-testid="note-error">
                {message}
              </span>
            )}
          </div>
        </form>
      </Card>

      <LoadState loading={loading && !data} error={error} onRetry={reload}>
        {data && data.length === 0 ? (
          <Card>
            <EmptyState icon="chat" title="هنوز یادداشتی نیست" />
          </Card>
        ) : (
          <ul className="space-y-3">
            {(data ?? []).map((note) => (
              <li key={note.id}>
                <Card>
                  <div data-testid="note-item">
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-3)" }}>
                      <span className="font-medium" style={{ color: "var(--text-2)" }}>
                        {note.author_name || "—"}
                      </span>
                      <span>{faDateTime(note.created_at)}</span>
                      {note.updated_at !== note.created_at && <span>(ویرایش‌شده)</span>}
                      <span className="mr-auto flex gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label="ویرایش"
                          onClick={() => {
                            setEditId(note.id);
                            setEditText(note.body);
                          }}
                          data-testid="note-edit"
                        >
                          <Icon name="edit" size={14} />
                        </Button>
                        <Button size="sm" variant="ghost" aria-label="حذف" onClick={() => setRemoving(note)} data-testid="note-remove">
                          <Icon name="trash" size={14} />
                        </Button>
                      </span>
                    </div>
                    {editId === note.id ? (
                      <div className="space-y-2">
                        <TextArea rows={3} value={editText} onChange={(e) => setEditText(e.target.value)} aria-label="ویرایشِ یادداشت" data-testid="note-edit-input" />
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            disabled={busy || !editText.trim()}
                            onClick={async () => {
                              if (await run(() => g.patch(`/leads/${leadId}/notes/${note.id}/`, { body: editText }))) setEditId(null);
                            }}
                            data-testid="note-edit-save"
                          >
                            ذخیره
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => setEditId(null)} disabled={busy}>
                            انصراف
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <p className="whitespace-pre-wrap text-sm leading-7" dir="auto" style={{ color: "var(--text)" }}>
                        {note.body}
                      </p>
                    )}
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </LoadState>

      {message && !text && <Alert tone="bad">{message}</Alert>}

      <ConfirmDialog
        open={removing !== null}
        title="حذفِ یادداشت"
        message="این یادداشت پاک می‌شود (در تاریخچهٔ لید می‌ماند که پاک شده)."
        confirmLabel="حذف شود"
        danger
        busy={busy}
        onConfirm={async () => {
          if (removing) await run(() => g.del(`/leads/${leadId}/notes/${removing.id}/`));
          setRemoving(null);
        }}
        onClose={() => !busy && setRemoving(null)}
      />
    </div>
  );
}
