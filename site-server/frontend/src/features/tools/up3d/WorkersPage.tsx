import { FormEvent, useCallback, useEffect, useState } from "react";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, EmptyState, ErrorBox, Field, Input, PageHeader, Spinner, Table } from "../../../components/ui";
import { ago, errMsg, fa, up3d } from "./api";
import { Muted, useToast } from "./shared";
import type { Worker } from "./types";

/**
 * کارگرهای رندر: فهرست (آنلاین، سخت‌افزار، سرعتِ اندازه‌گیری‌شده)، افزودن، فعال/غیرفعال،
 * فایلِ راه‌اندازیِ ویندوز و بستهٔ کارگر (هر دو با توکنِ پنل دانلود می‌شوند).
 */

const PROFILE_OPTIONS: { id: string; name: string }[] = [
  { id: "standard", name: "استاندارد" },
  { id: "high", name: "بالا" },
  { id: "ultra", name: "4K" },
  { id: "preview", name: "پیش‌نمایش" },
];

export default function WorkersPage() {
  const toast = useToast();
  const [workers, setWorkers] = useState<Worker[] | null>(null);
  const [server, setServer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [profiles, setProfiles] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [shown, setShown] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    try {
      const r = await up3d.workers();
      setWorkers(r.workers);
      setServer(r.server);
      setError(null);
    } catch (e) {
      setError(errMsg(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await up3d.addWorker(name.trim(), profiles);
      toast(r.message);
      setName("");
      setProfiles([]);
      await load();
    } catch (err) {
      toast(errMsg(err), true);
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (w: Worker) => {
    try {
      await up3d.toggleWorker(w.id);
      await load();
    } catch (err) {
      toast(errMsg(err), true);
    }
  };

  const bat = async (w: Worker) => {
    try {
      await up3d.downloadBat(w);
    } catch (err) {
      toast(errMsg(err), true);
    }
  };

  const bundle = async () => {
    try {
      await up3d.downloadBundle();
    } catch (err) {
      toast(errMsg(err), true);
    }
  };

  const reveal = (id: number) =>
    setShown((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });

  const gpuText = (w: Worker) => {
    const g = w.capabilities.gpu;
    return Array.isArray(g) ? g.join(", ") : typeof g === "string" ? g : "";
  };

  return (
    <div className="space-y-4">
      <PageHeader title="کارگرهای رندر" />
      <Muted>
        رندرِ سنگین داخلِ پنل اجرا نمی‌شود؛ «کارگر» کار را از پنل می‌گیرد، با Blender رندر می‌کند و نتیجه را پس می‌فرستد. کارگرِ{" "}
        <b>server-cpu</b> روی همین سرور با اولویتِ پایین (فقط انیمیک و پیش‌نمایش) کار می‌کند. برای کیفیتِ <b>استاندارد/بالا/4K</b> یک
        کامپیوترِ دارای کارتِ گرافیک (مثلاً RTX 3060) را کارگر کنید — همان کد، صد برابر سریع‌تر.
      </Muted>
      <ErrorBox message={error} />

      {workers === null ? (
        <div className="py-10 text-center">
          <Spinner />
        </div>
      ) : workers.length === 0 ? (
        <Card>
          <EmptyState icon="cpu" title="کارگری نیست" description="با فرمِ پایین اولین کارگر را بسازید." />
        </Card>
      ) : (
        <Card padded={false}>
          <Table>
            <thead>
              <tr>
                <th>نام</th>
                <th>وضعیت</th>
                <th>سخت‌افزار</th>
                <th>Blender</th>
                <th>سرعتِ اندازه‌گیری‌شده</th>
                <th>کارهای انجام‌شده</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {workers.map((w) => (
                <tr key={w.id}>
                  <td>
                    <b style={{ color: "var(--text)" }}>{w.name}</b> {!w.enabled && <Badge tone="bad">غیرفعال</Badge>}
                    <div className="text-xs" style={{ color: "var(--text-3)" }}>
                      {w.profiles.length ? `فقط: ${w.profiles.join("، ")}` : "پروفایل: خودکار"}
                    </div>
                  </td>
                  <td>
                    <Badge tone={w.online ? "ok" : "bad"}>{w.online ? "آنلاین" : "آفلاین"}</Badge>
                    <div className="text-xs" style={{ color: "var(--text-3)" }}>
                      {w.last_seen ? ago(w.last_seen) : ""}
                    </div>
                  </td>
                  <td className="text-xs">
                    {w.has_gpu ? (
                      <>
                        <Badge tone="ok">GPU</Badge> {gpuText(w)}
                      </>
                    ) : (
                      <>
                        <Badge>CPU</Badge> {w.capabilities.cpu_count ?? "?"} هسته
                      </>
                    )}
                    <div style={{ color: "var(--text-3)" }}>{w.capabilities.os || ""}</div>
                  </td>
                  <td className="u3d-mono text-xs">{w.capabilities.blender_version || "—"}</td>
                  <td className="text-xs">
                    {Object.keys(w.stats).length === 0
                      ? "—"
                      : Object.entries(w.stats).map(([k, v]) => (
                          <div key={k}>
                            {k}: <b>{fa(v.sec_per_frame)}</b> ث/فریم ({fa(v.n)})
                          </div>
                        ))}
                  </td>
                  <td className="u-num">{fa(w.jobs_done)}</td>
                  <td>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Button variant="secondary" size="sm" onClick={() => void bat(w)}>
                        <Icon name="download" size={13} />
                        فایلِ راه‌اندازیِ ویندوز
                      </Button>
                      {shown.has(w.id) ? (
                        <code className="u3d-mono text-xs" style={{ wordBreak: "break-all", color: "var(--text-2)" }}>
                          {w.token}
                        </code>
                      ) : (
                        <Button variant="ghost" size="sm" onClick={() => reveal(w.id)}>
                          توکن
                        </Button>
                      )}
                      <Button variant={w.enabled ? "danger" : "secondary"} size="sm" onClick={() => void toggle(w)}>
                        {w.enabled ? "غیرفعال کن" : "فعال کن"}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <form onSubmit={(e) => void add(e)} className="space-y-3">
            <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>
              افزودنِ کارگر
            </h2>
            <Field label="نام">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="مثلاً gpu-rtx3060" required />
            </Field>
            <div>
              <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                فقط این کیفیت‌ها (اختیاری)
              </span>
              <div className="flex flex-wrap gap-4">
                {PROFILE_OPTIONS.map((p) => (
                  <label key={p.id} className="flex items-center gap-1.5 text-sm" style={{ color: "var(--text-2)" }}>
                    <input
                      type="checkbox"
                      checked={profiles.includes(p.id)}
                      onChange={(e) =>
                        setProfiles((prev) => (e.target.checked ? [...prev, p.id] : prev.filter((x) => x !== p.id)))
                      }
                    />
                    {p.name}
                  </label>
                ))}
              </div>
              <Muted className="mt-1 text-xs">خالی = خودکار: با GPU همه، بی‌GPU فقط انیمیک و پیش‌نمایش.</Muted>
            </div>
            <Button type="submit" disabled={busy}>
              {busy ? "…" : "ساختِ کارگر و توکن"}
            </Button>
          </form>
        </Card>

        <Card>
          <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>
            راه‌اندازی روی کامپیوترِ ویندوز با کارتِ گرافیک
          </h2>
          <ol className="mt-2 space-y-1.5 text-sm" style={{ color: "var(--text-2)", paddingInlineStart: "1.3em", listStyle: "decimal" }}>
            <li>
              <b>Blender 4.5 LTS</b> و <b>Python 3.10+</b> را نصب کنید (از سایتِ رسمی).
            </li>
            <li>
              <button type="button" className="underline" style={{ color: "var(--brand-strong)" }} onClick={() => void bundle()}>
                بستهٔ کارگر (zip)
              </button>{" "}
              را بگیرید و در <code className="u3d-mono">C:\up3d</code> باز کنید (هسته، موتور، دارایی‌ها، افزونهٔ کاراکتر).
            </li>
            <li>از جدولِ بالا «فایلِ راه‌اندازیِ ویندوز» را بگیرید و داخلِ همان پوشه اجرا کنید. کارگر خودکار GPU را پیدا می‌کند (OptiX/CUDA) و کار می‌گیرد.</li>
            <li>در همین صفحه وضعیتش «آنلاین» و «GPU» می‌شود؛ رندرهای «بالا» و «4K» خودکار به آن می‌روند.</li>
          </ol>
          <Muted className="mt-3">یا با خطِ فرمان روی هر سیستمی (لینوکس/مک/ویندوز):</Muted>
          <pre className="u3d-pre mt-1">{`python -m up3d worker --server ${server || "<SERVER>/3d"} --token <TOKEN> --name gpu-pc`}</pre>
        </Card>
      </div>
    </div>
  );
}
