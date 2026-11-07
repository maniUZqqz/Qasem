import { useEffect, useMemo, useState } from "react";

import { Spinner, fa } from "../../../../components/ui";
import { videoApi } from "../api";
import type { TextClip } from "../manual/model";
import { TEXT_MOTIONS, applyDefaultTransition, metaOf, offlineClips, removeAllTransitions, setMediaMeta, setTextMotion, tagsFromText } from "../manual/r6ops";
import type { PanelProps } from "./types";

/** برچسب و یادداشتِ رسانه‌ها: هر ویدیو، صدا یا عکس چند برچسب (مثلاً «محصول، بیرونی») و یک یادداشت می‌گیرد؛ جستجو در «رسانه‌ها» هر دو را می‌بیند. در همین پروژه ذخیره می‌شود. */
export function MediaMetaPanel({ api }: PanelProps) {
  const [q, setQ] = useState("");
  const items = useMemo(() => Object.values(api.media).filter((m) => m.kind !== "image" || !m.ref.startsWith("sticker:")).sort((a, b) => a.title.localeCompare(b.title, "fa")), [api.media]);
  const shown = items.filter((m) => !q.trim() || `${m.title} ${(api.root.media_meta?.[m.ref]?.tags ?? []).join(" ")}`.includes(q.trim()));
  if (items.length === 0) return <p className="ws-hint" data-testid="mm-empty">هنوز رسانه‌ای نیست؛ اول در «رسانه‌ها» ویدیو آپلود کنید.</p>;
  return (
    <div data-testid="mediameta-panel">
      <input className="u-input" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="پیدا کردنِ رسانه…" aria-label="پیدا کردنِ رسانه" data-testid="mm-search" />
      <p className="ws-hint">برچسب‌ها را با ویرگول جدا کنید (تا ۱۲ برچسب). بعد از نوشتن، روی جای دیگری کلیک کنید تا ذخیره شود (برگشت: Ctrl+Z).</p>
      <ul className="mm-list" style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
        {shown.slice(0, 60).map((m) => {
          const meta = metaOf(api.root, m.ref);
          return (
            <li key={m.ref} className="mm-item" data-testid="mm-item" data-ref={m.ref}>
              <strong>{m.title}</strong> <small dir="ltr">{m.kind}</small>
              <input className="u-input" defaultValue={meta.tags.join("، ")} placeholder="برچسب‌ها: محصول، بیرونی…" aria-label={`برچسب‌های «${m.title}»`} data-testid="mm-tags" key={`t${m.ref}${meta.tags.join()}`}
                onBlur={(e) => { const tags = tagsFromText(e.target.value); if (tags.join("|") !== meta.tags.join("|")) api.applyRoot("برچسبِ رسانه", (p) => setMediaMeta(p, m.ref, { tags })); }} />
              <textarea className="u-input" defaultValue={meta.note} rows={2} maxLength={300} placeholder="یادداشت (مثلاً: نمای افتتاحیه، نورِ خوب)" aria-label={`یادداشتِ «${m.title}»`} data-testid="mm-note" key={`n${m.ref}${meta.note}`}
                onBlur={(e) => { if (e.target.value !== meta.note) api.applyRoot("یادداشتِ رسانه", (p) => setMediaMeta(p, m.ref, { note: e.target.value })); }} />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** رسانه‌های گم‌شده (Offline): قطعه‌هایی که فایلشان دیگر در رسانه‌های فروشگاه نیست؛ از همین‌جا قطعه را انتخاب و «جایگزینیِ فیلم» را باز می‌کنید */
export function OfflinePanel({ api }: PanelProps) {
  const known = useMemo(() => new Set(Object.keys(api.media)), [api.media]);
  const list = useMemo(() => offlineClips(api.root, known), [api.root, known]);
  if (!api.bin) return <p className="ws-hint"><Spinner size={12} /> رسانه‌ها هنوز بارگیری نشده‌اند…</p>;
  if (list.length === 0) return <p className="ws-hint" data-testid="off-ok">همهٔ رسانه‌های پروژه موجودند.</p>;
  return (
    <div data-testid="offline-panel">
      <p className="ws-hint">{fa(list.length)} قطعه رسانه‌اش را از دست داده (پاک شده یا از فروشگاه دیگری است). خروجی از این قطعه‌ها رد می‌شود تا جایگزین کنید.</p>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
        {list.map((o) => (
          <li key={o.id} data-testid="off-item" className="mk-top">
            <span><b>{o.label || o.ref}</b> <small>({o.track})</small></span>
            <button type="button" className="ws-btn" data-testid="off-select" onClick={() => api.select([o.id])}>انتخاب</button>
            <button type="button" className="ws-btn primary" data-testid="off-replace" onClick={() => { api.select([o.id]); api.openPanel("replace"); }}>جایگزینیِ فیلم…</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** گذارِ پیش‌فرض برای همهٔ برش‌ها: یک نوع و مدت می‌گذارید و روی همهٔ برش‌های چسبیدهٔ ترک‌های تصویر (یا فقط ترکِ انتخاب‌شده) می‌نشیند */
export function DefaultTransitionPanel({ api }: PanelProps) {
  const [kinds, setKinds] = useState<{ key: string; title: string; group: string }[]>([]);
  const [kind, setKind] = useState(api.root.default_transition?.kind ?? "crossfade");
  const [dur, setDur] = useState(api.root.default_transition?.duration ?? 0.4);
  const [onlyTrack, setOnlyTrack] = useState(false);
  useEffect(() => {
    let live = true;
    videoApi.catalogue(api.storeId).then((c) => { if (live) setKinds(c.transitions.kinds); }).catch(() => null);
    return () => { live = false; };
  }, [api.storeId]);
  const trackId = onlyTrack ? api.selected?.track.id : undefined;
  const run = (replace: boolean) => {
    let count = 0;
    api.applyRoot(replace ? "گذارِ پیش‌فرض روی همهٔ برش‌ها" : "گذارِ پیش‌فرض روی برش‌های بی‌گذار", (p) => { const r = applyDefaultTransition(p, { kind, duration: dur, trackId, replace }); count = r.count; return r.project; });
    api.notice(count ? `گذار روی ${fa(count)} برش نشست (برگشت: Ctrl+Z).` : "برشِ چسبیده‌ای که گذارش خالی باشد پیدا نشد.");
  };
  const groups = Array.from(new Set(kinds.map((k) => k.group)));
  return (
    <div data-testid="deftrans-panel">
      <label className="ws-field"><span>نوعِ گذار</span>
        <select className="u-input" value={kind} onChange={(e) => setKind(e.target.value)} data-testid="dt-kind">
          <option value="crossfade">محوشدنِ تدریجی (دیزالو)</option>
          <option value="fade">محو به سیاه</option>
          {groups.map((g) => (
            <optgroup key={g} label={g}>{kinds.filter((k) => k.group === g && k.key !== "fade").map((k) => <option key={k.key} value={k.key}>{k.title}</option>)}</optgroup>
          ))}
        </select>
      </label>
      <label className="fx-row"><span className="fx-label">مدت</span>
        <input type="range" min={0.1} max={2} step={0.05} value={dur} onChange={(e) => setDur(Number(e.target.value))} data-testid="dt-dur" />
        <span className="fx-val">{fa(Math.round(dur * 100) / 100)} ث</span>
      </label>
      <label className="fx-check"><input type="checkbox" checked={onlyTrack} onChange={(e) => setOnlyTrack(e.target.checked)} data-testid="dt-only" disabled={!api.selected} /><span>فقط روی ترکِ قطعهٔ انتخاب‌شده</span></label>
      <div className="mk-top">
        <button type="button" className="ws-btn primary" onClick={() => run(false)} data-testid="dt-apply">بگذار روی برش‌های بی‌گذار</button>
        <button type="button" className="ws-btn" onClick={() => run(true)} data-testid="dt-replace">جایگزینِ همهٔ گذارها</button>
        <button type="button" className="ws-btn" onClick={() => { let n = 0; api.applyRoot("برداشتنِ همهٔ گذارها", (p) => { const r = removeAllTransitions(p); n = r.count; return r.project; }); api.notice(`${fa(n)} گذار برداشته شد.`); }} data-testid="dt-clear">برداشتنِ همهٔ گذارها</button>
      </div>
      <p className="ws-hint">فقط برش‌هایی که دو قطعه به هم چسبیده‌اند گذار می‌گیرند. «برشِ مورف (تقریبیِ اپتیکال‌فلو)» برای برش میانِ دو نمای مشابهِ یک آدم است و فقط در خروجیِ نهایی روی سرورِ پردازش ساخته می‌شود؛ در پیش‌نمایش محو دیده می‌شود.</p>
    </div>
  );
}

/** حرکتِ متن: غلتشِ تیتراژ، نوارِ خبر، قوس و موج؛ کلِ نوشته روی مسیر می‌رود (خم‌شدنِ تک‌تکِ حروف روی منحنی نه) */
export function TextMotionPanel({ api }: PanelProps) {
  const sel = api.selected && api.selected.clip.type === "text" ? (api.selected.clip as TextClip) : null;
  if (!sel) return <p className="ws-hint" data-testid="tm-empty">اول یک متن را روی تایم‌لاین انتخاب کنید.</p>;
  return (
    <div data-testid="textmotion-panel">
      <div style={{ display: "grid", gap: 6 }}>
        {TEXT_MOTIONS.map((m) => (
          <button key={m.key} type="button" className="ws-btn" data-testid={`tm-${m.key}`} title={m.hint} onClick={() => api.apply(`حرکتِ متن: ${m.title}`, (p) => setTextMotion(p, sel.id, m.key))}>{m.title}</button>
        ))}
        <button type="button" className="ws-btn" disabled={!sel.path?.length} data-testid="tm-none" onClick={() => api.apply("برداشتنِ حرکتِ متن", (p) => setTextMotion(p, sel.id, null))}>بدونِ حرکت</button>
      </div>
      <p className="ws-hint">تیتراژ: متنِ چندخطی بنویسید؛ مدتِ متن خودکار به اندازهٔ خط‌ها دراز می‌شود. حرکت در پیش‌نمایش و خروجی یکی است.</p>
    </div>
  );
}
