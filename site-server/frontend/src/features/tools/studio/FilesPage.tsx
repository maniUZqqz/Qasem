import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, EmptyState, ErrorBox, Input } from "../../../components/ui";
import { api, downloadZip, fa, studioError } from "./api";
import { CopyButton, Loading, Mono, Pre, SectionHead } from "./common";
import { useProject } from "./shell";
import type { FileContentResp, FilesResp } from "./types";

/** فایل‌ها — کدِ واقعیِ جنگو، همان که در ZIP می‌آید */
export default function FilesPage() {
  const { slug, notify, buildCount } = useProject();
  const [params, setParams] = useSearchParams();
  const rel = params.get("f") ?? "";
  const [data, setData] = useState<FilesResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<FileContentResp | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    api
      .get<FilesResp>(`/studio/projects/${slug}/files/`)
      .then((r) => setData(r.data))
      .catch((err) => setError(studioError(err)));
  }, [slug, buildCount]);

  useEffect(() => {
    if (!rel) {
      setFile(null);
      return;
    }
    setFileError(null);
    api
      .get<FileContentResp>(`/studio/projects/${slug}/files/content/`, { params: { f: rel } })
      .then((r) => setFile(r.data))
      .catch((err) => {
        setFile(null);
        setFileError(studioError(err));
      });
  }, [slug, rel, buildCount]);

  if (!data) return <Loading error={error} />;

  const query = q.trim().toLowerCase();

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm" style={{ color: "var(--text-3)" }}>
          فایل‌ها{rel && <> › <Mono>{rel}</Mono></>}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="ms-auto"
          onClick={() => downloadZip(slug, false).catch((err: unknown) => notify(err instanceof Error ? err.message : studioError(err), "bad"))}
        >
          <Icon name="download" size={14} />
          دانلودِ ZIP
        </Button>
      </div>

      {data.tree.length === 0 ? (
        <Card>
          <EmptyState title="هنوز فایلی نیست">«تولیدِ کد» را بزن تا پروژه روی دیسک نوشته شود.</EmptyState>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <Card className="self-start">
            <SectionHead title={<span className="text-sm">{fa(data.tree.length)} فایل</span>} hint={<Mono>{slug}/</Mono>} />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جست‌وجوی فایل…" dir="ltr" className="mb-2" />
            <div className="max-h-[70vh] overflow-auto text-xs" dir="ltr" style={{ textAlign: "left" }}>
              {data.groups.map(([dir, files]) => {
                const shown = files.filter((f) => !query || f.path.toLowerCase().includes(query));
                if (!shown.length) return null;
                return (
                  <div key={dir || "."}>
                    {!query && (
                      <div className="mt-2 flex items-center gap-1 px-1 font-mono font-bold" style={{ color: "var(--text-3)" }}>
                        <Icon name="inbox" size={12} />
                        {dir || "."}
                      </div>
                    )}
                    {shown.map((f) => (
                      <button
                        key={f.path}
                        type="button"
                        onClick={() => setParams({ f: f.path })}
                        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left font-mono"
                        style={{
                          background: f.path === rel ? "var(--brand-soft)" : "transparent",
                          color: f.path === rel ? "var(--brand-strong)" : "var(--text-2)",
                        }}
                      >
                        <Icon name="receipt" size={12} />
                        {query ? f.path : f.name}
                      </button>
                    ))}
                  </div>
                );
              })}
            </div>
          </Card>

          <Card>
            <ErrorBox message={fileError} />
            {file ? (
              <>
                <SectionHead
                  title={<Mono className="text-sm">{file.rel}</Mono>}
                  hint={`${fa(file.content.length)} کاراکتر`}
                  action={
                    <>
                      {file.custom_zone && (
                        <span title="هر چه زیرِ این خط بنویسی با تولیدِ دوباره می‌ماند">
                          <Badge tone="warn">ناحیهٔ دستی دارد</Badge>
                        </span>
                      )}
                      <CopyButton text={file.content} />
                    </>
                  }
                />
                <Pre text={file.content} mark={file.mark} maxHeight="calc(100vh - 230px)" />
              </>
            ) : (
              !fileError && (
                <EmptyState title="یک فایل انتخاب کن" description="کدِ واقعیِ جنگو — همان که در ZIP می‌آید." />
              )
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
