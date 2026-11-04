import { DragEvent, useRef, useState } from "react";

import Icon from "../../../../components/Icon";
import { Alert, Spinner, fa } from "../../../../components/ui";
import { g, problem } from "../../api";
import { bytes, num } from "../../format";
import { useMeta } from "../../MetaContext";
import type { CsvUpload } from "../../types";

/** Step 1: pick or drop a CSV file. The server checks size, type and encoding; we only pre-check the size. */
export default function CsvUploadStep({ onUploaded }: { onUploaded: (upload: CsvUpload) => void }) {
  const { meta } = useMeta();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const maxBytes = meta?.csv.max_bytes ?? 5 * 1024 * 1024;
  const maxRows = meta?.csv.max_rows ?? 10000;

  const send = async (file: File | undefined) => {
    if (!file || busy) return;
    setError(null);
    if (file.size > maxBytes) {
      setError(`حجم فایل ${bytes(file.size)} است و از سقفِ ${bytes(maxBytes)} بیشتر است.`);
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      onUploaded(await g.post<CsvUpload>("/discovery/csv/upload/", form));
    } catch (err) {
      setError(problem(err).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };

  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragging(false);
    void send(e.dataTransfer.files?.[0]);
  };

  return (
    <div className="space-y-4" data-testid="csv-step-1">
      <label
        htmlFor="csv-file"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className="flex cursor-pointer flex-col items-center gap-2 rounded-2xl px-6 py-10 text-center"
        style={{
          border: `2px dashed ${dragging ? "var(--brand)" : "var(--line-strong)"}`,
          background: dragging ? "var(--brand-soft)" : "var(--surface-2)",
          transition: "background .15s, border-color .15s",
        }}
      >
        {busy ? <Spinner size={28} /> : <Icon name="upload" size={30} />}
        <span className="text-base font-bold" style={{ color: "var(--text)" }}>
          {busy ? "در حال خواندنِ فایل…" : "فایلِ CSV را اینجا بیندازید یا برای انتخاب بزنید"}
        </span>
        <span className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
          حداکثر {bytes(maxBytes)} و {num(maxRows)} ردیف · اولین ردیف باید عنوانِ ستون‌ها باشد
        </span>
        <input
          ref={input}
          id="csv-file"
          type="file"
          accept=".csv,.txt,.tsv,text/csv,text/plain"
          className="sr-only"
          data-testid="csv-file"
          onChange={(e) => void send(e.target.files?.[0])}
          disabled={busy}
        />
      </label>

      {error && (
        <Alert tone="bad" title="فایل پذیرفته نشد">
          <span data-testid="csv-upload-error">{error}</span>
        </Alert>
      )}

      <ul className="list-disc space-y-1 pr-5 text-sm leading-7" style={{ color: "var(--text-3)" }}>
        <li>کدگذاری‌های UTF-8 (با یا بدونِ BOM)، UTF-16 و ویندوز-{fa(1256)} (خروجیِ فارسیِ اکسل) خوانده می‌شود.</li>
        <li>جداکننده (ویرگول، نقطه‌ویرگول، تب یا |) خودکار پیدا می‌شود.</li>
        <li>ستونِ تلفن می‌تواند چند شماره داشته باشد (با | یا ، جدا)؛ صفرِ ابتدایی که اکسل انداخته برمی‌گردد.</li>
        <li>در این مرحله فقط فایل بررسی می‌شود؛ تا «شروعِ ورود» را نزنید چیزی ثبت نمی‌شود.</li>
      </ul>
    </div>
  );
}
