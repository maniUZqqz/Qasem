import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Button, Card, EmptyState, ErrorBox, Table } from "../../../components/ui";
import { api, downloadZip, fa, studioError, truncate } from "./api";
import { DiffView, Help, Loading, Mono, SectionHead } from "./common";
import { useProject } from "./shell";
import type { CommitDetail, HistoryResp } from "./types";

/** تاریخچهٔ نسخه‌ها (Git) */
export default function HistoryPage() {
  const { slug, notify, buildCount } = useProject();
  const [params, setParams] = useSearchParams();
  const sha = params.get("c") ?? "";
  const [data, setData] = useState<HistoryResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [commit, setCommit] = useState<CommitDetail | null>(null);
  const [commitError, setCommitError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<HistoryResp>(`/studio/projects/${slug}/history/`)
      .then((r) => setData(r.data))
      .catch((err) => setError(studioError(err)));
  }, [slug, buildCount]);

  useEffect(() => {
    if (!sha) {
      setCommit(null);
      return;
    }
    setCommitError(null);
    api
      .get<CommitDetail>(`/studio/projects/${slug}/history/${sha}/`)
      .then((r) => setCommit(r.data))
      .catch((err) => {
        setCommit(null);
        setCommitError(studioError(err));
      });
  }, [slug, sha]);

  if (!data) return <Loading error={error} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm" style={{ color: "var(--text-3)" }}>
          تاریخچهٔ نسخه‌ها{commit && <> › <Mono>{commit.short}</Mono></>}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="ms-auto"
          onClick={() => downloadZip(slug, true).catch((err: unknown) => notify(err instanceof Error ? err.message : studioError(err), "bad"))}
        >
          <Icon name="download" size={14} />
          ZIP با تاریخچه
        </Button>
      </div>
      {!data.git && <Alert tone="warn">git روی سرور نصب نیست؛ نسخه‌ها ثبت نمی‌شوند.</Alert>}

      <div className="grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
        <Card className="self-start">
          <SectionHead title={<span className="text-sm">{fa(data.commits.length)} نسخه</span>} hint="هر «تولیدِ کد» یک نسخه" />
          {data.commits.length === 0 ? (
            <EmptyState title="هنوز نسخه‌ای نیست">«تولیدِ کد» را بزن.</EmptyState>
          ) : (
            <div className="max-h-[70vh] space-y-0.5 overflow-auto">
              {data.commits.map((c) => (
                <button
                  key={c.sha}
                  type="button"
                  onClick={() => setParams({ c: c.sha })}
                  className="block w-full rounded-lg px-2.5 py-2 text-right"
                  style={{ background: commit && commit.short === c.short ? "var(--brand-soft)" : "transparent" }}
                >
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-xs" style={{ color: "var(--brand-strong)" }}>
                      {c.short}
                    </span>
                    <span className="ms-auto text-xs" style={{ color: "var(--text-3)" }}>
                      {c.date}
                    </span>
                  </div>
                  <div className="text-sm" style={{ color: "var(--text)" }}>
                    {truncate(c.subject, 70)}
                  </div>
                  {c.stat && (
                    <div dir="ltr" className="font-mono text-[11px]" style={{ color: "var(--text-3)", textAlign: "left" }}>
                      {c.stat}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
        </Card>

        <div>
          <ErrorBox message={commitError} />
          {commit ? (
            <Card padded={false}>
              <div className="px-5 pt-5">
                <SectionHead title={commit.subject} hint={<Mono>{commit.short} · {commit.date}</Mono>} />
              </div>
              <Table>
                <thead>
                  <tr>
                    <th>فایل</th>
                    <th style={{ width: 70 }}>+</th>
                    <th style={{ width: 70 }}>−</th>
                  </tr>
                </thead>
                <tbody>
                  {commit.files.map((f) => (
                    <tr key={f.path}>
                      <td dir="ltr" className="font-mono text-xs" style={{ textAlign: "left" }}>
                        {f.path}
                      </td>
                      <td style={{ color: "var(--ok)" }}>{f.add}</td>
                      <td style={{ color: "var(--bad)" }}>{f.del}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <div className="p-5">
                <DiffView text={commit.diff} maxHeight="calc(100vh - 300px)" />
                {commit.truncated && <Help>تغییرات بزرگ‌تر از حدِ نمایش بود؛ بخشِ اول نشان داده شد.</Help>}
              </div>
            </Card>
          ) : (
            !commitError && (
              <Card>
                <SectionHead title="نسخه‌بندی با Git" />
                <p className="text-sm leading-7" style={{ color: "var(--text-3)" }}>
                  هر بار که «تولیدِ کد» می‌زنی (یا تغییرِ هوشِ مصنوعی را اعمال می‌کنی) استودیو یک نسخه (commit) در پوشهٔ خودِ
                  پروژه ثبت می‌کند. از فهرست یک نسخه را انتخاب کن تا ببینی دقیقاً کدام خط‌ها عوض شده.
                </p>
                <p className="text-sm leading-7" style={{ color: "var(--text-3)" }}>
                  پوشهٔ <Mono>.git</Mono> همراهِ پروژه است: با «ZIP با تاریخچه» می‌بری و روی هر سیستمی با <Mono>git log</Mono>{" "}
                  می‌بینی.
                </p>
              </Card>
            )
          )}
        </div>
      </div>
    </div>
  );
}
