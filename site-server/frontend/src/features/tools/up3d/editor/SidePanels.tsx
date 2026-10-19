import { useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Button } from "../../../../components/ui";
import { P, fa } from "../api";
import { ButtonTabs, JobLine, Muted, WaitingAlert } from "../shared";
import type { Job, Project } from "../types";

/** بخشِ ۵ «خروجی‌ها»: پیش‌نمایش (ویدئو/فریم‌ها/سه‌بعدی)، خروجی‌های دیگر (GLB، بستهٔ بازی، FBX، BLEND، فریمِ نمونه)، کارهای این پروژه. */

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
    <div>
      <ButtonTabs<PvTab>
        tabs={[
          { id: "video", label: `ویدئو${vids.length ? ` (${fa(vids.length)})` : ""}` },
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
                <Link key={j.id} to={P.job(j.id)} style={{ color: "var(--brand-strong)" }}>
                  {j.profile} #{fa(j.id)}
                </Link>
              ))}
              <a className="ms-auto u-btn u-btn-secondary u-btn-sm" href={vids[0].files["final.mp4"]} download>
                <Icon name="download" size={13} />
                دانلودِ آخرین ویدئو
              </a>
            </div>
          </>
        ) : (
          <Muted className="py-6 text-center">
            هنوز ویدئویی نیست.
            <br />
            در بخشِ ۴ «انیمیک» را شروع کنید (چند دقیقه)؛ نتیجه همین‌جا می‌آید.
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
          <Muted className="py-6 text-center">«۶ فریمِ نمونه» را بزنید: چند لحظه از ویدئو با کیفیتِ پیش‌نمایش، بی‌آن‌که کلِ ویدئو رندر شود.</Muted>
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
    </div>
  );
}

/** خروجی‌های غیرِ ویدئو — همان اکشن‌های export/contact ِ API. */
export function ExportActions({ onExport, onContact }: { onExport: (format: string) => void; onContact: () => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      <Button size="sm" variant="secondary" onClick={() => onExport("glb")} title="کلِ صحنه با انیمیشنِ پخته برای وب/بازی">
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
      <Button size="sm" variant="secondary" onClick={onContact} title="۶ لحظه از ویدئو با کیفیتِ پیش‌نمایش">
        ۶ فریمِ نمونه
      </Button>
    </div>
  );
}

export function ProjectJobs({ jobs, onCancel, onAllowCpu }: { jobs: Job[]; onCancel: (id: number) => void; onAllowCpu: (id: number) => void }) {
  const list = jobs.slice(0, 8);
  if (list.length === 0) return <Muted>هنوز کاری نیست.</Muted>;
  return (
    <div className="space-y-1.5">
      {list.map((j) => (
        <div key={j.id}>
          <JobLine
            job={j}
            action={
              !j.final ? (
                <Button size="sm" variant="danger" onClick={() => onCancel(j.id)}>
                  لغو
                </Button>
              ) : undefined
            }
          />
          {j.waiting && j.waiting.eligible.length === 0 && (
            <div className="mt-1.5">
              <WaitingAlert job={j} onAllowCpu={onAllowCpu} onCancel={onCancel} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
