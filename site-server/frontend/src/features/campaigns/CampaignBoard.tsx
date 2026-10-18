import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import {
  Alert,
  Badge,
  Button,
  ErrorBox,
  Input,
  Select,
  Spinner,
  fa,
} from "../../components/ui";

type Task = {
  id: number;
  kind: string;
  kind_label: string;
  title: string;
  detail: string;
  state: string;
  effective_state: string;
  state_label: string;
  priority: number;
  assigned_to: number | null;
  assigned_username: string | null;
  due_at: string | null;
  is_late: boolean;
  waiting_on_person: boolean;
  job: number | null;
  machine_owned: boolean;
  because: string;
};

type Column = {
  kind: string;
  title: string;
  tasks: Task[];
  done: number;
  total: number;
};

type Board = {
  columns: Column[];
  total: number;
  done: number;
  percent: number;
  late: Task[];
  waiting: Task[];
  kinds: { key: string; title: string }[];
  states: { key: string; title: string }[];
};

const TONE: Record<string, "ok" | "warn" | "bad" | "info" | "neutral"> = {
  TODO: "neutral",
  DOING: "info",
  BLOCKED: "warn",
  DONE: "ok",
  DROPPED: "neutral",
};

/**
 * The campaign as a list of things that have to happen. §29.1
 *
 * A task backed by a job shows the job's state and its control is disabled —
 * `machine_owned` from the server. Letting someone tick off a render that is
 * still going would make the board say "done" over work that is not, and a
 * board caught lying once is one people stop reading.
 */
export default function CampaignBoard({ campaignId }: { campaignId: number }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("CONTENT");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/campaigns/${campaignId}/board/`);
      setBoard(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [campaignId]);

  useEffect(() => {
    load();
  }, [load]);

  async function add() {
    if (!title.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/campaigns/${campaignId}/board/`, { title: title.trim(), kind });
      setTitle("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function fill() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/campaigns/${campaignId}/board/`, { seed: true });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function setState(task: Task, state: string) {
    setError(null);
    try {
      await api.patch(`/campaigns/${campaignId}/board/${task.id}/`, { state });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove(task: Task) {
    try {
      await api.delete(`/campaigns/${campaignId}/board/${task.id}/`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (!board) return <Spinner size={18} />;

  return (
    <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--line)" }}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold" style={{ color: "var(--text)" }}>
            کارهای این کمپین
          </span>
          {board.total > 0 && (
            <Badge tone={board.percent === 100 ? "ok" : "info"}>
              {fa(board.done)} از {fa(board.total)} کار
            </Badge>
          )}
        </div>
        {board.total === 0 && (
          <Button variant="secondary" onClick={fill} disabled={busy}>
            کارهای معمول را بگذار
          </Button>
        )}
      </div>

      <ErrorBox message={error} />

      {board.waiting.length > 0 && (
        <div className="mb-3">
          <Alert tone="warn" title="منتظر شماست">
            {board.waiting.map((t) => t.title).join("، ")} — تا تأیید نکنید جلو
            نمی‌رود.
          </Alert>
        </div>
      )}
      {board.late.length > 0 && (
        <div className="mb-3">
          <Alert tone="bad" title="از موعد گذشته">
            {board.late.map((t) => t.title).join("، ")}
          </Alert>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {board.columns
          .filter((column) => column.tasks.length > 0)
          .map((column) => (
            <div key={column.kind}>
              <p className="mb-1 text-xs font-bold" style={{ color: "var(--text-3)" }}>
                {column.title} ({fa(column.done)}/{fa(column.total)})
              </p>
              <div className="flex flex-col gap-1">
                {column.tasks.map((task) => (
                  <div
                    key={task.id}
                    className="flex flex-wrap items-center gap-2 rounded-lg px-3 py-2"
                    style={{ background: "var(--surface-2)" }}
                  >
                    <Badge tone={TONE[task.effective_state] ?? "neutral"}>
                      {task.state_label}
                    </Badge>
                    <span
                      className="min-w-0 flex-1 text-sm"
                      style={{
                        color: "var(--text)",
                        textDecoration:
                          task.effective_state === "DONE" ? "line-through" : "none",
                      }}
                    >
                      {task.title}
                    </span>
                    {task.assigned_username && (
                      <Badge tone="neutral">{task.assigned_username}</Badge>
                    )}
                    {task.is_late && <Badge tone="bad">دیر شده</Badge>}

                    {task.machine_owned ? (
                      // The state belongs to the job; a control here would let
                      // someone contradict what is actually happening.
                      <span className="text-xs" style={{ color: "var(--text-3)" }}>
                        خودکار
                      </span>
                    ) : (
                      <>
                        <Select
                          value={task.effective_state}
                          onChange={(e) => setState(task, e.target.value)}
                        >
                          {board.states.map((state) => (
                            <option key={state.key} value={state.key}>
                              {state.title}
                            </option>
                          ))}
                        </Select>
                        <Button variant="ghost" onClick={() => remove(task)}>
                          ×
                        </Button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Select value={kind} onChange={(e) => setKind(e.target.value)}>
          {board.kinds.map((k) => (
            <option key={k.key} value={k.key}>
              {k.title}
            </option>
          ))}
        </Select>
        <div className="min-w-[12rem] flex-1">
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") add();
            }}
            placeholder="کار تازه…"
          />
        </div>
        <Button onClick={add} disabled={busy || !title.trim()}>
          اضافه کن
        </Button>
      </div>
    </div>
  );
}
