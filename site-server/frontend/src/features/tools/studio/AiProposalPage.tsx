import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, Spinner, Table } from "../../../components/ui";
import { api, fa, fmtDate, pUrl, studioError, truncate } from "./api";
import { Check, confirmDo, DiffView, docHtml, Help, Loading, Mono, Pre, PreviewFrame, proposalTone, SectionHead, StickyBar, stripTemplate, Tabs } from "./common";
import { useProject } from "./shell";
import type { ChangeT, ProposalResp, ProposalT, Shared } from "./types";

const SAMPLE =
  '<section class="section"><div class="wrap"><h1>نمونهٔ بدنه</h1><p>متنِ نمونه.</p><a class="btn" href="#">دکمه</a></div></section>';

/** «بعد» همهٔ تغییرهای همین پیشنهاد را با هم نشان می‌دهد (مثلاً هدرِ تازه + CSSِ تازه) */
function afterShared(shared: Shared, changes: ChangeT[]): Shared {
  const after = { ...shared };
  for (const c of changes) {
    if (c.target === "shared_css") after.base_css = c.new;
    if (c.target === "shared_header") after.header = c.new;
    if (c.target === "shared_footer") after.footer = c.new;
  }
  return after;
}

function cssOf(c: ChangeT, changes: ChangeT[]): ChangeT | undefined {
  return changes.find(
    (x) =>
      (c.target === "page_body" && x.target === "page_css" && x.page === c.page) ||
      (c.target === "view_template" && x.target === "view_css" && x.view === c.view),
  );
}

function previewHtml(c: ChangeT, side: "old" | "new", shared: Shared, changes: ChangeT[]): string {
  const before = shared;
  const after = afterShared(shared, changes);
  const st = side === "new" ? after : before;
  if (c.target === "page_file") return stripTemplate(side === "new" ? c.new : c.old);
  if (c.target === "shared_header" || c.target === "shared_footer") return docHtml(st, SAMPLE, "");
  const cssC = cssOf(c, changes);
  const css = cssC ? (side === "new" ? cssC.new : cssC.old) : "";
  return docHtml(st, side === "new" ? c.new : c.old, css);
}

/** صفحهٔ پیشنهادِ AI: Diff، پیش‌نمایشِ قبل/بعد، اعمال/رد/بازگردانی */
export default function AiProposalPage() {
  const { slug, notify, reload } = useProject();
  const { pk = "" } = useParams<{ pk: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<ProposalResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<string>("");

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<ProposalResp>(`/studio/projects/${slug}/ai/proposals/${pk}/`);
      setData(d);
      setSelected(d.changes.filter((c) => c.valid).map((c) => c.id));
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug, pk]);

  useEffect(() => {
    void load();
  }, [load]);

  // تا وقتی AI در حالِ کار است هر ۲٫۵ ثانیه وضعیت پرسیده می‌شود
  useEffect(() => {
    if (!data || data.proposal.status !== "running") return;
    const id = window.setInterval(async () => {
      try {
        const { data: s } = await api.get<{ status: string; calls: number; changes: number }>(`/studio/projects/${slug}/ai/proposals/${pk}/status/`);
        if (s.status !== "running") void load();
        else setProgress(`${fa(s.calls)} درخواست فرستاده شده، ${fa(s.changes)} تغییر آماده — صبر کن…`);
      } catch {
        /* قطعیِ گذرا؛ دورِ بعد */
      }
    }, 2500);
    return () => window.clearInterval(id);
  }, [data, slug, pk, load]);

  if (!data) return <Loading error={error} />;
  const prop = data.proposal;

  async function post(action: "apply" | "reject" | "revert") {
    if (action === "revert" && !confirmDo("تغییرهای این پیشنهاد برگردانده شود؟")) return;
    setBusy(action);
    try {
      const body = action === "apply" ? { change: selected } : {};
      const { data: d } = await api.post<ProposalResp & { proposal: ProposalT; message?: string; ok?: boolean }>(
        `/studio/projects/${slug}/ai/proposals/${pk}/${action}/`,
        body,
      );
      if (action === "reject") {
        notify(d.message ?? "پیشنهاد رد شد؛ هیچ‌چیز تغییر نکرد.", "info");
        navigate(pUrl(slug, "ai"));
        return;
      }
      setData({ ...data!, ...d });
      setSelected(d.changes.filter((c) => c.valid).map((c) => c.id));
      if (d.message) notify(d.message, d.ok ? "ok" : "warn");
      await reload(); // وضعیتِ پروژه (تولیدِ کد) عوض شده
    } catch (err) {
      notify(studioError(err), "bad");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
        <Link to={pUrl(slug, "ai")} className="u-back">
          <Icon name="back" size={14} />
          هوشِ مصنوعی
        </Link>
        <span>›</span>
        <b style={{ color: "var(--text)" }}>{truncate(prop.title || prop.task_display, 50)}</b>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={proposalTone(prop.status)}>
            {prop.is_running && <Spinner size={11} />}
            {prop.status_display}
          </Badge>
          <div className="min-w-[200px] flex-1">
            <b style={{ color: "var(--text)" }}>{prop.task_display}</b>
            <div className="text-sm" style={{ color: "var(--text-3)" }}>
              «{truncate(prop.prompt_text, 200)}»
            </div>
          </div>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            {prop.provider_model} · {fa(prop.calls)} فراخوانی · {fmtDate(prop.created_at)}
          </span>
        </div>
      </Card>

      {prop.is_running && (
        <Card className="text-center">
          <div className="py-6">
            <Spinner size={38} />
            <h3 className="mt-4 text-base font-bold" style={{ color: "var(--text)" }}>
              هوشِ مصنوعی در حالِ کار است…
            </h3>
            <p className="mt-1 text-sm" style={{ color: "var(--text-3)" }}>
              {progress || `${fa(prop.calls)} درخواست فرستاده شده. این صفحه خودش تازه می‌شود؛ می‌توانی ببندی و بعداً از «هوشِ مصنوعی» برگردی.`}
            </p>
          </div>
        </Card>
      )}
      {prop.status === "failed" && (
        <Card>
          <SectionHead tone="bad" title="ناموفق" />
          <Pre text={prop.error} maxHeight={240} rtl />
          <Help>اگر خطا از اتصال یا کلید است، «تنظیماتِ هوشِ مصنوعی» ⇒ «آزمونِ اتصال». بعد دوباره بفرست.</Help>
        </Card>
      )}
      {prop.summary && (
        <Alert tone="info">
          <span style={{ whiteSpace: "pre-line" }}>{prop.summary}</span>
        </Alert>
      )}

      {data.changes.map((ch) => (
        <ChangeCard
          key={ch.id}
          ch={ch}
          data={data}
          selectable={prop.status === "pending" && ch.valid}
          selected={selected.includes(ch.id)}
          onSelect={(on) => setSelected(on ? [...selected, ch.id] : selected.filter((x) => x !== ch.id))}
        />
      ))}

      {data.changes.length > 0 && (
        <StickyBar>
          {prop.status === "pending" ? (
            <>
              <Button onClick={() => post("apply")} disabled={!prop.can_apply || busy !== null || selected.length === 0}>
                {busy === "apply" ? "در حالِ اعمال و تولیدِ کد…" : "اعمالِ تغییرهای انتخاب‌شده + تولیدِ کد"}
              </Button>
              <Button variant="danger" onClick={() => post("reject")} disabled={busy !== null}>
                رد کن
              </Button>
              <span className="text-sm" style={{ color: "var(--text-3)" }}>
                اعمال = نوشتن در تعریف‌ها، تولیدِ کد و ثبتِ یک نسخه. بعداً هم می‌شود بازگردانی کرد.
              </span>
            </>
          ) : prop.status === "applied" ? (
            <>
              <Badge tone="ok">اعمال شد {fmtDate(prop.applied_at)}</Badge>
              <Button variant="ghost" onClick={() => post("revert")} disabled={busy !== null}>
                {busy === "revert" ? "…" : "بازگردانی (برگشت به قبل)"}
              </Button>
              <Link to={pUrl(slug, "preview")} className="no-underline">
                <Button variant="ghost">پیش‌نمایشِ زنده</Button>
              </Link>
              <Link to={pUrl(slug, "history")} className="no-underline">
                <Button variant="ghost">تاریخچه</Button>
              </Link>
            </>
          ) : (
            <>
              <Badge>{prop.status_display}</Badge>
              <Link to={pUrl(slug, "ai")} className="no-underline">
                <Button variant="ghost">بازگشت</Button>
              </Link>
            </>
          )}
        </StickyBar>
      )}
    </div>
  );
}

type Pane = "pv" | "diff" | "new";

function ChangeCard({
  ch,
  data,
  selectable,
  selected,
  onSelect,
}: {
  ch: ChangeT;
  data: ProposalResp;
  selectable: boolean;
  selected: boolean;
  onSelect: (on: boolean) => void;
}) {
  const [pane, setPane] = useState<Pane>(ch.is_html ? "pv" : "diff");
  const spec = data.spec ?? [];
  const products = data.samples.products ?? [];

  return (
    <Card>
      <SectionHead
        title={
          <span className="inline-flex flex-wrap items-center gap-2">
            {selectable && <Check label="اعمال شود" checked={selected} onChange={onSelect} />}
            {ch.label}
          </span>
        }
        action={
          <>
            <Badge tone="brand">{ch.target_display}</Badge>
            {!ch.valid ? <Badge tone="bad">رد شد / نامعتبر</Badge> : ch.issues.length ? <Badge tone="warn">هشدار</Badge> : <Badge tone="ok">وارسی سالم</Badge>}
            {ch.unchanged && <Badge>بی‌تغییر</Badge>}
          </>
        }
      />
      {ch.issues.length > 0 && (
        <ul className="mb-3 list-disc ps-5 text-sm" style={{ color: ch.valid ? "var(--warn)" : "var(--bad)" }}>
          {ch.issues.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      )}

      {ch.target === "sample_data" ? (
        <>
          <Table>
            <thead>
              <tr>
                <th>محصول</th>
                <th>دسته</th>
                <th>قیمت (تومان)</th>
                <th>موجودی</th>
              </tr>
            </thead>
            <tbody>
              {products.map((x, i) => (
                <tr key={i}>
                  <td>
                    {x.name}
                    <div className="text-xs" style={{ color: "var(--text-3)" }}>
                      {truncate(x.description, 90)}
                    </div>
                  </td>
                  <td>
                    <Mono>{x.category}</Mono>
                  </td>
                  <td className="u-num">{x.price}</td>
                  <td className="u-num">{x.stock}</td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Help>
            در <Mono>fixtures/sample_data.json</Mono> ِ پروژه نوشته و با <Mono>manage.py load_sample_data</Mono> بارگذاری می‌شود (در ZIP هم هست).
          </Help>
        </>
      ) : ch.target === "model_spec" ? (
        spec.map((a) => (
          <div key={a.name} className="mb-3">
            <b className="font-mono" dir="ltr">
              apps/{a.name}
            </b>{" "}
            <span className="text-sm" style={{ color: "var(--text-3)" }}>
              {a.verbose}
            </span>
            {a.models.map((m) => (
              <div key={m.name} className="my-2">
                <Table>
                  <thead>
                    <tr>
                      <th colSpan={3}>
                        <span className="font-mono" dir="ltr">
                          {m.name}
                        </span>{" "}
                        — {m.verbose}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.fields.map((f) => (
                      <tr key={f.name}>
                        <td className="font-mono" dir="ltr">
                          {f.name}
                        </td>
                        <td>{f.verbose}</td>
                        <td className="font-mono text-xs" dir="ltr">
                          {f.type}
                          {f.related_model ? ` → ${f.related_model}` : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            ))}
          </div>
        ))
      ) : (
        <>
          <Tabs<Pane>
            tabs={[
              ...(ch.is_html ? [{ key: "pv" as Pane, label: "پیش‌نمایشِ قبل / بعد" }] : []),
              { key: "diff", label: "Diff" },
              { key: "new", label: "کدِ جدید" },
            ]}
            active={pane}
            onChange={setPane}
          />
          {pane === "pv" && ch.is_html && (
            <div className="grid gap-3 lg:grid-cols-2">
              <div>
                <div className="mb-1 text-xs" style={{ color: "var(--text-3)" }}>
                  قبل
                </div>
                <PreviewFrame html={previewHtml(ch, "old", data.shared, data.changes)} height={440} title="قبل" />
              </div>
              <div>
                <div className="mb-1 text-xs" style={{ color: "var(--text-3)" }}>
                  بعد
                </div>
                <PreviewFrame html={previewHtml(ch, "new", data.shared, data.changes)} height={440} title="بعد" />
              </div>
            </div>
          )}
          {pane === "diff" && <DiffView text={ch.diff} />}
          {pane === "new" && <Pre text={ch.new} />}
        </>
      )}
    </Card>
  );
}
