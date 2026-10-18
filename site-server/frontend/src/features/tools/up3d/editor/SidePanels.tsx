import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Button, Card, SectionTitle } from "../../../../components/ui";
import { P, desc, dur, fa, label, up3d } from "../api";
import { ButtonTabs, JobLine, Muted } from "../shared";
import type { Catalog, Estimate, Job, Project } from "../types";

/** ستونِ کنارِ ویرایشگر: پیش‌نمایش (ویدئو/فریم‌ها/سه‌بعدی)، رندر و خروجی‌ها، کارهای این پروژه. */

type PvTab = "video" | "samples" | "three";

export function PreviewPanel({ proj }: { proj: Project }) {
  const [tab, setTab] = useState<PvTab>("video");
  const vids = proj.jobs.filter((j) => j.kind === "render" && j.state === "COMPLETED" && j.files["final.mp4"]);
  const contact = proj.jobs.find((j) => j.kind === "contact" && j.state === "COMPLETED");
  const imgs = contact
    ? Object.entries(contact.files)
        .filter(([k]) => /contact_\d+\.png$/.test(k))
        .map(([, v]) => v)
    : [];
  const exps = proj.jobs.filter((j) => j.kind === "export" && j.state === "COMPLETED").slice(0, 5);

  return (
    <Card>
      <ButtonTabs<PvTab>
        tabs={[
          { id: "video", label: "ویدئو" },
          { id: "samples", label: "فریم‌های نمونه" },
          { id: "three", label: "سه‌بعدی (وب/بازی)" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "video" &&
        (vids.length ? (
          <>
            <video className="u3d-video" controls playsInline preload="metadata" poster={vids[0].files["poster.jpg"] || undefined} src={vids[0].files["final.mp4"]} />
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
              {vids.slice(0, 6).map((j) => (
                <a key={j.id} href={j.files["final.mp4"]} target="_blank" rel="noreferrer" style={{ color: "var(--brand-strong)" }}>
                  {j.profile} #{fa(j.id)}
                </a>
              ))}
              <a className="ms-auto" href={vids[0].files["final.mp4"]} download style={{ color: "var(--brand-strong)" }}>
                دانلود
              </a>
            </div>
          </>
        ) : (
          <Muted className="py-6 text-center">
            هنوز ویدئویی نیست.
            <br />
            «انیمیک» را بزنید (چند دقیقه).
          </Muted>
        ))}
      {tab === "samples" &&
        (imgs.length ? (
          <div className="u3d-thumbs">
            {imgs.map((u) => (
              <a key={u} href={u} target="_blank" rel="noreferrer">
                <img src={u} alt="" />
              </a>
            ))}
          </div>
        ) : (
          <Muted className="py-6 text-center">«۶ فریمِ نمونه» را بزنید: چند لحظه از ویدئو با کیفیتِ پیش‌نمایش.</Muted>
        ))}
      {tab === "three" &&
        (exps.length ? (
          <div className="space-y-1.5">
            {exps.map((j) => {
              const keys = Object.keys(j.files).filter((k) => k.startsWith("scene."));
              return (
                <div key={j.id} className="rounded-xl px-3 py-2 text-sm" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
                  <b style={{ color: "var(--text)" }}>{keys[0] || "خروجی"}</b>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                    {keys.map((k) => (
                      <a key={k} href={j.files[k]} download style={{ color: "var(--brand-strong)" }}>
                        دانلودِ {k}
                      </a>
                    ))}
                    {keys.some((k) => k.endsWith(".glb")) && (
                      <Link className="u-btn u-btn-secondary u-btn-sm" to={P.viewer(j.id)}>
                        نمایشگرِ سه‌بعدی / بازی
                      </Link>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <Muted className="py-6 text-center">«خروجیِ GLB» را بزنید: کلِ صحنه با انیمیشن برای وب، Unity، Godot، Unreal یا Blender.</Muted>
        ))}
    </Card>
  );
}

export function RenderPanel({
  cat,
  pid,
  version,
  onRender,
  onExport,
  onContact,
}: {
  cat: Catalog;
  pid: number;
  version: number | null;
  onRender: (profile: string, allowCpu: boolean) => void;
  onExport: (format: string) => void;
  onContact: () => void;
}) {
  const [est, setEst] = useState<Record<string, Estimate>>({});

  // تخمین از آمارِ واقعیِ کارگرها؛ با هر نسخهٔ تازه (مدتِ تازه) دوباره
  useEffect(() => {
    let alive = true;
    (async () => {
      for (const p of cat.render_profile) {
        try {
          const e = await up3d.estimate(p.id, pid);
          if (alive) setEst((prev) => ({ ...prev, [p.id]: e }));
        } catch {
          /* بی‌تخمین */
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [cat, pid, version]);

  const click = (profile: string) => {
    const e = est[profile];
    if (e && !e.available && e.cpu_seconds) {
      if (!window.confirm(`کارگرِ GPU آنلاین نیست. روی CPU ِ سرور اجرا شود؟\nتخمین: حدودِ ${dur(e.cpu_seconds)} (سایت‌های دیگر کند نمی‌شوند؛ اولویتِ پایین)`)) return;
      onRender(profile, true);
      return;
    }
    onRender(profile, false);
  };

  return (
    <Card>
      <SectionTitle>رندر</SectionTitle>
      <Muted className="text-xs">
        اول «انیمیک» برای وارسیِ حرکت و زمان (سریع)، بعد «پیش‌نمایش» با نورِ واقعی. کیفیت‌های بالاتر روی کارگرِ GPU اجرا می‌شوند.
      </Muted>
      <div className="mt-2 space-y-1.5">
        {cat.render_profile.map((p) => {
          const e = est[p.id];
          const quick = p.id === "animatic" || p.id === "preview";
          return (
            <div key={p.id} className="rounded-xl px-3 py-2" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
              <div className="flex items-center justify-between gap-2">
                <b className="text-sm" style={{ color: "var(--text)" }}>
                  {label(p)}
                </b>
                <Button size="sm" variant={quick ? "primary" : "secondary"} onClick={() => click(p.id)}>
                  رندر
                </Button>
              </div>
              <div className="mt-0.5 text-xs" style={{ color: "var(--text-3)" }}>
                {desc(p)}
                {e && (
                  <>
                    {" · "}
                    {fa(e.frames)} فریم ·{" "}
                    {e.available ? (
                      <>
                        ~{dur(e.seconds)} روی <b>{e.worker}</b>
                      </>
                    ) : (
                      <>
                        <span style={{ color: "var(--warn)" }}>کارگرِ GPU آنلاین نیست</span>
                        {e.cpu_seconds ? ` · روی CPU ِ سرور ~${dur(e.cpu_seconds)}` : ""}
                      </>
                    )}
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Button size="sm" variant="secondary" onClick={() => onExport("glb")}>
          خروجیِ GLB (وب/بازی)
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onExport("game_pack")} title="کاراکتر + هر حرکت یک کلیپِ جدا برای Unity/Unreal/Godot">
          بستهٔ بازیِ کاراکتر
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onExport("fbx")}>
          FBX
        </Button>
        <Button size="sm" variant="secondary" onClick={() => onExport("blend")}>
          BLEND
        </Button>
        <Button size="sm" variant="secondary" onClick={onContact}>
          ۶ فریمِ نمونه
        </Button>
      </div>
    </Card>
  );
}

export function ProjectJobs({ jobs, onCancel }: { jobs: Job[]; onCancel: (id: number) => void }) {
  const list = jobs.slice(0, 8);
  return (
    <Card>
      <SectionTitle>کارهای این پروژه</SectionTitle>
      {list.length === 0 ? (
        <Muted>هنوز کاری نیست.</Muted>
      ) : (
        <div className="space-y-1.5">
          {list.map((j) => (
            <JobLine
              key={j.id}
              job={j}
              action={
                !j.final ? (
                  <Button size="sm" variant="danger" onClick={() => onCancel(j.id)}>
                    لغو
                  </Button>
                ) : undefined
              }
            />
          ))}
        </div>
      )}
    </Card>
  );
}
