import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { Alert, Badge, Button, ErrorBox, Input, Select, Spinner, fa } from "../../components/ui";
import { Claim, DEFAULT_SCENE, Preview, RenderItem, Scene, TemplateRow, bcApi, claimsOf, downloadBlob, isCancel } from "./api";
import { useBrandChar } from "./BrandCharLayout";
import { CharPicker, Chips, Section, useNotice } from "./common";

export default function ScenesPage() {
  const { id, ov, sel, select } = useBrandChar();
  const nav = useNavigate();
  const [scene, setScene] = useState<Scene>(DEFAULT_SCENE);
  const [bubbleText, setBubbleText] = useState("");
  const [bubbleKind, setBubbleKind] = useState("say");
  const [captionText, setCaptionText] = useState("");
  const [captionPos, setCaptionPos] = useState("bottom");
  const [tag, setTag] = useState("");
  const [allowClaims, setAllowClaims] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [prevBusy, setPrevBusy] = useState(false);
  const [prevError, setPrevError] = useState<string | null>(null);
  const [claims, setClaims] = useState<{ message: string; found: Claim[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<RenderItem[]>([]);
  const [tpls, setTpls] = useState<TemplateRow[]>([]);
  const [tplText, setTplText] = useState<Record<string, { bubble?: string; caption?: string }>>({});
  const [tplOut, setTplOut] = useState<Record<string, RenderItem>>({});
  const n = useNotice();

  const cid = sel?.id ?? null;
  const persona = ov.persona.data;
  const personaLines = useMemo(() => {
    const out: string[] = [];
    for (const t of [persona.greeting, ...persona.catchphrases, ...persona.sample_lines.map((s) => s.text), persona.signoff]) if (t && !out.includes(t)) out.push(t);
    return out.slice(0, 8);
  }, [persona]);
  const suggested = personaLines.length ? personaLines : ov.lines.map((l) => l.text).slice(0, 6);

  // نقشِ شخصیت ⇒ صحنهٔ اولیه
  useEffect(() => {
    if (!sel) return;
    const r = ov.roles.find((x) => x.key === sel.role);
    if (r) setScene((s) => ({ ...s, background: r.background, expression: r.expression, pose: r.pose }));
    setPreview(null);
  }, [sel?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    bcApi.templates(id).then((r) => setTpls(r.items)).catch(() => setTpls([]));
  }, [id, sel?.id, ov.persona.version, ov.persona.updated_at]);

  const body = useCallback((): Record<string, unknown> => ({
    size: scene.size, pose: scene.pose, expression: scene.expression, background: scene.background, position: scene.position, flip: scene.flip, prop: scene.prop,
    bubble: bubbleText.trim() ? { text: bubbleText, kind: bubbleKind } : null,
    caption: captionText.trim() ? { text: captionText, position: captionPos } : null,
    allow_claims: allowClaims,
  }), [scene, bubbleText, bubbleKind, captionText, captionPos, allowClaims]);

  const key = useMemo(() => JSON.stringify([body(), cid]), [body, cid]);
  useEffect(() => {
    if (cid === null) return;
    const ctl = new AbortController();
    const t = window.setTimeout(() => {
      setPrevBusy(true);
      bcApi
        .preview(id, cid, body(), ctl.signal)
        .then((p) => {
          setPreview(p);
          setPrevError(null);
        })
        .catch((e) => {
          if (!isCancel(e)) setPrevError(errorMessage(e));
        })
        .finally(() => setPrevBusy(false));
    }, 350);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!sel || cid === null) return <Alert tone="info">اول در «استودیوی شخصیت» یک شخصیت بسازید.</Alert>;
  const set = <K extends keyof Scene>(k: K, v: Scene[K]) => setScene((s) => ({ ...s, [k]: v }));
  const size = ov.options.sizes.find((s) => s.key === scene.size);
  const poseList = tag ? ov.options.pose_tags.find((t) => t.key === tag)?.poses ?? [] : ov.options.poses.map((p) => p.key);
  const poseLabel = (k: string) => ov.options.poses.find((p) => p.key === k)?.fa ?? k;
  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setClaims(null);
    try {
      await fn();
    } catch (e) {
      const c = claimsOf(e);
      if (c) setClaims(c);
      else n.fail(e);
    } finally {
      setBusy(null);
    }
  };
  const render = () => act("render", async () => {
    const r = await bcApi.render(id, cid, body());
    setDone((d) => [r, ...d.filter((x) => x.id !== r.id)].slice(0, 12));
    n.ok(r.cached ? "همین تصویر از قبل ساخته شده بود (از کَش)." : "تصویر ساخته و در کتابخانهٔ ادیتورِ عکس ثبت شد.");
  });
  const sticker = (crop: "full" | "bust") => act("sticker", async () => {
    const r = await bcApi.sticker(id, cid, { pose: scene.pose, expression: scene.expression, prop: scene.prop, flip: scene.flip, crop });
    setDone((d) => [r, ...d.filter((x) => x.id !== r.id)].slice(0, 12));
    n.ok("استیکرِ شفاف ساخته شد.");
  });
  const renderTemplate = (t: TemplateRow) => act(`tpl-${t.id}`, async () => {
    const o = tplText[t.id] ?? {};
    const r = await bcApi.renderTemplate(id, t.id, { character: cid, ...(o.bubble !== undefined ? { bubble_text: o.bubble } : {}), ...(o.caption !== undefined ? { caption_text: o.caption } : {}), allow_claims: allowClaims });
    setTplOut((m) => ({ ...m, [t.id]: r }));
  });

  return (
    <div className="bc-root" data-testid="scenes-page">
      <Section title="شخصیت" hint="صحنه‌ها با شخصیتِ انتخاب‌شده ساخته می‌شود.">
        <CharPicker chars={ov.characters} value={cid} onChange={select} />
      </Section>
      {n.error ? <ErrorBox message={n.error} /> : null}
      {n.notice ? <Alert tone="ok">{n.notice}</Alert> : null}

      <div className="bc-grid two">
        <div className="bc-root">
          <Section title="ژست" hint={`${fa(ov.options.poses.length)} ژست؛ با «شخصیت چه کار کند؟» فیلتر کنید.`}>
            <div className="bc-chips" role="group" aria-label="شخصیت چه کار کند">
              <button type="button" className="bc-chip" aria-pressed={tag === ""} onClick={() => setTag("")}>همه</button>
              {ov.options.pose_tags.map((t) => <button key={t.key} type="button" className="bc-chip" aria-pressed={tag === t.key} onClick={() => setTag(t.key)}>{t.fa}</button>)}
            </div>
            <div className="bc-chips" role="group" aria-label="ژست">
              {poseList.map((p) => <button key={p} type="button" className="bc-chip" aria-pressed={scene.pose === p} onClick={() => set("pose", p)}>{poseLabel(p)}</button>)}
            </div>
            <span className="bc-sub">حالتِ چهره</span>
            <Chips options={ov.options.expressions} value={scene.expression} onChange={(v) => set("expression", v)} label="حالتِ چهره" />
            <div className="bc-fields">
              <label className="bc-label">وسیلهٔ دست
                <Select value={scene.prop} onChange={(e) => set("prop", e.target.value)}>
                  <option value="auto">خودکار (ژست و ظاهر)</option>
                  {ov.options.choices.prop.map((o) => <option key={o.key} value={o.key}>{o.fa}</option>)}
                </Select>
              </label>
              <label className="bc-row" style={{ gap: 6, alignSelf: "end" }}><input type="checkbox" checked={scene.flip} onChange={(e) => set("flip", e.target.checked)} /> رو به چپ (آینه؛ لوگو وارونه نمی‌شود)</label>
            </div>
          </Section>

          <Section title="کادر و پس‌زمینه">
            <span className="bc-sub">اندازه</span>
            <div className="bc-chips" role="group" aria-label="اندازه">
              {ov.options.sizes.map((s) => <button key={s.key} type="button" className="bc-chip" aria-pressed={scene.size === s.key} onClick={() => set("size", s.key)}>{s.fa} ({fa(s.w)}×{fa(s.h)})</button>)}
            </div>
            {size && size.safe[0] > 0 ? <p className="bc-muted">استوری: متن و شخصیت از ۱۳٪ِ بالا و ۱۸٪ِ پایین دور می‌ماند (اعدادِ پلتفرم تقریبی‌اند).</p> : null}
            <div className="bc-fields">
              <label className="bc-label">پس‌زمینه
                <Select value={String(scene.background).startsWith("#") ? "#" : scene.background} onChange={(e) => set("background", e.target.value === "#" ? "#2f7fd1" : e.target.value)}>
                  <optgroup label="فروشگاهی (با رنگ‌های برند)">{ov.options.backgrounds.filter((b) => b.group === "marketing").map((b) => <option key={b.key} value={b.key}>{b.fa}</option>)}</optgroup>
                  <optgroup label="صحنه‌های آماده">{ov.options.backgrounds.filter((b) => b.group === "scene").map((b) => <option key={b.key} value={b.key}>{b.fa}</option>)}</optgroup>
                  <option value="#">رنگِ دلخواه…</option>
                </Select>
              </label>
              <label className="bc-label">جای شخصیت
                <Select value={scene.position} onChange={(e) => set("position", e.target.value)}>{ov.options.positions.map((p) => <option key={p.key} value={p.key}>{p.fa}</option>)}</Select>
              </label>
              {String(scene.background).startsWith("#") ? (
                <label className="bc-label">رنگِ پس‌زمینه
                  <input type="color" value={String(scene.background)} onChange={(e) => set("background", e.target.value)} aria-label="رنگِ پس‌زمینه" />
                </label>
              ) : null}
            </div>
          </Section>

          <Section title="متن" hint="حباب و کپشن را خودتان بنویسید یا از جمله‌های لحنِ برند بردارید.">
            <div className="bc-chips" role="group" aria-label="جمله‌های پیشنهادی">
              {suggested.map((t) => <button key={t} type="button" className="bc-chip" onClick={() => setBubbleText(t)} title="گذاشتن در حباب">{t}</button>)}
            </div>
            <div className="bc-fields">
              <label className="bc-label wide">متنِ حباب<Input value={bubbleText} maxLength={ov.limits.max_text} onChange={(e) => setBubbleText(e.target.value)} placeholder="خالی = بدونِ حباب" /></label>
              <label className="bc-label">نوعِ حباب<Select value={bubbleKind} onChange={(e) => setBubbleKind(e.target.value)}>{ov.options.bubble_kinds.map((b) => <option key={b.key} value={b.key}>{b.fa}</option>)}</Select></label>
              <label className="bc-label wide">کپشنِ نواری<Input value={captionText} maxLength={ov.limits.max_text} onChange={(e) => setCaptionText(e.target.value)} placeholder="خالی = بدونِ کپشن؛ *کلمهٔ مهم* به رنگِ برند" /></label>
              <label className="bc-label">جای کپشن<Select value={captionPos} onChange={(e) => setCaptionPos(e.target.value)}><option value="bottom">پایین</option><option value="top">بالا</option></Select></label>
            </div>
            {claims ? (
              <Alert tone="warn" title="متن ادعا دارد">
                {claims.message}
                <div className="bc-row" style={{ marginTop: 8 }}>
                  <label className="bc-row" style={{ gap: 6 }}><input type="checkbox" checked={allowClaims} onChange={(e) => setAllowClaims(e.target.checked)} /> این ادعا را خودم تأیید کرده‌ام</label>
                </div>
              </Alert>
            ) : null}
            {preview && preview.claims.length && !claims ? <Alert tone="warn">{preview.claims_message}</Alert> : null}
          </Section>
        </div>

        <div className="bc-root">
          <div className="bc-sticky bc-root">
            <Section title="پیش‌نمایشِ زنده" action={prevBusy ? <Spinner size={16} /> : undefined}>
              {prevError ? <ErrorBox message={prevError} /> : null}
              <div className={`bc-previewbox${prevBusy ? " busy" : ""}`} data-testid="scene-preview">{preview ? <img src={preview.image} alt="پیش‌نمایشِ صحنه" /> : <Spinner />}</div>
              {preview ? (
                <div className="bc-qa" data-testid="scene-qa">
                  <Badge tone={preview.qa.ok ? "ok" : "warn"}>{preview.qa.ok ? "رنگ‌های امضا دیده می‌شود" : "یک رنگِ امضا گم شده"}</Badge>
                  {preview.qa.colours.map((c) => <span key={c.role + c.hex} className="bc-row" style={{ gap: 4 }}><i className="bc-dot" style={{ background: c.hex, opacity: c.found ? 1 : 0.3 }} />{c.name_fa || c.name}</span>)}
                  {preview.qa.notes.map((t) => <span key={t} className="bc-muted">{t}</span>)}
                </div>
              ) : null}
              <div className="bc-row">
                <Button type="button" onClick={() => void render()} disabled={busy !== null}>{busy === "render" ? <Spinner size={14} /> : null} بساز و ذخیره کن</Button>
                <Button type="button" variant="secondary" onClick={() => void sticker("full")} disabled={busy !== null}>استیکرِ شفاف</Button>
                <Button type="button" variant="ghost" onClick={() => void sticker("bust")} disabled={busy !== null}>نیم‌تنه (برای تامنیل)</Button>
              </div>
            </Section>
            {done.length ? (
              <Section title="ساخته‌شده‌ها">
                <div className="bc-gallery">
                  {done.map((r) => (
                    <div className="bc-shot" key={r.id}>
                      {r.asset?.thumb ? <img src={r.asset.thumb} alt={r.kind_fa} loading="lazy" /> : null}
                      <small>{r.kind_fa} · {fa(r.width)}×{fa(r.height)}</small>
                      <div className="bc-row">
                        <Button type="button" variant="ghost" size="sm" onClick={() => void downloadBlob(r.urls.download, `brand-character-${r.id}.png`).catch((e) => n.fail(e))}>دانلود</Button>
                        {r.asset ? <Button type="button" variant="ghost" size="sm" onClick={() => nav(`/stores/${id}/photo-editor?asset=${r.asset!.id}&mode=manual`)}>ادیتورِ عکس</Button> : null}
                      </div>
                    </div>
                  ))}
                </div>
              </Section>
            ) : null}
          </div>
        </div>
      </div>

      <Section title="قالب‌های پست و استوری" hint="۱۰ قالبِ آماده برای استودیوی تصویر؛ متنِ حباب و کپشن از لحنِ برند می‌آید و هر قالب را می‌توانید ویرایش کنید. نتیجه در کتابخانهٔ ادیتورِ عکس می‌نشیند.">
        {!tpls.length ? <span className="bc-muted">قالبی نیست.</span> : null}
        <div className="bc-uses" data-testid="templates">
          {tpls.map((t) => {
            const o = tplText[t.id] ?? {};
            const out = tplOut[t.id];
            return (
              <div className="bc-use" key={t.id}>
                <h3>{t.fa}<Badge tone="neutral">{t.size_fa}</Badge></h3>
                <label className="bc-label">متنِ حباب<Input value={o.bubble ?? t.bubble} maxLength={ov.limits.max_text} onChange={(e) => setTplText((m) => ({ ...m, [t.id]: { ...m[t.id], bubble: e.target.value } }))} /></label>
                <label className="bc-label">کپشن<Input value={o.caption ?? t.caption} maxLength={ov.limits.max_text} onChange={(e) => setTplText((m) => ({ ...m, [t.id]: { ...m[t.id], caption: e.target.value } }))} /></label>
                <div className="bc-row">
                  <Button type="button" size="sm" onClick={() => void renderTemplate(t)} disabled={busy !== null}>{busy === `tpl-${t.id}` ? <Spinner size={14} /> : null} بساز</Button>
                  <span className="bc-muted">{poseLabel(t.pose)}</span>
                </div>
                {out?.asset?.thumb ? (
                  <div className="bc-shot">
                    <img src={out.asset.thumb} alt={t.fa} loading="lazy" />
                    <div className="bc-row">
                      <Button type="button" variant="ghost" size="sm" onClick={() => void downloadBlob(out.urls.download, `${t.id}.png`).catch((e) => n.fail(e))}>دانلود</Button>
                      <Button type="button" variant="ghost" size="sm" onClick={() => nav(`/stores/${id}/photo-editor?asset=${out.asset!.id}&mode=manual`)}>ادیتورِ عکس</Button>
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
        <p className="bc-muted">برای ویدیو و تامنیل: <Link to={`/stores/${id}/brand-character/gallery`}>گالری و کاربرد</Link>.</p>
      </Section>
    </div>
  );
}
