import { FormEvent, ReactNode, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Spinner, Table, TextArea } from "../../../components/ui";
import { api, BASE, fa, fmtShort, pUrl, studioError, truncate } from "./api";
import { Check, Help, Loading, Mono, proposalTone, SectionHead } from "./common";
import { useProject } from "./shell";
import type { AiHomeResp, ProposalT } from "./types";

/** خانهٔ هوشِ مصنوعیِ هر پروژه: ساختِ فرانت، دستیارِ مدل، فهرستِ پیشنهادها */
export default function AiHomePage() {
  const { slug, project } = useProject();
  const navigate = useNavigate();
  const [data, setData] = useState<AiHomeResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [brief, setBrief] = useState("");
  const [shell, setShell] = useState(true);
  const [samples, setSamples] = useState(true);
  const [pages, setPages] = useState<number[]>([]);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState<"frontend" | "models" | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AiHomeResp>(`/studio/projects/${slug}/ai/`)
      .then((r) => {
        setData(r.data);
        setBrief(r.data.project.description);
        setPages(r.data.pages.map((p) => p.id));
      })
      .catch((err) => setError(studioError(err)));
  }, [slug]);

  if (!data) return <Loading error={error} />;
  const ready = data.cfg.is_ready;

  async function send(act: "frontend" | "models", e: FormEvent) {
    e.preventDefault();
    setBusy(act);
    setFormError(null);
    try {
      const body = act === "frontend" ? { act, brief, shell, samples, pages } : { act, description };
      const { data: d } = await api.post<{ proposal: ProposalT }>(`/studio/projects/${slug}/ai/`, body);
      navigate(pUrl(slug, `ai/proposal/${d.proposal.id}`));
    } catch (err) {
      setFormError(studioError(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {!ready ? (
        <Alert
          tone="warn"
          action={
            <Link to={`${BASE}/ai/settings`} className="no-underline">
              <Button size="sm">تنظیماتِ هوشِ مصنوعی</Button>
            </Link>
          }
        >
          هنوز سرویسِ هوشِ مصنوعی تنظیم نشده.
        </Alert>
      ) : (
        <Alert
          tone="info"
          action={
            <Link to={`${BASE}/ai/settings`} className="no-underline">
              <Button variant="ghost" size="sm">عوض کن</Button>
            </Link>
          }
        >
          سرویس: <b>{data.cfg.provider_display}</b> · مدل <Mono>{data.cfg.model}</Mono>
        </Alert>
      )}
      <ErrorBox message={formError} />

      <div className="grid gap-4 lg:grid-cols-2">
        {!project.is_imported ? (
          <AiCard>
            <form onSubmit={(e) => send("frontend", e)} className="space-y-3">
              <h3 className="flex items-center gap-2 text-base font-bold" style={{ color: "var(--text)" }}>
                <Icon name="image" size={18} />
                ساختِ فرانتِ اولیه (فازِ ۰۶)
              </h3>
              <p className="text-sm" style={{ color: "var(--text-3)" }}>
                هدر، فوتر، CSSِ مشترک و بدنهٔ صفحه‌ها از روی توضیح ساخته می‌شود. بک‌اند دست نمی‌خورد.
              </p>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                  توضیحِ فروشگاه و حس‌وحالِ سایت
                </span>
                <TextArea value={brief} onChange={(e) => setBrief(e.target.value)} rows={4} />
              </label>
              <div className="flex flex-wrap gap-4">
                <Check label="هدر، فوتر و پوستهٔ CSS" checked={shell} onChange={setShell} />
                <Check label="دسته و محصولِ نمونه (برای دیدنِ ظاهر)" checked={samples} onChange={setSamples} />
              </div>
              <div>
                <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                  کدام صفحه‌ها
                </span>
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  {data.pages.map((pg) => (
                    <Check
                      key={pg.id}
                      label={pg.title}
                      checked={pages.includes(pg.id)}
                      onChange={(on) => setPages(on ? [...pages, pg.id] : pages.filter((x) => x !== pg.id))}
                    />
                  ))}
                </div>
              </div>
              <Button type="submit" disabled={!ready || busy !== null}>
                <Icon name="sparkle" size={14} />
                {busy === "frontend" ? "در حالِ فرستادن…" : "بساز — پیشنهاد بده"}
              </Button>
              <Help>هر صفحه یک درخواستِ جدا به مدل است تا متن کوچک و دقیق بماند. چند دقیقه طول می‌کشد؛ صفحهٔ پیشنهاد خودش تازه می‌شود.</Help>
            </form>
          </AiCard>
        ) : (
          <AiCard>
            <h3 className="text-base font-bold" style={{ color: "var(--text)" }}>
              ویرایشِ قالب‌ها
            </h3>
            <p className="my-2 text-sm" style={{ color: "var(--text-3)" }}>
              در پروژهٔ واردشده هر قالب را از «فرانت» باز کن و با کادرِ بنفش ویرایش کن.
            </p>
            <Link to={pUrl(slug, "frontend")} className="no-underline">
              <Button>قالب‌ها</Button>
            </Link>
          </AiCard>
        )}

        <AiCard>
          <form onSubmit={(e) => send("models", e)} className="space-y-3">
            <h3 className="flex items-center gap-2 text-base font-bold" style={{ color: "var(--text)" }}>
              <Icon name="box" size={18} />
              دستیارِ مدل (بک‌اند)
            </h3>
            <p className="text-sm" style={{ color: "var(--text-3)" }}>
              بگو چه امکانی می‌خواهی؛ اپ، مدل، فیلد و رابطه‌ها پیشنهاد می‌شود. بعد از تأیید، مثلِ ساختِ دستی در «اپ‌ها و
              مدل‌ها» می‌نشیند.
            </p>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                چه می‌خواهی؟
              </span>
              <TextArea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={4}
                placeholder="مثلاً: مشتری‌ها بتوانند برای هر محصول نظر و امتیاز (۱ تا ۵) بگذارند و ادمین تأییدشان کند؛ کدِ تخفیف با درصد و تاریخِ انقضا"
              />
            </label>
            <Button type="submit" disabled={!ready || busy !== null || !description.trim()}>
              <Icon name="sparkle" size={14} />
              {busy === "models" ? "در حالِ فرستادن…" : "پیشنهاد بده"}
            </Button>
          </form>
        </AiCard>
      </div>

      <Card padded={false}>
        <div className="px-5 pt-5">
          <SectionHead title="پیشنهادها" hint="هیچ‌کدام بدونِ تأییدِ تو اعمال نشده‌اند" />
        </div>
        {data.proposals.length === 0 ? (
          <EmptyState title="هنوز پیشنهادی نیست." />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>زمان</th>
                <th>کار</th>
                <th>درخواست</th>
                <th>تغییرها</th>
                <th>وضعیت</th>
              </tr>
            </thead>
            <tbody>
              {data.proposals.map((pr) => (
                <tr key={pr.id}>
                  <td className="whitespace-nowrap">{fmtShort(pr.created_at)}</td>
                  <td>
                    <Link to={pUrl(slug, `ai/proposal/${pr.id}`)} style={{ color: "var(--brand-strong)" }}>
                      {pr.title || pr.task_display}
                    </Link>
                  </td>
                  <td style={{ color: "var(--text-3)" }}>{truncate(pr.prompt_text, 70)}</td>
                  <td className="u-num">{fa(pr.change_count)}</td>
                  <td>
                    <Badge tone={proposalTone(pr.status)}>
                      {pr.status === "running" && <Spinner size={11} />}
                      {pr.status_display}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function AiCard({ children }: { children: ReactNode }) {
  return (
    <div
      className="rounded-2xl p-5"
      style={{
        background: "linear-gradient(135deg, var(--brand-soft), transparent)",
        border: "1px solid color-mix(in srgb, var(--brand) 35%, transparent)",
      }}
    >
      {children}
    </div>
  );
}
