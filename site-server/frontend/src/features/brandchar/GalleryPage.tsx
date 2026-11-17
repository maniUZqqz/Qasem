import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Alert, Badge, Button, ErrorBox, Input, Select, Spinner, fa } from "../../components/ui";
import { RenderItem, bcApi, downloadBlob } from "./api";
import { useBrandChar } from "./BrandCharLayout";
import { CharPicker, Section, fmtDate, useNotice } from "./common";
import { MOTION_SCENE_KEY } from "./motionBridge";


const KINDS = [
  { key: "", fa: "همه" },
  { key: "shot", fa: "پست و استوری" },
  { key: "template", fa: "قالب‌ها" },
  { key: "sticker", fa: "استیکر" },
  { key: "sheet", fa: "برگهٔ مدل" },
  { key: "svg", fa: "SVG" },
  { key: "pdf", fa: "PDF" },
];

export default function GalleryPage() {
  const { id, ov, sel, select, reload } = useBrandChar();
  const nav = useNavigate();
  const [kind, setKind] = useState("");
  const [items, setItems] = useState<RenderItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [usage, setUsage] = useState(ov.usage);
  const [recent, setRecent] = useState<{ id: number; surface: string; surface_fa: string; ref: string; created_at: string }[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [action, setAction] = useState("wave");
  const [arrive, setArrive] = useState("left");
  const [side, setSide] = useState("right");
  const [text, setText] = useState("");
  const [pose, setPose] = useState("thumbs_up");
  const [slug, setSlug] = useState("");
  const [hero, setHero] = useState<{ image: string; image_alt: string; title: string; subtitle: string; bubble: string; bound: boolean } | null>(null);
  const [dirOut, setDirOut] = useState<{ key: string; fa: string; thumb: string }[]>([]);
  const [inbox, setInbox] = useState<{ enabled: boolean; name?: string; greeting?: string; avatar?: string | null } | null>(null);
  const n = useNotice();
  const cid = sel?.id ?? null;
  const persona = ov.persona.data;

  const loadItems = useCallback(async () => {
    if (cid === null) return;
    setLoading(true);
    try {
      setItems(await bcApi.renders(id, cid, kind || undefined));
    } catch (e) {
      n.fail(e);
    } finally {
      setLoading(false);
    }
  }, [id, cid, kind]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  const loadUsage = useCallback(() => {
    bcApi.usage(id).then((u) => { setUsage(u); setRecent(u.recent); }).catch(() => undefined);
  }, [id]);
  useEffect(loadUsage, [loadUsage]);
  useEffect(() => {
    bcApi.inbox(id).then(setInbox).catch(() => setInbox(null));
  }, [id, cid]);
  useEffect(() => {
    setText((t) => t || persona.greeting || persona.catchphrases[0] || "");
  }, [persona.greeting, persona.catchphrases]);

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    try {
      await fn();
      loadUsage();
    } catch (e) {
      n.fail(e);
    } finally {
      setBusy(null);
    }
  };

  const toMotion = () => act("motion", async () => {
    const scene = await bcApi.useMotion(id, { character: cid, action, text, enter: arrive, side, duration: 6 });
    try {
      sessionStorage.setItem(MOTION_SCENE_KEY, JSON.stringify({ store: id, scene, at: Date.now() }));
    } catch {
      /* ذخیرهٔ مرورگر بسته است؛ صحنه را از خودِ استودیو هم می‌شود افزود */
    }
    nav(`/stores/${id}/motion`);
  });
  const toThumb = () => act("thumb", async () => {
    const r = await bcApi.useThumbnail(id, { character: cid, pose });
    nav(r.open);
  });
  const toDirector = () => act("director", async () => {
    const r = await bcApi.useDirector(id, { character: cid });
    setDirOut(r.items.map((i) => ({ key: i.key, fa: i.fa, thumb: i.thumb })));
    n.ok("پنج استیکر آماده شد. در «ادیتور ویدیو ⇐ کارگردان» مرحلهٔ «شخصیتِ برند» را اضافه کنید.");
  });
  const toSite = () => act("site", async () => {
    const r = await bcApi.useSiteHero(id, { character: cid, project_slug: slug.trim(), pose: "wave" });
    setHero(r);
    n.ok(r.bound ? "پروژهٔ سایت‌ساز به این فروشگاه بسته شد؛ متنِ هوش مصنوعیِ سایت هم با لحنِ برند نوشته می‌شود." : "بلوک آماده است (بستنِ پروژه فقط برای کارمندان است).");
  });

  if (!sel || cid === null) return <Alert tone="info">اول در «استودیوی شخصیت» یک شخصیت بسازید.</Alert>;

  return (
    <div className="bc-root" data-testid="gallery-page">
      {n.error ? <ErrorBox message={n.error} /> : null}
      {n.notice ? <Alert tone="ok">{n.notice}</Alert> : null}

      <Section title="شخصیت" hint="کاربردها با شخصیتِ انتخاب‌شده انجام می‌شود.">
        <CharPicker chars={ov.characters} value={cid} onChange={select} />
      </Section>

      <Section title="همه‌جا به کار ببر" hint={`تا حالا ${fa(usage.total)} بار به کار رفته. هر دکمه از شخصیتِ «${sel.name}» (نسخهٔ ${fa(sel.version)}${sel.locked ? "، قفل" : ""}) می‌سازد و همان‌جا باز می‌کند.`}>
        <div className="bc-uses">
          <div className="bc-use" data-testid="use-motion">
            <h3>استودیوی موشن <Badge tone="info">{fa(usage.surfaces.find((s) => s.key === "motion")?.count ?? 0)}</Badge></h3>
            <p>قطعهٔ «شخصیتِ برند»: وارد می‌شود، دست تکان می‌دهد یا اشاره می‌کند و حباب را هم‌زمان با کلماتِ گوینده نشان می‌دهد.</p>
            <div className="bc-fields">
              <label className="bc-label">کار<Select value={action} onChange={(e) => setAction(e.target.value)}><option value="wave">سلام و دست تکان‌دادن</option><option value="point">اشاره</option><option value="thumbs">تأیید (شستِ بالا)</option><option value="explain">توضیح</option><option value="think">فکر</option></Select></label>
              <label className="bc-label">ورود از<Select value={arrive} onChange={(e) => setArrive(e.target.value)}><option value="left">چپ</option><option value="right">راست</option><option value="bottom">پایین</option></Select></label>
              <label className="bc-label">کنارِ کادر<Select value={side} onChange={(e) => setSide(e.target.value)}><option value="right">راست</option><option value="left">چپ</option></Select></label>
              <label className="bc-label wide">متنِ حباب (همان متنِ گویندهٔ صحنه بهتر است)<Input value={text} maxLength={160} onChange={(e) => setText(e.target.value)} /></label>
            </div>
            <Button type="button" size="sm" onClick={() => void toMotion()} disabled={busy !== null}>{busy === "motion" ? <Spinner size={14} /> : null} افزودن به استودیوی موشن</Button>
          </div>

          <div className="bc-use" data-testid="use-thumb">
            <h3>تامنیل‌ساز <Badge tone="info">{fa(usage.surfaces.find((s) => s.key === "thumbnail")?.count ?? 0)}</Badge></h3>
            <p>استیکرِ شفافِ نیم‌تنه به‌عنوانِ سوژه؛ شعارِ برند در عنوان می‌نشیند و هیچ کارِ «حذفِ پس‌زمینه»ای ساخته نمی‌شود.</p>
            <label className="bc-label">ژست<Select value={pose} onChange={(e) => setPose(e.target.value)}>{ov.options.poses.map((p) => <option key={p.key} value={p.key}>{p.fa}</option>)}</Select></label>
            <Button type="button" size="sm" onClick={() => void toThumb()} disabled={busy !== null}>{busy === "thumb" ? <Spinner size={14} /> : null} استفاده در تامنیل</Button>
          </div>

          <div className="bc-use" data-testid="use-post">
            <h3>پست و استوری <Badge tone="info">{fa(usage.surfaces.find((s) => s.key === "post_template")?.count ?? 0)}</Badge></h3>
            <p>۱۰ قالبِ آمادهٔ پست و استوری با متنِ حباب از لحنِ برند؛ در استودیوی تصویر هم همین‌ها هست.</p>
            <div className="bc-row"><Link className="u-btn u-btn-secondary u-btn-sm" to={`/stores/${id}/brand-character/scenes`}>قالب‌ها</Link><Link className="u-btn u-btn-ghost u-btn-sm" to={`/stores/${id}/studio`}>استودیوی تولید محتوا</Link></div>
          </div>

          <div className="bc-use" data-testid="use-inbox">
            <h3>صندوق پیام و ایجنتِ فروش <Badge tone="info">{fa(usage.surfaces.find((s) => s.key === "inbox")?.count ?? 0)}</Badge></h3>
            <p>آواتار و سلامِ ایجنت در صندوقِ پیام و چتِ آزمایشی؛ پاسخ‌ها هم با لحنِ برند نوشته می‌شود.</p>
            {inbox?.enabled ? (
              <div className="bc-row">{inbox.avatar ? <img src={inbox.avatar} alt="آواتار" style={{ width: 56, height: 56, objectFit: "contain", borderRadius: 12, background: "var(--surface-2)" }} /> : null}<div><b>{inbox.name}</b><div className="bc-muted">{inbox.greeting || "سلامی ثبت نشده"}</div></div></div>
            ) : <span className="bc-muted">هنوز شخصیتی ثبت نشده.</span>}
            <div className="bc-row"><Link className="u-btn u-btn-secondary u-btn-sm" to={`/stores/${id}/inbox`}>صندوق پیام</Link><Link className="u-btn u-btn-ghost u-btn-sm" to={`/stores/${id}/chat`}>چتِ آزمایشی</Link></div>
          </div>

          <div className="bc-use" data-testid="use-site">
            <h3>سایت‌ساز <Badge tone="info">{fa(usage.surfaces.find((s) => s.key === "site_hero")?.count ?? 0)}</Badge></h3>
            <p>بلوکِ «سربرگِ شخصیتِ برند» در سایت‌ساز. با نوشتنِ شناسهٔ پروژه، متنِ هوش مصنوعیِ سایت هم با لحنِ برند نوشته می‌شود (ابزارِ کارکنان).</p>
            <label className="bc-label">شناسهٔ پروژهٔ سایت‌ساز (اختیاری)<Input value={slug} onChange={(e) => setSlug(e.target.value)} dir="ltr" placeholder="my-site" /></label>
            <Button type="button" size="sm" onClick={() => void toSite()} disabled={busy !== null}>{busy === "site" ? <Spinner size={14} /> : null} آماده‌سازیِ بلوک</Button>
            {hero ? <div className="bc-note">تصویر: <code dir="ltr">{hero.image}</code><br />تیتر: {hero.title}<br />حباب: {hero.bubble}</div> : null}
            <Link className="bc-muted" to="/tools/studio">باز کردنِ سایت‌ساز</Link>
          </div>

          <div className="bc-use" data-testid="use-director">
            <h3>کارگردانِ ویدیو <Badge tone="info">{fa(usage.surfaces.find((s) => s.key === "director")?.count ?? 0)}</Badge></h3>
            <p>ابزارِ «شخصیتِ برند» در کارگردان: شخصیت در ابتدا سلام می‌کند و در پایان تأیید می‌دهد؛ استیکرِ ژست‌ها از همین‌جا ساخته می‌شود.</p>
            <Button type="button" size="sm" onClick={() => void toDirector()} disabled={busy !== null}>{busy === "director" ? <Spinner size={14} /> : null} ساختِ استیکرهای ویدیو</Button>
            {dirOut.length ? <div className="bc-row">{dirOut.map((d) => <figure key={d.key} style={{ margin: 0, textAlign: "center" }}><img src={d.thumb} alt={d.fa} style={{ width: 54, height: 54, objectFit: "contain" }} /><figcaption className="bc-muted">{d.fa}</figcaption></figure>)}</div> : null}
            <Link className="bc-muted" to={`/stores/${id}/editor`}>ادیتور ویدیو ⇐ کارگردان</Link>
          </div>
        </div>

        <span className="bc-sub">تولیدکننده‌های متنی که لحنِ برند را می‌گیرند ({usage.persona_active ? "روشن" : "خاموش"})</span>
        <div className="bc-chips">
          {usage.injection.map((i) => <Badge key={i.key} tone={i.active ? "ok" : "neutral"}>{i.fa}</Badge>)}
        </div>
        {!usage.persona_active ? <Alert tone="warn">لحنِ برند به تولیدکننده‌ها نمی‌رسد: <Link to={`/stores/${id}/brand-character/persona`}>شخصیتِ گفتار</Link> را ذخیره و روشن کنید.</Alert> : null}
        {recent.length ? (
          <details>
            <summary>آخرین استفاده‌ها ({fa(recent.length)})</summary>
            <ul className="bc-sources">{recent.slice(0, 12).map((r) => <li key={r.id}>{r.surface_fa} <span className="bc-muted">· {fmtDate(r.created_at)}</span></li>)}</ul>
          </details>
        ) : null}
      </Section>

      <Section title="گالری" hint="همهٔ خروجی‌های این شخصیت؛ در کتابخانهٔ ادیتورِ عکس هم هستند." action={loading ? <Spinner size={16} /> : undefined}>
        <div className="bc-chips" role="group" aria-label="نوعِ خروجی">
          {KINDS.map((k) => <button key={k.key} type="button" className="bc-chip" aria-pressed={kind === k.key} onClick={() => setKind(k.key)}>{k.fa}</button>)}
        </div>
        <div className="bc-gallery" data-testid="gallery">
          {items.map((r) => (
            <div className="bc-shot" key={r.id}>
              {r.asset?.thumb ? <img src={r.asset.thumb} alt={r.kind_fa} loading="lazy" /> : <div className="bc-ph" style={{ aspectRatio: "4 / 5", display: "grid", placeItems: "center", color: "var(--text-3)" }}>{r.kind_fa}</div>}
              <small>{r.kind_fa} · {r.width && r.height ? `${fa(r.width)}×${fa(r.height)}` : ""} · {fmtDate(r.created_at)}</small>
              {r.qa && r.qa.ok === false ? <Badge tone="warn">رنگِ امضا گم شده</Badge> : null}
              <div className="bc-row">
                <Button type="button" variant="ghost" size="sm" onClick={() => void downloadBlob(r.urls.download, `brand-character-${r.id}.${r.kind === "svg" ? "svg" : r.kind === "pdf" ? "pdf" : "png"}`).catch((e) => n.fail(e))}>دانلود</Button>
                {r.asset && r.kind !== "sheet" ? <Button type="button" variant="ghost" size="sm" onClick={() => nav(`/stores/${id}/photo-editor?asset=${r.asset!.id}&mode=manual`)}>ادیتورِ عکس</Button> : null}
                {r.asset?.has_alpha ? <Button type="button" variant="ghost" size="sm" onClick={() => nav(`/stores/${id}/thumbnails?subject=${r.asset!.id}`)}>تامنیل</Button> : null}
                <Button type="button" variant="ghost" size="sm" onClick={() => void bcApi.removeRender(id, cid, r.id).then(() => { void loadItems(); void reload(cid); })}>حذف</Button>
              </div>
            </div>
          ))}
          {!items.length && !loading ? <span className="bc-muted">هنوز خروجی‌ای نیست. در «ژست و صحنه» یکی بسازید.</span> : null}
        </div>
      </Section>
    </div>
  );
}
