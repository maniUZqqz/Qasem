import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Badge, Button, ErrorBox, Spinner, fa } from "../../components/ui";
import { NodeStatus, bcApi } from "./api";
import { useBrandChar } from "./BrandCharLayout";
import { Section, useNotice } from "./common";

export default function OverviewPage() {
  const { id, ov, sel, reload } = useBrandChar();
  const [node, setNode] = useState<NodeStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const n = useNotice();
  const base = `/stores/${id}/brand-character`;
  const p = ov.persona;
  const primary = ov.characters.find((c) => c.is_primary) ?? ov.characters[0];

  useEffect(() => {
    bcApi.node(id).then(setNode).catch(() => setNode(null));
  }, [id]);

  const steps: { done: boolean; label: string; to: string; cta: string }[] = [
    { done: p.exists, label: "شخصیتِ گفتار (نام، کهن‌الگو، لحن) ذخیره شده", to: `${base}/persona`, cta: "ساختن" },
    { done: ov.characters.length > 0, label: "یک شخصیتِ دیداری ساخته شده", to: `${base}/studio`, cta: "ساختن" },
    { done: !!primary?.locked, label: "ظاهر تأیید و قفل شده", to: `${base}/studio`, cta: "تأیید" },
    { done: p.locked, label: "لحن تأیید و قفل شده", to: `${base}/persona`, cta: "تأیید" },
    { done: ov.usage.total > 0, label: "شخصیت جایی به کار رفته (موشن، تامنیل، پست ...)", to: `${base}/gallery`, cta: "به کار ببر" },
  ];
  const doneCount = steps.filter((s) => s.done).length;

  const quickPersona = async () => {
    setBusy("persona");
    try {
      const d = await bcApi.personaDraft(id, "", false);
      await bcApi.savePersona(id, d.persona, d.origin === "facts" ? "facts" : "rule");
      await reload();
      n.ok("پیش‌نویسِ شخصیتِ گفتار از " + (d.origin === "facts" ? "واقعیت‌های تأییدشدهٔ برند" : "پروفایلِ فروشگاه") + " ذخیره شد؛ در «شخصیتِ گفتار» مرورش کنید.");
    } catch (e) {
      n.fail(e);
    } finally {
      setBusy(null);
    }
  };
  const quickCharacter = async () => {
    setBusy("char");
    try {
      const c = await bcApi.create(id, { role: ov.has_facts ? "coach" : "coach", style: "flat", use_logo: true });
      await bcApi.sheet(id, c.id);
      await reload(c.id);
      n.ok("شخصیتِ مربی با رنگ‌ها و لوگوی برند ساخته شد و برگهٔ مدلش آماده است.");
    } catch (e) {
      n.fail(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="bc-root" data-testid="overview-page">
      {n.error ? <ErrorBox message={n.error} /> : null}
      {n.notice ? <Alert tone="ok">{n.notice}</Alert> : null}

      <Section title="قدم‌به‌قدم" hint={`${fa(doneCount)} از ${fa(steps.length)} انجام شده`}>
        <div className="bc-meter"><div className="bar"><i style={{ width: `${(doneCount / steps.length) * 100}%` }} /></div><b>{fa(doneCount)}/{fa(steps.length)}</b></div>
        {steps.map((s) => (
          <div className="bc-row" key={s.label}>
            <Badge tone={s.done ? "ok" : "neutral"}>{s.done ? "انجام شد" : "مانده"}</Badge>
            <span style={{ flex: 1 }}>{s.label}</span>
            {!s.done ? <Link className="u-btn u-btn-secondary u-btn-sm" to={s.to}>{s.cta}</Link> : null}
          </div>
        ))}
        <div className="bc-row">
          {!p.exists ? <Button type="button" onClick={() => void quickPersona()} disabled={busy !== null}>{busy === "persona" ? <Spinner size={14} /> : null} {ov.has_facts ? "پیش‌نویسِ گفتار از واقعیت‌های برند" : "پیش‌نویسِ گفتار از پروفایلِ فروشگاه"}</Button> : null}
          {!ov.characters.length ? <Button type="button" variant="secondary" onClick={() => void quickCharacter()} disabled={busy !== null}>{busy === "char" ? <Spinner size={14} /> : null} شخصیتِ مربی با رنگ‌های برند بساز</Button> : null}
        </div>
      </Section>

      <div className="bc-grid two">
        <Section title="شخصیتِ گفتار" action={<Link className="u-btn u-btn-ghost u-btn-sm" to={`${base}/persona`}>باز کردن</Link>}>
          {p.exists ? (
            <div className="bc-kv">
              <span>نام</span><b>{p.data.name || "—"}</b>
              <span>کهن‌الگو</span><b>{p.archetype_fa}</b>
              <span>لحن</span><b>{p.tone_words.join("، ") || "متعادل"}</b>
              <span>شعار</span><b>{p.data.catchphrases[0] || "—"}</b>
              <span>وضعیت</span><b>{p.locked ? `تأییدشده · نسخهٔ ${fa(p.version)}` : "پیش‌نویس"} {p.active ? "" : "· خاموش"}</b>
              <span>کامل‌بودن</span><b>{fa(p.score.done)} از {fa(p.score.total)}{p.score.missing.length ? ` (کم: ${p.score.missing.slice(0, 3).join("، ")})` : ""}</b>
            </div>
          ) : <span className="bc-muted">هنوز ذخیره نشده.</span>}
        </Section>

        <Section title="شخصیتِ دیداری" action={<Link className="u-btn u-btn-ghost u-btn-sm" to={`${base}/studio`}>باز کردن</Link>}>
          {primary ? (
            <div className="bc-row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
              {primary.cover ? <img src={primary.cover} alt={primary.name} style={{ width: 96, height: 96, objectFit: "cover", borderRadius: 12 }} /> : null}
              <div className="bc-kv">
                <span>نام</span><b>{primary.name}</b>
                <span>سبک</span><b>{primary.style_fa}</b>
                <span>نسخه</span><b>{primary.locked ? `قفل · ${fa(primary.version)}` : "قفل نیست"}</b>
                <span>خروجی‌ها</span><b>{fa(primary.shots)} پست، {fa(primary.stickers)} استیکر</b>
                <span>ثبات</span><b>{primary.check.at ? (primary.check.ok ? "همهٔ ژست‌ها و اندازه‌ها قبول" : "ردی دارد") : "هنوز بررسی نشده"}</b>
              </div>
            </div>
          ) : <span className="bc-muted">هنوز ساخته نشده.</span>}
          {sel ? <p className="bc-muted">شخصیتِ انتخاب‌شده: {sel.name}</p> : null}
        </Section>

        <Section title="هوش مصنوعی و سرورِ پردازش" hint="شخصیتِ کدکشیده و همهٔ قالب‌ها بدونِ این‌ها کار می‌کنند؛ فقط «تصویرِ هوش مصنوعی» و «پیش‌نویسِ هوشمند» به آن‌ها نیاز دارند.">
          {node ? (
            <div className="bc-kv" data-testid="overview-node">
              <span>سرورِ پردازش</span><b>{node.online ? "روشن" : node.known ? "خاموش (کارها در صف می‌مانند)" : "ثبت نشده"}</b>
              <span>ساختِ تصویر</span><b>{node.ready ? "آماده" : node.kind_known ? "در حالِ آماده‌شدن" : "با به‌روزرسانیِ بعدیِ گره نصب می‌شود"}</b>
              <span>FLUX</span><b>{node.profiles.length ? node.profiles.join("، ") : "—"}</b>
              <span>قفلِ هویت</span><b>{node.identity_tools.length ? node.identity_tools.join("، ") : "ویرایشِ تصویر (img2img)"}</b>
            </div>
          ) : <Spinner size={16} />}
        </Section>

        <Section title="کجا به کار می‌رود" action={<Link className="u-btn u-btn-ghost u-btn-sm" to={`${base}/gallery`}>گالری و کاربرد</Link>}>
          <div className="bc-kv">
            {ov.usage.surfaces.slice(0, 6).map((s) => <Fragment key={s.key}><span>{s.fa}</span><b>{s.count ? `${fa(s.count)} بار` : "هنوز نه"}</b></Fragment>)}
          </div>
          <div className="bc-chips">{ov.usage.injection.map((i) => <Badge key={i.key} tone={i.active ? "ok" : "neutral"}>{i.fa}</Badge>)}</div>
        </Section>
      </div>

      {ov.notes.map((t) => <p className="bc-muted" key={t}>{t}</p>)}
    </div>
  );
}
