import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../components/Icon";
import { openTool } from "../../../components/Layout";
import { Badge, Card, EmptyState, ErrorBox, SectionTitle, Spinner, Stat } from "../../../components/ui";
import { P, ago, errMsg, fa, up3d } from "./api";
import { JobLine, Muted, usePoll } from "./shared";
import type { Dashboard, Job } from "./types";

/** داشبورد: معرفی، شمارِ کتابخانه، وضعیتِ AI و کارگرها، کارهای در جریان (زنده) و پروژه‌ها. */
export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [active, setActive] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    up3d
      .dashboard()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(errMsg(e)));
    return () => {
      alive = false;
    };
  }, []);

  usePoll(
    async () => {
      setActive(await up3d.jobs(true));
    },
    4000,
    [],
  );

  if (!data) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const { ai, counts } = data;

  return (
    <div className="space-y-5">
      <ErrorBox message={error} />

      <Card>
        <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr]">
          <div>
            <h2 className="text-xl font-black" style={{ color: "var(--text)" }}>
              از یک جمله تا یک تبلیغِ سه‌بعدیِ کامل
            </h2>
            <p className="mt-2 text-sm leading-7" style={{ color: "var(--text-2)" }}>
              بنویسید چه محصولی و چه پیامی؛ کارگردانِ هوشِ مصنوعی صحنه، بازیگر، حرکت، دوربین و گفتارِ فارسی را می‌چیند،
              موتورِ سه‌بعدی (Blender) آن را با نور و سایهٔ واقعی رندر می‌کند و صدا، لب و نوشته‌های فارسی روی آن مونتاژ می‌شود.
              همهٔ این‌ها با کد (SDK/API) و ویرایشگرِ گرافیکی هم قابلِ ساخت و ویرایش است.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link to={P.newProject()} className="u-btn u-btn-primary">
                <Icon name="plus" size={15} />
                ساختِ تبلیغِ تازه
              </Link>
              <Link to={P.assets()} className="u-btn u-btn-secondary">
                کتابخانهٔ کاراکتر، حرکت و محیط
              </Link>
              <Link to={P.docs()} className="u-btn u-btn-ghost">
                راهنما، API و SDK
              </Link>
            </div>
          </div>
          <div className="u-stat-row grid grid-cols-2 gap-3">
            <Stat value={fa(counts.character ?? 0)} label="کاراکتر" />
            <Stat value={fa(counts.motion ?? 0)} label="حرکت در کتابخانه" />
            <Stat value={fa(counts.environment ?? 0)} label="محیط" hint={`${fa(counts.product ?? 0)} شکلِ محصول`} />
            <Stat value={fa(counts.render_profile ?? 0)} label="سطحِ کیفیتِ رندر" />
          </div>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <SectionTitle>هوشِ مصنوعی و صدا</SectionTitle>
          {ai.ready ? (
            <>
              <p className="text-sm" style={{ color: "var(--text-2)" }}>
                <Badge tone="ok">وصل</Badge> مدلِ متن: <b className="u3d-mono">{ai.model}</b> · صدا:{" "}
                <b className="u3d-mono">{ai.tts_model}</b>
              </p>
              <Muted className="u3d-mono mt-1">{ai.base_url}</Muted>
            </>
          ) : (
            <p className="text-sm" style={{ color: "var(--text-2)" }}>
              <Badge tone="warn">تنظیم نشده</Badge> بدونِ کلید، قالب‌های آماده و صدای بی‌صدا کار می‌کنند.
            </p>
          )}
          <button
            type="button"
            onClick={() => openTool("/admin/up3d/aisettings/1/change/")}
            className="u-btn u-btn-secondary u-btn-sm mt-3"
          >
            تنظیم در جنگو ادمین
          </button>
        </Card>

        <Card>
          <SectionTitle>کارگرهای رندر</SectionTitle>
          {data.workers.length === 0 ? (
            <Muted>هنوز کارگری نیست.</Muted>
          ) : (
            <div className="space-y-1.5">
              {data.workers.map((w) => (
                <div key={w.id} className="flex items-center justify-between gap-2 text-sm" style={{ color: "var(--text-2)" }}>
                  <span>{w.name}</span>
                  <span className="flex gap-1">
                    <Badge tone={w.has_gpu ? "ok" : "neutral"}>{w.has_gpu ? "GPU" : "CPU"}</Badge>
                    <Badge tone={w.online ? "ok" : "bad"}>{w.online ? "آنلاین" : "آفلاین"}</Badge>
                  </span>
                </div>
              ))}
            </div>
          )}
          <Link to={P.workers()} className="u-btn u-btn-secondary u-btn-sm mt-3">
            افزودنِ کارگرِ GPU
          </Link>
        </Card>

        <Card>
          <SectionTitle>کارهای در جریان</SectionTitle>
          {active === null ? (
            <Muted>…</Muted>
          ) : active.length === 0 ? (
            <Muted>کاری در جریان نیست.</Muted>
          ) : (
            <div className="space-y-1.5">
              {active.slice(0, 5).map((j) => (
                <JobLine key={j.id} job={j} />
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="flex items-center justify-between">
        <SectionTitle>پروژه‌ها</SectionTitle>
        <Link to={P.newProject()} className="u-btn u-btn-secondary u-btn-sm">
          <Icon name="plus" size={14} />
          پروژهٔ تازه
        </Link>
      </div>

      {data.projects.length === 0 ? (
        <Card>
          <EmptyState icon="film" title="هنوز پروژه‌ای نیست" action={<Link to={P.newProject()} className="u-btn u-btn-primary u-btn-sm">اولین تبلیغ را بسازید</Link>} />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {data.projects.map((p) => (
            <Link key={p.id} to={P.project(p.id)} className="no-underline">
              <Card padded={false} hover>
                <div className="u3d-poster" style={{ aspectRatio: "9 / 12", backgroundImage: p.poster ? `url('${p.poster}')` : undefined }}>
                  {!p.poster && <Icon name="film" size={34} />}
                </div>
                <div className="px-3 py-2.5">
                  <b className="block truncate text-sm" style={{ color: "var(--text)" }}>
                    {p.title}
                  </b>
                  <div className="text-xs" style={{ color: "var(--text-3)" }}>
                    {p.version ? (
                      <>
                        نسخهٔ {fa(p.version)} ·{" "}
                        <span style={{ color: p.valid ? "var(--ok)" : "var(--bad)" }}>{p.valid ? "معتبر" : "ایراد دارد"}</span>
                      </>
                    ) : (
                      "در حالِ برنامه‌ریزی…"
                    )}
                  </div>
                  <div className="text-xs" style={{ color: "var(--text-3)" }}>
                    {ago(p.updated)}
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
