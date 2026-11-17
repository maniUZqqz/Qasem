import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, Input, Spinner, fa } from "../../../../components/ui";
import { g, problem, useGet } from "../../api";
import { faAgo, faDateTime } from "../../format";
import { ConfirmDialog } from "../../components/Modal";
import MissionForm from "../components/MissionForm";
import RunPanel from "../components/RunPanel";
import { Section } from "../components/bits";
import { useFinder } from "../FinderLayout";
import type { FinderMeta, Mission, Paged, PresetInfo } from "../types";

const SCHEDULE_LABEL = (d: number) => (d === 0 ? "بدونِ تکرار" : d === 1 ? "هر روز" : d === 7 ? "هر هفته" : d === 14 ? "هر دو هفته" : d === 30 ? "هر ماه" : `هر ${fa(d)} روز`);

/** «مأموریت‌ها»: whom to find, run it, watch it. Presets (Chagher's gyms, cafes in Isfahan ...) are one click; any mission can be made by hand. */
export default function MissionsPage() {
  const { meta, reload: reloadMeta } = useFinder();
  const [params, setParams] = useSearchParams();
  const list = useGet<Paged<Mission>>("/finder/missions/", undefined, { poll: 8000 });
  const [form, setForm] = useState<{ open: boolean; mission: Mission | null }>({ open: false, mission: null });
  const [formKey, setFormKey] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [archive, setArchive] = useState<Mission | null>(null);
  const [probe, setProbe] = useState<FinderMeta["engines"] | null>(null);
  const openRun = Number(params.get("run")) || null;
  const [neshanKey, setNeshanKey] = useState("");

  const showRun = (id: number | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("run", String(id));
    else next.delete("run");
    setParams(next, { replace: true });
  };

  const fromPreset = async (p: PresetInfo, start: boolean) => {
    setBusy(p.key + (start ? "-run" : ""));
    setNotice(null);
    try {
      const r = await g.post<{ mission: Mission; run: { id: number } | null }>("/finder/missions/from-preset/", { preset: p.key, start });
      setNotice({ tone: "ok", text: start ? "مأموریت ساخته شد و اجرا در صف است." : "مأموریت ساخته شد." });
      list.reload();
      if (r.run) showRun(r.run.id);
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    } finally {
      setBusy(null);
    }
  };

  const startRun = async (m: Mission) => {
    setBusy(`run-${m.id}`);
    setNotice(null);
    try {
      const run = await g.post<{ id: number }>(`/finder/missions/${m.id}/run/`);
      list.reload();
      showRun(run.id);
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    } finally {
      setBusy(null);
    }
  };

  const toggleSchedule = async (m: Mission) => {
    try {
      await g.patch(`/finder/missions/${m.id}/`, { enabled: !m.enabled });
      list.reload();
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    }
  };

  const doArchive = async () => {
    if (!archive) return;
    try {
      await g.del(`/finder/missions/${archive.id}/`);
      setArchive(null);
      list.reload();
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
      setArchive(null);
    }
  };

  const testEngines = async () => {
    setBusy("probe");
    try {
      setProbe(await g.post<FinderMeta["engines"]>("/finder/engines/probe/"));
      reloadMeta();
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    } finally {
      setBusy(null);
    }
  };

  const saveNeshan = async (remove: boolean) => {
    setBusy("neshan");
    try {
      if (remove) await g.del("/finder/neshan-key/");
      else await g.put("/finder/neshan-key/", { api_key: neshanKey.trim() });
      setNeshanKey("");
      reloadMeta();
      setNotice({ tone: "ok", text: remove ? "کلیدِ نشان برداشته شد." : "کلیدِ نشان ذخیره شد." });
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    } finally {
      setBusy(null);
    }
  };

  const missions = list.data?.results ?? [];
  const neshanSet = !!meta?.sources.find((s) => s.key === "neshan")?.key_set;
  const engines = probe ?? meta?.engines ?? {};

  return (
    <div className="space-y-6" data-testid="finder-missions">
      <Alert tone="info" title="مشتری‌یاب چه می‌کند؟">
        شما می‌گویید چه کسب‌وکاری را کجا پیدا کند (نوع، کلیدواژه، شهر)؛ خزنده از نقشه، فهرست‌های عمومی، جست‌وجوی وب و سایتِ خودِ کسب‌وکارها اطلاعاتِ تماسِ عمومی را جمع می‌کند، تکراری‌ها را یکی می‌کند، به هر مورد امتیازِ تناسب با دلیلِ فارسی می‌دهد و لید می‌سازد. <b>هیچ پیامی فرستاده نمی‌شود</b>؛ پیام فقط بعد از تأییدِ شما، آن هم از مسیرِ کمپین.
      </Alert>

      {notice && (
        <Alert tone={notice.tone === "ok" ? "ok" : "bad"} action={<Button variant="ghost" size="sm" onClick={() => setNotice(null)}>بستن</Button>}>
          {notice.text}
        </Alert>
      )}

      <Section title="شروعِ سریع" hint="پیش‌تنظیم‌ها؛ هر کدام یک مأموریتِ آماده است که همه‌چیزش بعداً قابلِ ویرایش است.">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="presets">
          {meta?.presets.map((p) => (
            <Card key={p.key} className="flex flex-col gap-2">
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-bold" style={{ color: "var(--text)" }}>
                  {p.name}
                </h3>
                {p.needs_node && <Badge tone="info">سرورِ پردازش</Badge>}
              </div>
              <p className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
                {p.description}
              </p>
              <div className="flex flex-wrap gap-1">
                {p.types.map((t) => (
                  <Badge key={t}>{t}</Badge>
                ))}
                {p.cities.map((c) => (
                  <Badge key={c} tone="brand">
                    {c}
                  </Badge>
                ))}
              </div>
              <div className="mt-auto flex flex-wrap gap-2 pt-1">
                <Button size="sm" disabled={!!busy} onClick={() => fromPreset(p, true)} data-testid={`preset-run-${p.key}`}>
                  <Icon name="play" size={14} />
                  {busy === `${p.key}-run` ? "…" : "بساز و اجرا کن"}
                </Button>
                <Button variant="secondary" size="sm" disabled={!!busy} onClick={() => fromPreset(p, false)} data-testid={`preset-make-${p.key}`}>
                  فقط بساز
                </Button>
              </div>
            </Card>
          ))}
          <Card hover className="flex min-h-[8rem] flex-col items-center justify-center gap-2 text-center">
            <Button onClick={() => { setFormKey((k) => k + 1); setForm({ open: true, mission: null }); }} disabled={!meta} data-testid="new-mission">
              <Icon name="plus" size={15} />
              مأموریتِ دلخواه
            </Button>
            <span className="text-xs" style={{ color: "var(--text-3)" }}>
              برای هر فروشگاه، هر نوع کسب‌وکار و هر شهر
            </span>
          </Card>
        </div>
      </Section>

      {openRun && (
        <Section title="اجرای باز" action={<Button variant="ghost" size="sm" onClick={() => showRun(null)}>بستن</Button>}>
          <RunPanel runId={openRun} onChanged={list.reload} />
        </Section>
      )}

      <Section title="مأموریت‌های من" hint={missions.length ? `${fa(missions.length)} مأموریت` : undefined}>
        {list.loading && !list.data ? (
          <div className="py-8 text-center">
            <Spinner />
          </div>
        ) : list.error ? (
          <Alert tone="bad">{list.error}</Alert>
        ) : missions.length === 0 ? (
          <Card>
            <EmptyState icon="target" title="هنوز مأموریتی نساخته‌اید">
              از «شروعِ سریع» بالا یکی را بزنید یا یک مأموریتِ دلخواه بسازید.
            </EmptyState>
          </Card>
        ) : (
          <div className="space-y-3" data-testid="mission-list">
            {missions.map((m) => (
              <Card key={m.id} className="space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-base font-bold" style={{ color: "var(--text)" }}>
                      {m.name}
                    </h3>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
                      {m.types_label.map((t) => (
                        <Badge key={t}>{t}</Badge>
                      ))}
                      {m.spec.keywords.slice(0, 3).map((k) => (
                        <Badge key={k} tone="info">
                          {k}
                        </Badge>
                      ))}
                      {m.cities.map((c) => (
                        <Badge key={c} tone="brand">
                          {c}
                        </Badge>
                      ))}
                      {m.store_name && <Badge tone="neutral">{m.store_name}</Badge>}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" disabled={!!m.active_run || busy === `run-${m.id}`} onClick={() => startRun(m)} data-testid={`mission-run-${m.id}`}>
                      <Icon name="play" size={14} />
                      اجرا
                    </Button>
                    <Link to={`/growth/finder/results?mission=${m.id}`} className="u-btn u-btn-secondary u-btn-sm no-underline">
                      نتیجه‌ها ({fa(m.findings)})
                    </Link>
                    <Link to={`/growth/finder/drafts?mission=${m.id}`} className="u-btn u-btn-secondary u-btn-sm no-underline">
                      پیش‌نویس‌ها ({fa(m.drafts)})
                    </Link>
                    <Button variant="ghost" size="sm" onClick={() => { setFormKey((k) => k + 1); setForm({ open: true, mission: m }); }}>
                      <Icon name="edit" size={14} />
                      ویرایش
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setArchive(m)} aria-label="بایگانی">
                      <Icon name="trash" size={14} />
                    </Button>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs" style={{ color: "var(--text-3)" }}>
                  <span>
                    تکرار: <b>{SCHEDULE_LABEL(m.schedule_days)}</b>
                    {m.schedule_days > 0 && (
                      <>
                        {" "}
                        · {m.enabled ? `اجرای بعدی ${faDateTime(m.next_run_at)}` : "خاموش"}{" "}
                        <button type="button" className="underline" onClick={() => toggleSchedule(m)} data-testid={`mission-toggle-${m.id}`}>
                          {m.enabled ? "خاموش کن" : "روشن کن"}
                        </button>
                      </>
                    )}
                  </span>
                  <span>آخرین اجرا: {m.last_run_at ? faAgo(m.last_run_at) : "—"}</span>
                  {m.last_run && (
                    <span>
                      <button type="button" className="underline" onClick={() => showRun(m.last_run!.id)} data-testid={`mission-lastrun-${m.id}`}>
                        {m.last_run.state_label}: {fa(m.last_run.created)} لیدِ تازه، {fa(m.last_run.merged)} ادغام
                      </button>
                    </span>
                  )}
                  {m.active_run && (
                    <Badge tone="info">در حال اجرا</Badge>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </Section>

      <Section title="وضعیتِ ابزارها" hint="چه چیزی الان کار می‌کند و چه چیزی منتظر است.">
        <div className="grid gap-3 md:grid-cols-2">
          <Card className="space-y-2" >
            <div data-testid="node-status">
              <h3 className="text-sm font-bold" style={{ color: "var(--text)" }}>
                سرورِ پردازش (کامپیوترِ گرافیکی)
              </h3>
              {meta &&
                (
                  [
                    ["خزشِ بزرگ و رندرِ سایت‌های جاوااسکریپتی", meta.node.crawl],
                    ["خواندنِ پیجِ اینستاگرام (آباگرام)", meta.node.instagram],
                  ] as const
                ).map(([label, st]) => (
                  <div key={label} className="mt-2 text-xs leading-6" style={{ color: "var(--text-2)" }}>
                    <div className="flex items-center gap-2">
                      <Badge tone={st.ready ? "ok" : st.online ? "warn" : "neutral"}>{st.ready ? "آماده" : st.online ? "روشن، در حالِ آماده‌سازی" : st.known ? "خاموش" : "هنوز گزارش نداده"}</Badge>
                      <b>{label}</b>
                    </div>
                    {st.message && <div style={{ color: "var(--text-3)" }}>{st.message}</div>}
                  </div>
                ))}
              <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                کارهایی که به این سرور نیاز دارند در صفِ ماندگار می‌مانند و با روشن‌شدنش خودکار انجام می‌شوند.
              </p>
            </div>
          </Card>
          <Card className="space-y-2">
            <div data-testid="engine-status">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-bold" style={{ color: "var(--text)" }}>
                  موتورهای جست‌وجوی وب
                </h3>
                <Button variant="secondary" size="sm" disabled={busy === "probe"} onClick={testEngines} data-testid="engines-probe">
                  <Icon name="refresh" size={14} />
                  {busy === "probe" ? "در حال آزمایش…" : "آزمایش"}
                </Button>
              </div>
              {engines.engines ? (
                <ul className="mt-2 space-y-1 text-xs" style={{ color: "var(--text-2)" }}>
                  {Object.entries(engines.engines).map(([k, e]) => (
                    <li key={k} className="flex items-center gap-2">
                      <Badge tone={e.ok ? "ok" : "bad"}>{e.ok ? `کار می‌کند (${fa(e.results)})` : "کار نمی‌کند"}</Badge>
                      <b>{e.label}</b>
                      {e.message && <span style={{ color: "var(--text-3)" }}>{e.message}</span>}
                    </li>
                  ))}
                  {engines.at && <li style={{ color: "var(--text-3)" }}>آخرین آزمایش: {faAgo(engines.at)}</li>}
                </ul>
              ) : (
                <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                  هنوز آزمایش نشده. «آزمایش» از هر موتور یک درخواستِ کوچک می‌فرستد (موتوری که در استراحت است پرسیده نمی‌شود).
                </p>
              )}
              {engines.cooldown && Object.keys(engines.cooldown).length > 0 && (
                <ul className="mt-2 space-y-1 text-xs" style={{ color: "var(--text-2)" }} data-testid="engine-rest">
                  {Object.entries(engines.cooldown).map(([k, c]) => (
                    <li key={k} className="flex flex-wrap items-center gap-2">
                      <Badge tone="warn">در استراحت</Badge>
                      <b>{engines.engines?.[k]?.label ?? k}</b>
                      <span style={{ color: "var(--text-3)" }}>تا {faDateTime(c.until)} ({c.reason}) — برای اینکه مسدودی طولانی نشود دوباره نمی‌پرسیم.</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                از این سرور فقط Brave به پرسِ فارسی جواب درست می‌دهد و اگر پشتِ‌هم پرسیده شود موقتاً مسدود می‌کند؛ پس آهسته و کم می‌پرسیم و بعد از مسدودی نیم‌ساعت استراحت می‌دهیم. نتیجه‌ها پیش از استفاده از نظرِ ارتباط با موضوع سنجیده می‌شوند و مقاله و فهرست کنار می‌رود. {engines.brave_api ? "کلیدِ API برِیو ثبت است؛ از راهِ رسمی پرسیده می‌شود." : "اگر کلیدِ API برِیو را در تنظیماتِ کشف بگذارید، از راهِ رسمی و بدونِ محدودیت پرسیده می‌شود."}
              </p>
            </div>
          </Card>
        </div>
        <Card className="space-y-2">
          <div data-testid="neshan-key">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold" style={{ color: "var(--text)" }}>
                کلیدِ API نشان (اختیاری)
              </h3>
              <Badge tone={neshanSet ? "ok" : "neutral"}>{neshanSet ? "ثبت شده" : "ثبت نشده"}</Badge>
            </div>
            <p className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
              منبعِ «نشان» فقط با کلیدِ خودتان کار می‌کند (از platform.neshan.org). کلید فقط ذخیره می‌شود و هرگز نمایش داده نمی‌شود. از سایتِ نشان و بلد چیزی خزیده نمی‌شود.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Input dir="ltr" type="password" value={neshanKey} onChange={(e) => setNeshanKey(e.target.value)} placeholder="کلید را اینجا بچسبانید" style={{ maxWidth: 320 }} autoComplete="off" aria-label="کلیدِ نشان" />
              <Button size="sm" disabled={busy === "neshan" || neshanKey.trim().length < 16} onClick={() => saveNeshan(false)}>
                ذخیره
              </Button>
              {neshanSet && (
                <Button size="sm" variant="ghost" disabled={busy === "neshan"} onClick={() => saveNeshan(true)}>
                  برداشتن
                </Button>
              )}
            </div>
          </div>
        </Card>
        {meta && (
          <p className="text-xs" style={{ color: "var(--text-3)" }}>
            داده‌های نقشه: {meta.attribution}. ارسالِ خودکار {meta.outreach.sending_enabled ? "روشن" : "خاموش"} است؛ سقفِ روزانه {fa(meta.outreach.daily_cap)} ({fa(meta.outreach.cap_remaining)} مانده).
          </p>
        )}
      </Section>

      {meta && form.open && (
        <MissionForm
          key={formKey}
          open
          mission={form.mission}
          onClose={() => setForm({ open: false, mission: null })}
          onSaved={async (m, start) => {
            setForm({ open: false, mission: null });
            list.reload();
            if (start) await startRun(m);
          }}
        />
      )}
      <ConfirmDialog
        open={!!archive}
        title="بایگانیِ مأموریت"
        message={`مأموریتِ «${archive?.name ?? ""}» بایگانی شود؟ لیدهایی که پیدا کرده می‌مانند.`}
        confirmLabel="بایگانی"
        onConfirm={doArchive}
        onClose={() => setArchive(null)}
      />
    </div>
  );
}
