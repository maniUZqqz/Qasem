import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Button, Card, ErrorBox, Field, Input } from "../../../components/ui";
import { api, fieldErrors, pUrl, studioError } from "./api";
import { Help, Mono, SectionHead } from "./common";
import type { Project } from "./types";

const STEPS = [
  <>پروژه در یک پوشهٔ جدا (workspace) کپی می‌شود؛ ZIP در برابرِ مسیرهای ناامن وارسی می‌شود.</>,
  <>
    <b>بدونِ اجرای کد</b> (فقط خواندنِ متن با ast) settings، INSTALLED_APPS، مدل‌ها، فیلدها، ویوها، URLها و قالب‌ها شناسایی
    می‌شوند.
  </>,
  <>
    یک <b>گزارشِ سازگاری</b> می‌گیری: چه شناخته شد، چه نامعلوم ماند.
  </>,
  <>نسخهٔ اصلی در Git ثبت می‌شود تا هر تغییر قابلِ دیدن و برگشت باشد.</>,
];

/** واردکردنِ پروژهٔ جنگوی موجود (ZIP یا پوشه روی سرور) */
export default function ImportPage() {
  const navigate = useNavigate();
  const [roots, setRoots] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [src, setSrc] = useState<"zip" | "path">("zip");
  const [file, setFile] = useState<File | null>(null);
  const [serverPath, setServerPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    api
      .get<{ roots: string[] }>("/studio/import/")
      .then((r) => setRoots(r.data.roots))
      .catch(() => setRoots([]));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setErrors({});
    try {
      const fd = new FormData();
      fd.append("name", name);
      fd.append("slug", slug);
      if (src === "zip" && file) fd.append("zip", file);
      if (src === "path") fd.append("server_path", serverPath);
      const { data } = await api.post<{ project: Project; message: string }>("/studio/import/", fd);
      navigate(pUrl(data.project.slug, "import-report"), { state: { notice: { text: data.message } } });
    } catch (err) {
      setError(studioError(err));
      setErrors(fieldErrors(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <form onSubmit={submit} className="space-y-4">
          <SectionHead title="پروژهٔ جنگوی موجود" hint="idea.md فازِ ۰۹" />
          <ErrorBox message={error} />
          <Field label="نام" hint={errors.name}>
            <Input value={name} onChange={(e) => setName(e.target.value)} required placeholder="مثلاً سایتِ قدیمیِ فروشگاه" />
          </Field>
          <Field label="شناسهٔ انگلیسی (نامِ پوشه)" hint={errors.slug}>
            <Input value={slug} onChange={(e) => setSlug(e.target.value)} pattern="[a-z0-9-]*" dir="ltr" placeholder="old-shop" />
          </Field>

          <SectionHead title={<span className="text-sm">از کجا؟</span>} />
          <div className="flex flex-wrap gap-4 text-sm" style={{ color: "var(--text-2)" }}>
            <label className="inline-flex cursor-pointer items-center gap-1.5">
              <input type="radio" checked={src === "zip"} onChange={() => setSrc("zip")} /> فایلِ ZIP
            </label>
            <label className="inline-flex cursor-pointer items-center gap-1.5">
              <input type="radio" checked={src === "path"} onChange={() => setSrc("path")} /> پوشه روی همین سرور
            </label>
          </div>
          {src === "zip" ? (
            <div>
              <input
                type="file"
                accept=".zip,application/zip"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="u-input"
              />
              {errors.zip && (
                <p className="mt-1 text-xs" style={{ color: "var(--bad)" }}>
                  {errors.zip}
                </p>
              )}
              <Help>
                کلِ پروژه را ZIP کن (همان پوشه‌ای که manage.py دارد). venv، node_modules و __pycache__ خودکار کنار گذاشته
                می‌شوند.
              </Help>
            </div>
          ) : (
            <div>
              <Input value={serverPath} onChange={(e) => setServerPath(e.target.value)} dir="ltr" placeholder={`${roots[0] ?? "/var/www"}/my-project`} />
              <Help>
                فقط زیرِ این پوشه‌ها:{" "}
                {roots.map((r) => (
                  <Mono key={r} className="me-1">
                    {r}
                  </Mono>
                ))}
                — یک <b>رونوشت</b> گرفته می‌شود؛ پوشهٔ اصلی دست نمی‌خورد.
              </Help>
            </div>
          )}
          <Button type="submit" disabled={busy || !name.trim() || (src === "zip" ? !file : !serverPath.trim())}>
            <Icon name="upload" size={15} />
            {busy ? "در حالِ واردکردن و تحلیل…" : "وارد کن و تحلیل کن"}
          </Button>
        </form>
      </Card>

      <div className="space-y-5">
        <Card>
          <SectionHead title="چه اتفاقی می‌افتد" />
          <ol className="space-y-2 text-sm leading-7" style={{ color: "var(--text-2)" }}>
            {STEPS.map((s, i) => (
              <li key={i} className="flex gap-3">
                <span
                  className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold"
                  style={{ background: "var(--brand-soft)", color: "var(--brand-strong)" }}
                >
                  {i + 1}
                </span>
                <span>{s}</span>
              </li>
            ))}
          </ol>
        </Card>
        <Card>
          <SectionHead title="بعد از واردکردن چه می‌شود کرد (سطحِ ۲)" />
          <ul className="list-disc space-y-1 ps-5 text-sm leading-7" style={{ color: "var(--text-2)" }}>
            <li>ساختار را گرافیکی ببینی: اپ‌ها، مدل‌ها، نمودارِ رابطه‌ها، نقشهٔ URLها، کد.</li>
            <li>هر قالبِ HTML را دستی یا با هوشِ مصنوعی ویرایش کنی (با Diff و تأیید).</li>
            <li>
              <b>اپِ تازه</b> با مدل، ویو و نشانی بسازی؛ استودیو کاملش را می‌نویسد و با یک خط به settings و urls ِ پروژه وصل
              می‌کند.
            </li>
            <li>پیش‌نمایشِ زنده و ZIPِ خروجی.</li>
          </ul>
          <div className="mt-3">
            <Alert tone="warn">
              کدِ اپ‌ها و مدل‌های خودِ پروژه بازنویسی نمی‌شود (فقط نمایش). «تولیدِ کد» و «پیش‌نمایش» کدِ پروژه را اجرا می‌کنند؛
              فقط پروژه‌ای را وارد کن که به آن اعتماد داری.
            </Alert>
          </div>
        </Card>
      </div>
    </div>
  );
}
