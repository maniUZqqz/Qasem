import { FormEvent, useCallback, useEffect, useState } from "react";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, EmptyState, ErrorBox, Field, Input, PageHeader, Spinner, Table } from "../../../components/ui";
import { ago, errMsg, fa, up3d } from "./api";
import { Muted, useToast } from "./shared";
import type { GpuNode, Worker } from "./types";

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
  const [nodes, setNodes] = useState<GpuNode[]>([]);
  const [blenderZip, setBlenderZip] = useState("");
  const [nodeBusy, setNodeBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await up3d.workers();
      setWorkers(r.workers);
      setServer(r.server);
      setNodes(r.gpu_nodes || []);
      setBlenderZip(r.blender_zip || "");
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

  const setNode3d = async (n: GpuNode, on: boolean | null) => {
    setNodeBusy(n.id);
    try {
      await up3d.setNode3d(n.id, on);
      toast(
        on === true
          ? `«رندرِ سه‌بعدی» روی ${n.name} روشن شد — در heartbeat ِ بعدی (چند ثانیه) worker-3d.bat اجرا می‌شود${
              n.blender ? "" : "؛ Blender و دادهٔ کاراکترها یک بار دانلود می‌شوند (~۸۰۰ مگابایت)"
            }`
          : on === false
            ? `«رندرِ سه‌بعدی» روی ${n.name} خاموش شد`
            : `«رندرِ سه‌بعدی» روی ${n.name} خودکار شد`,
      );
      await load();
    } catch (err) {
      toast(errMsg(err), true);
    } finally {
      setNodeBusy(null);
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
        <b>server-cpu</b> روی همین سرور با اولویتِ پایین فقط وقتی کار می‌کند که GPU نیست یا سرش گرم است. برای کیفیتِ
        <b> استاندارد/بالا/4K</b> «رندرِ سه‌بعدی» ِ سرورِ پردازش (RTX 3060) را روشن کنید — همان کد، ده‌ها برابر سریع‌تر.
      </Muted>
      <ErrorBox message={error} />

      <Card>
        <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>
          سرورهای پردازشِ GPU (رندرِ سه‌بعدی)
        </h2>
        <Muted>
          کارها اول به GPU می‌روند: تا وقتی کارگرِ GPU ِ بیکار آنلاین است، سرور هیچ رندری برنمی‌دارد؛ اگر GPU سرش گرم است، سرور فقط
          کارهای سبک (انیمیک، پیش‌نمایش، تصویر) را می‌سازد. کارِ سنگینی که با «اجرا روی CPU» روی سرور است، با آمدنِ GPU به آن واگذار
          می‌شود و برای کارِ کوتاهِ تازه موقتاً کنار می‌رود (فریم‌های ساخته‌شده می‌مانند). روی سرورِ پردازش «رندرِ سه‌بعدی» را روشن کنید
          (همین‌جا، یا ابزارها ← سرورهای پردازش ← سرویس‌ها ← «رندرِ سه‌بعدی»)؛ با «سوئیچِ خودکار» هر وقت کارِ سه‌بعدی منتظر باشد خودش
          روشن می‌شود. بارِ اول worker-3d.bat ِ آن کامپیوتر Blender 4.5 (~۴۰۰ مگابایت) و دادهٔ کاراکترهای MPFB
          (~۴۳۰ مگابایت) را از همین سایت می‌گیرد — دانلود ادامه‌پذیر است و پیش از باز شدن وارسی می‌شود. پوشهٔ processing ِ آن کامپیوتر
          باید به‌روز باشد (git pull).
        </Muted>
        {nodes.length === 0 ? (
          <div className="mt-2 text-sm" style={{ color: "var(--text-3)" }}>
            هیچ سرورِ پردازشی با GPU ثبت نشده (ابزارها ← سرورهای پردازش).
          </div>
        ) : (
          <div className="mt-3">
            <Table>
              <thead>
                <tr>
                  <th>سرور</th>
                  <th>GPU</th>
                  <th>Blender</th>
                  <th>رندرِ سه‌بعدی</th>
                  <th>کارگر</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((n) => (
                  <tr key={n.id}>
                    <td>
                      <b style={{ color: "var(--text)" }}>{n.name}</b>{" "}
                      <Badge tone={n.online ? "ok" : "bad"}>{n.online ? "آنلاین" : "آفلاین"}</Badge>
                      <div className="text-xs" style={{ color: "var(--text-3)" }}>
                        عامل {n.agent || "?"}
                      </div>
                    </td>
                    <td className="text-xs">{Array.isArray(n.gpu) ? n.gpu.join(", ") : n.gpu}</td>
                    <td className="text-xs">
                      {n.blender ? <Badge tone="ok">هست</Badge> : <Badge tone="warn">نیست — بارِ اول دانلود می‌شود</Badge>}
                    </td>
                    <td className="text-xs">
                      {n.worker3d_running ? <Badge tone="ok">در حالِ اجرا</Badge> : <Badge>خاموش</Badge>}{" "}
                      <span style={{ color: "var(--text-3)" }}>
                        {n.desired === true ? "· پنل: روشن" : n.desired === false ? "· پنل: خاموش" : n.auto_switch ? "· خودکار" : "· پیش‌فرضِ گره"}
                      </span>
                    </td>
                    <td className="text-xs">
                      {n.worker_online ? (
                        <>
                          <Badge tone={n.worker_capable ? "ok" : "warn"}>{n.worker_capable ? "آنلاین" : "قدیمی"}</Badge>{" "}
                          {n.worker_gpu ? "GPU" : "بی‌GPU؟"} {n.worker_blender || ""} {n.worker_version ? `· up3d ${n.worker_version}` : ""}
                          {!n.worker_capable && (
                            <div style={{ color: "var(--warn)" }}>پوشهٔ processing ِ این کامپیوتر قدیمی است؛ git pull کنید تا کار بگیرد</div>
                          )}
                          {n.worker_capable && n.worker_mpfb === false && (
                            <div style={{ color: "var(--warn)" }}>دادهٔ کاراکترهای MPFB نیست ⇐ صحنه‌های با مجریِ ساخته‌شده به آن نمی‌رود</div>
                          )}
                        </>
                      ) : (
                        <Badge tone="bad">آفلاین</Badge>
                      )}
                    </td>
                    <td>
                      <div className="flex flex-wrap gap-1.5">
                        {n.desired !== true && (
                          <Button size="sm" disabled={nodeBusy === n.id || !n.startable} onClick={() => void setNode3d(n, true)}>
                            روشن کن
                          </Button>
                        )}
                        {n.desired !== false && (
                          <Button size="sm" variant="ghost" disabled={nodeBusy === n.id} onClick={() => void setNode3d(n, false)}>
                            خاموش
                          </Button>
                        )}
                        {n.desired != null && (
                          <Button size="sm" variant="ghost" disabled={nodeBusy === n.id} onClick={() => void setNode3d(n, null)}>
                            خودکار
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
        {blenderZip && (
          <div className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
            دانلودِ دستیِ Blender برای ویندوز:{" "}
            <a href={blenderZip} className="underline" style={{ color: "var(--brand-strong)" }}>
              blender-windows.zip
            </a>{" "}
            (در processing\vendor\blender باز شود، طوری که vendor\blender\blender.exe باشد)
          </div>
        )}
      </Card>

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
                      {w.capabilities.version ? ` · up3d ${String(w.capabilities.version)}` : ""}
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
