import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, errorMessage } from "../../../api/client";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Input, PageHeader, Select, Spinner, fa } from "../../../components/ui";
import {
  Claim, DEFAULT_SCENE, Mascot, Overview, Preview, RenderItem, Scene, Spec, claimsOf, mascotApi,
} from "./api";
import "./mascot.css";

const COLOUR_FIELDS: { key: keyof Spec; label: string }[] = [
  { key: "limb_colour", label: "رنگِ دست و پا" },
  { key: "outline", label: "رنگِ خطِ دور" },
  { key: "hat_colour", label: "رنگِ کلاه یا هدبند" },
  { key: "neck_colour", label: "رنگِ شال، کراوات یا پاپیون" },
  { key: "extra_colour", label: "رنگِ پیش‌بند، عینک یا کوله" },
  { key: "prop_colour", label: "رنگِ وسیلهٔ دست" },
  { key: "hair_colour", label: "رنگِ مو" },
];
const CHOICE_FIELDS: { key: keyof Spec; label: string }[] = [
  { key: "head_style", label: "شکلِ سر" },
  { key: "eye_style", label: "چشم" },
  { key: "hat", label: "کلاه" },
  { key: "hair", label: "مو" },
  { key: "neck", label: "گردن‌آویز" },
  { key: "extra", label: "وسیلهٔ اضافه" },
  { key: "prop", label: "وسیلهٔ دست" },
];

function isCancel(e: unknown): boolean {
  return typeof e === "object" && e !== null && (e as { code?: string }).code === "ERR_CANCELED";
}

/** دانلود با توکنِ ورود (لینکِ ساده سرآیندِ Authorization ندارد). */
async function downloadBlob(path: string, filename: string) {
  const res = await api.get(path, { responseType: "blob" });
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function ColourField({ label, value, disabled, onChange }: { label: string; value: string; disabled?: boolean; onChange: (v: string) => void }) {
  return (
    <label className="dz-field">
      <span>{label}</span>
      <span className="mc-colour">
        <input type="color" value={/^#[0-9a-f]{6}$/i.test(value) ? value : "#000000"} disabled={disabled} onChange={(e) => onChange(e.target.value)} aria-label={label} />
        <Input type="text" value={value} disabled={disabled} maxLength={7} onChange={(e) => onChange(e.target.value)} />
      </span>
    </label>
  );
}

export default function MascotPage() {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [ov, setOv] = useState<Overview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [draft, setDraft] = useState<Spec | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [scene, setScene] = useState<Scene>(DEFAULT_SCENE);
  const [bubbleText, setBubbleText] = useState("");
  const [bubbleKind, setBubbleKind] = useState("say");
  const [captionText, setCaptionText] = useState("");
  const [captionPos, setCaptionPos] = useState("bottom");
  const [tag, setTag] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [prevBusy, setPrevBusy] = useState(false);
  const [prevError, setPrevError] = useState<string | null>(null);
  const [items, setItems] = useState<RenderItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [claims, setClaims] = useState<{ message: string; found: Claim[] } | null>(null);
  const [allowClaims, setAllowClaims] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newRole, setNewRole] = useState("coach");
  const [newName, setNewName] = useState("");
  const [newLogo, setNewLogo] = useState(true);
  const top = useRef<HTMLDivElement>(null);

  const load = useCallback(async (keep?: number | null) => {
    try {
      const o = await mascotApi.overview(id);
      setOv(o);
      setSel((cur) => {
        const want = keep ?? cur;
        return o.mascots.find((m) => m.id === want)?.id ?? o.mascots[0]?.id ?? null;
      });
    } catch (e) {
      setLoadError(errorMessage(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const m: Mascot | undefined = ov?.mascots.find((x) => x.id === sel);
  const role = ov?.roles.find((r) => r.key === m?.role);

  // با عوضِ ماسکوت: پیش‌نویسِ ظاهر و صحنهٔ پیش‌فرضِ نقش
  const mKey = m ? JSON.stringify([m.id, m.version, m.locked, m.name, m.spec]) : "";
  useEffect(() => {
    if (!m) return;
    setDraft(m.spec);
    setNameDraft(m.name);
  }, [mKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const mid = m?.id ?? null;
  useEffect(() => {
    if (mid === null) return;
    const r = ov?.roles.find((x) => x.key === m?.role);
    if (r) setScene((s) => ({ ...s, background: r.background, expression: r.expression, pose: r.pose }));
    setItems([]);
    setPreview(null);
    mascotApi.shots(id, mid).then(setItems).catch(() => setItems([]));
  }, [mid]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = !!m && !!draft && (JSON.stringify(draft) !== JSON.stringify(m.spec) || nameDraft.trim() !== m.name);
  const locked = !!m?.locked;

  const sceneBody = useCallback((withSpec: boolean): Record<string, unknown> => ({
    size: scene.size, pose: scene.pose, expression: scene.expression, background: scene.background, position: scene.position, flip: scene.flip, prop: scene.prop,
    bubble: bubbleText.trim() ? { text: bubbleText, kind: bubbleKind } : null,
    caption: captionText.trim() ? { text: captionText, position: captionPos } : null,
    allow_claims: allowClaims,
    ...(withSpec && draft ? { spec: draft } : {}),
  }), [scene, bubbleText, bubbleKind, captionText, captionPos, allowClaims, draft]);

  // پیش‌نمایشِ زنده (با تأخیر؛ درخواستِ کهنه لغو می‌شود)
  const prevKey = useMemo(() => JSON.stringify([sceneBody(dirty), mid]), [sceneBody, dirty, mid]);
  useEffect(() => {
    if (mid === null || !draft) return;
    const ctl = new AbortController();
    const t = window.setTimeout(async () => {
      setPrevBusy(true);
      try {
        const p = await mascotApi.preview(id, mid, sceneBody(dirty), ctl.signal);
        setPreview(p);
        setPrevError(null);
      } catch (e) {
        if (!isCancel(e)) setPrevError(errorMessage(e));
      } finally {
        if (!ctl.signal.aborted) setPrevBusy(false);
      }
    }, 500);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, prevKey]);

  if (loadError) return <ErrorBox message={loadError} />;
  if (!ov) return <Spinner />;

  const opts = ov.options;
  const size = opts.sizes.find((s) => s.key === scene.size) ?? opts.sizes[0];
  const setS = (patch: Partial<Scene>) => setScene((s) => ({ ...s, ...patch }));
  const setLook = (patch: Partial<Spec>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const poseList = tag ? opts.poses.filter((p) => opts.pose_tags.find((t) => t.key === tag)?.poses.includes(p.key)) : opts.poses;

  async function run<T>(label: string, fn: () => Promise<T>): Promise<T | null> {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      return await fn();
    } catch (e) {
      const c = claimsOf(e);
      if (c) setClaims(c);
      else setError(errorMessage(e));
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function createMascot() {
    const made = await run("create", () => mascotApi.create(id, { role: newRole, name: newName.trim() || undefined, use_logo: newLogo && ov!.store.has_logo }));
    if (made) {
      setCreating(false);
      setNewName("");
      setNotice(`ماسکوتِ «${made.name}» با رنگ‌ها${made.has_logo ? " و لوگوی" : "ی"} برندِ شما ساخته شد؛ ظاهرش را ببینید و «تأییدِ ظاهر» را بزنید.`);
      await load(made.id);
    }
  }

  async function saveLook() {
    if (!m || !draft) return;
    const out = await run("save", () => mascotApi.patch(id, m.id, { name: nameDraft.trim() || m.name, spec: draft }));
    if (out) {
      setNotice("ظاهر ذخیره شد.");
      await load(m.id);
    }
  }

  async function resetLook() {
    if (!m || !window.confirm("ظاهر دوباره از روی نقش و رنگ‌های برندِ فروشگاه ساخته شود؟ تغییرهای ذخیره‌نشده از بین می‌رود.")) return;
    const out = await run("reset", () => mascotApi.patch(id, m.id, { reset_look: true }));
    if (out) await load(m.id);
  }

  async function changeRole(key: string) {
    if (!m || key === m.role) return;
    if (!window.confirm("با عوضِ نقش، ظاهر دوباره از روی نقشِ تازه و رنگ‌های برند ساخته می‌شود. ادامه بدهم؟")) return;
    const out = await run("role", () => mascotApi.patch(id, m.id, { role: key }));
    if (out) await load(m.id);
  }

  async function toggleLock() {
    if (!m) return;
    if (dirty && !locked) {
      setError("اول ظاهر را ذخیره کنید، بعد تأیید و قفل کنید.");
      return;
    }
    const out = await run("lock", () => (locked ? mascotApi.unlock(id, m.id) : mascotApi.lock(id, m.id)));
    if (out) {
      setNotice(locked ? "قفل باز شد؛ ظاهر دوباره قابلِ تغییر است." : `ظاهر تأیید شد (نسخهٔ ${fa(out.version)}). از این به بعد همهٔ پست‌ها دقیقاً همین شخصیت‌اند.`);
      await load(m.id);
    }
  }

  async function removeMascot() {
    if (!m || !window.confirm(`ماسکوتِ «${m.name}» پاک شود؟ عکس‌های ساخته‌شده در کتابخانهٔ ادیتورِ عکس می‌مانند.`)) return;
    const ok = await run("remove", async () => {
      await mascotApi.remove(id, m.id);
      return true;
    });
    if (ok) {
      setSel(null);
      await load(null);
    }
  }

  async function makeShot() {
    if (!m) return;
    setClaims(null);
    const r = await run("render", () => mascotApi.render(id, m.id, sceneBody(false)));
    if (r) {
      setItems((cur) => [r, ...cur.filter((x) => x.id !== r.id)]);
      setNotice(r.cached ? "همین تصویر قبلاً ساخته شده بود؛ همان آورده شد (در کتابخانهٔ ادیتورِ عکس هم هست)." : "تصویر ساخته و در کتابخانهٔ ادیتورِ عکس ذخیره شد.");
      await load(m.id);
    }
  }

  async function makeSticker(crop: "full" | "bust") {
    if (!m) return;
    const r = await run("sticker", () => mascotApi.sticker(id, m.id, { pose: scene.pose, expression: scene.expression, prop: scene.prop, flip: scene.flip, crop }));
    if (r) {
      setItems((cur) => [r, ...cur.filter((x) => x.id !== r.id)]);
      setNotice(`استیکرِ شفاف (${crop === "bust" ? "نیم‌تنه" : "تمام‌قد"}) ساخته شد؛ در کتابخانهٔ ادیتورِ عکس و تامنیل‌ساز می‌توانید برش‌نخورده از آن استفاده کنید.`);
    }
  }

  async function makeSheet() {
    if (!m) return;
    const r = await run("sheet", () => mascotApi.sheet(id, m.id));
    if (r) {
      setItems((cur) => [r, ...cur.filter((x) => x.id !== r.id)]);
      setNotice("برگهٔ مدل ساخته شد (کلیدِ رنگ، حالت‌ها و ژست‌ها).");
    }
  }

  async function runCheck() {
    if (!m) return;
    const r = await run("check", () => mascotApi.check(id, m.id));
    if (r) {
      setNotice(r.ok ? `همهٔ ${fa(r.total ?? 0)} تصویر (${fa(r.poses ?? 0)} ژست × ${fa(r.sizes ?? 0)} اندازه) قبول شد: شخصیت همه‌جا یکی است.` : "بعضی تصویرها رد شد؛ فهرستش پایین است.");
      await load(m.id);
    }
  }

  /** «استفاده در تامنیل»: استیکرِ شفافِ نیم‌تنه ⇒ تامنیل‌ساز با سوژهٔ آماده (بدونِ هیچ «حذفِ پس‌زمینه»ای). */
  async function useInThumbnail(existing?: RenderItem) {
    if (!m) return;
    const r = existing ?? await run("sticker", () => mascotApi.sticker(id, m.id, { pose: scene.pose, expression: scene.expression, prop: scene.prop, flip: scene.flip, crop: "bust" }));
    if (!r?.asset) return;
    const q = new URLSearchParams({ subject: String(r.asset.id) });
    if (!existing && bubbleText.trim()) q.set("title", bubbleText.trim());
    navigate(`/stores/${id}/thumbnails?${q.toString()}`);
  }

  async function removeItem(it: RenderItem) {
    if (!m) return;
    try {
      await mascotApi.removeShot(id, m.id, it.id);
      setItems((cur) => cur.filter((x) => x.id !== it.id));
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const colourKey = preview?.qa ?? null;
  const claimWarn = preview && preview.claims.length > 0 ? preview : null;

  return (
    <>
      <PageHeader
        title="ماسکوتِ برند"
        subtitle="یک شخصیتِ کارتونیِ ثابت با رنگ‌ها و لوگوی برندِ شما؛ در همهٔ پست‌ها، استوری‌ها و تامنیل‌ها دقیقاً یکی است — کشیده‌شده با کد، بدونِ هوش مصنوعی و بدونِ کارتِ گرافیک"
        actions={<>
          <Link to={`/stores/${id}/thumbnails`} className="u-btn u-btn-secondary">تامنیل‌ساز</Link>
          <Link to={`/stores/${id}/photo-editor`} className="u-btn u-btn-secondary">ادیتور عکس</Link>
        </>}
      />
      <div ref={top} />
      <div className="mb-4 flex flex-col gap-3">
        <Alert tone="info" title="شخصیتِ کارتونی، نه آدمِ واقعی">
          {ov.notes.join(" ")}
        </Alert>
        <ErrorBox message={error} />
        {notice && <Alert tone="ok">{notice}</Alert>}
      </div>

      {/* ───────────── ماسکوت‌ها */}
      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="mc-title" style={{ margin: 0 }}>ماسکوت‌های {ov.store.name}</h2>
          <span className="dz-muted">
            {ov.store.colors.length > 0 ? <>رنگ‌های برند: {ov.store.colors.map((c) => <i key={c} className="mc-dot" style={{ display: "inline-block", width: 14, height: 14, borderRadius: "50%", background: c, border: "1px solid var(--line-strong)", marginInlineStart: 4, verticalAlign: "middle" }} />)}</> : "هنوز رنگِ برندی ثبت نشده؛ رنگ‌ها را در «ادیتور عکس ⇐ سبکِ برند» بگذارید."}
            {ov.store.has_logo ? " · لوگو دارد" : ""}
          </span>
        </div>
        <div className="mc-list">
          {ov.mascots.map((x) => (
            <button key={x.id} type="button" className="mc-mascot" aria-pressed={x.id === sel} onClick={() => { setSel(x.id); setCreating(false); }}>
              {x.cover ? <img src={x.cover} alt={x.name} loading="lazy" /> : <span className="mc-cover">هنوز تصویری نساخته‌اید</span>}
              <b>{x.name}</b>
              <span className="flex flex-wrap gap-1">
                <Badge tone="brand">{x.role_fa}</Badge>
                {x.locked ? <Badge tone="ok">نسخهٔ {fa(x.version)} · قفل</Badge> : <Badge tone="warn">پیش‌نویس</Badge>}
              </span>
            </button>
          ))}
          {ov.mascots.length < ov.limits.max_mascots && (
            <button type="button" className="mc-mascot mc-mascot-add" onClick={() => setCreating(true)}>
              <b>+ ماسکوتِ تازه</b>
              <span className="dz-muted">از یک نقشِ آماده شروع کنید</span>
            </button>
          )}
        </div>
        {creating && (
          <div className="mt-4">
            <h3 className="mc-sub">نقش را انتخاب کنید (رنگ‌های برندِ شما روی کلاه، پیش‌بند و وسیله می‌نشیند)</h3>
            <div className="mc-roles" role="group" aria-label="نقش">
              {ov.roles.map((r) => (
                <button key={r.key} type="button" className="mc-role" aria-pressed={newRole === r.key} onClick={() => setNewRole(r.key)}>
                  <b>{r.fa}</b>
                  <span>{r.hint}</span>
                </button>
              ))}
            </div>
            <div className="mc-fields mt-3">
              <label className="dz-field">
                <span>نامِ ماسکوت (اختیاری)</span>
                <Input value={newName} maxLength={80} onChange={(e) => setNewName(e.target.value)} placeholder={`مثلاً: ${ov.roles.find((r) => r.key === newRole)?.fa ?? "مربی"} ${ov.store.name}`} />
              </label>
              <label className="dz-field" style={{ alignSelf: "end" }}>
                <span>
                  <input type="checkbox" checked={newLogo && ov.store.has_logo} disabled={!ov.store.has_logo} onChange={(e) => setNewLogo(e.target.checked)} /> لوگوی فروشگاه روی سینه
                </span>
                {!ov.store.has_logo && <span className="dz-muted">فروشگاه لوگو ندارد.</span>}
              </label>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button onClick={() => void createMascot()} disabled={busy === "create"}>{busy === "create" ? "در حالِ ساخت…" : "ساختنِ ماسکوت"}</Button>
              <Button variant="ghost" onClick={() => setCreating(false)}>بستن</Button>
            </div>
          </div>
        )}
      </Card>

      {!m || !draft ? (
        <Card>
          <EmptyState icon="users" title="هنوز ماسکوتی ندارید" description="با دکمهٔ «ماسکوتِ تازه» یک نقش انتخاب کنید؛ ماسکوت با رنگ‌ها و لوگوی برندِ شما ساخته می‌شود و در چند ثانیه می‌توانید از آن پست و استوری و تامنیل بسازید.">
            <Button onClick={() => setCreating(true)}>ماسکوتِ تازه</Button>
          </EmptyState>
        </Card>
      ) : (
        <div className="mc-root">
          {/* ───────────── کنترل‌ها */}
          <div className="mc-controls">
            <Card>
              <h2 className="mc-title"><i>۱</i> ظاهرِ شخصیت</h2>
              {locked && (
                <div className="mb-3">
                  <Alert tone="ok" title={`ظاهر تأیید و قفل شده است (نسخهٔ ${fa(m.version)})`}>
                    تا «بازکردنِ قفل» ظاهر عوض نمی‌شود؛ با نسخهٔ تازه فقط تصویرهای تازه ساخته می‌شود و تصویرهای قبلی دست نمی‌خورد.
                  </Alert>
                </div>
              )}
              <div className="mc-fields">
                <label className="dz-field wide">
                  <span>نامِ ماسکوت</span>
                  <Input value={nameDraft} maxLength={80} disabled={locked} onChange={(e) => setNameDraft(e.target.value)} />
                </label>
                <label className="dz-field wide">
                  <span>نقش</span>
                  <Select value={m.role} disabled={locked} onChange={(e) => void changeRole(e.target.value)}>
                    {ov.roles.map((r) => <option key={r.key} value={r.key}>{r.fa} — {r.hint}</option>)}
                  </Select>
                </label>
                {CHOICE_FIELDS.map((f) => (
                  <label key={f.key} className="dz-field">
                    <span>{f.label}</span>
                    <Select value={String(draft[f.key])} disabled={locked} onChange={(e) => setLook({ [f.key]: e.target.value } as Partial<Spec>)}>
                      {(opts.choices[f.key as string] ?? []).map((o) => <option key={o.key} value={o.key}>{o.fa}</option>)}
                    </Select>
                  </label>
                ))}
                <label className="dz-field">
                  <span>لوگوی فروشگاه</span>
                  <Select value={draft.logo} disabled={locked || !ov.store.has_logo} onChange={(e) => setLook({ logo: e.target.value })}>
                    {(opts.choices.logo ?? []).map((o) => <option key={o.key} value={o.key}>{o.fa}</option>)}
                  </Select>
                  {!ov.store.has_logo && <span className="dz-muted">لوگو در «سبکِ برند» ثبت نشده.</span>}
                </label>
              </div>
              <h3 className="mc-sub">رنگ‌ها (پیش‌فرض: رنگ‌های برندِ شما)</h3>
              <div className="mc-fields">
                {COLOUR_FIELDS.map((f) => (
                  <ColourField key={f.key} label={f.label} value={String(draft[f.key])} disabled={locked} onChange={(v) => setLook({ [f.key]: v } as Partial<Spec>)} />
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={() => void saveLook()} disabled={!dirty || locked || busy === "save"}>{busy === "save" ? "در حالِ ذخیره…" : dirty ? "ذخیرهٔ ظاهر" : "ذخیره شده"}</Button>
                <Button variant="secondary" onClick={() => void toggleLock()} disabled={busy === "lock"}>{locked ? "بازکردنِ قفل" : "تأییدِ ظاهر (قفل)"}</Button>
                <Button variant="ghost" onClick={() => void resetLook()} disabled={locked}>بازتنظیم از رنگ‌های برند</Button>
                <Button variant="ghost" onClick={() => void removeMascot()}>حذفِ ماسکوت</Button>
              </div>
              <h3 className="mc-sub">کلیدِ رنگ و جملهٔ هویت</h3>
              <div className="mc-key">
                {m.palette.map((p, i) => (
                  <span key={`${p.role}-${i}`}><i style={{ background: p.hex }} />{p.hex.toUpperCase()}</span>
                ))}
              </div>
              <p className="dz-muted mt-2" dir="ltr" style={{ textAlign: "left" }}>{m.anchor}</p>
            </Card>

            <Card>
              <h2 className="mc-title"><i>۲</i> ژست و صحنه</h2>
              <h3 className="mc-sub">شخصیت چه کار کند؟</h3>
              <div className="mc-chips" role="group" aria-label="برچسب">
                <button type="button" className="mc-chip" aria-pressed={tag === ""} onClick={() => setTag("")}>همه ({fa(opts.poses.length)})</button>
                {opts.pose_tags.map((t) => (
                  <button key={t.key} type="button" className="mc-chip" aria-pressed={tag === t.key} onClick={() => setTag(t.key)}>{t.fa}</button>
                ))}
              </div>
              <div className="mc-poses mt-2" role="group" aria-label="ژست">
                {poseList.map((p) => (
                  <button key={p.key} type="button" className="mc-pose" aria-pressed={scene.pose === p.key} onClick={() => setS({ pose: p.key })} title={p.en}>{p.fa}</button>
                ))}
              </div>
              <h3 className="mc-sub">حالتِ چهره</h3>
              <div className="mc-chips" role="group" aria-label="حالتِ چهره">
                {opts.expressions.map((e) => (
                  <button key={e.key} type="button" className="mc-chip" aria-pressed={scene.expression === e.key} onClick={() => setS({ expression: e.key })}>{e.fa}</button>
                ))}
              </div>
              <h3 className="mc-sub">پس‌زمینه</h3>
              <div className="dz-muted mb-1">صحنه‌های فروشگاهی با رنگ‌های برندِ شما کشیده می‌شوند</div>
              <div className="mc-chips" role="group" aria-label="پس‌زمینه">
                {opts.backgrounds.filter((b) => b.group === "marketing").map((b) => (
                  <button key={b.key} type="button" className="mc-chip" aria-pressed={scene.background === b.key} onClick={() => setS({ background: b.key })}>{b.fa}</button>
                ))}
              </div>
              <div className="dz-muted mb-1 mt-2">صحنه‌های بیشتر</div>
              <div className="mc-chips">
                {opts.backgrounds.filter((b) => b.group === "scene").map((b) => (
                  <button key={b.key} type="button" className="mc-chip" aria-pressed={scene.background === b.key} onClick={() => setS({ background: b.key })}>{b.fa}</button>
                ))}
              </div>
              <h3 className="mc-sub">اندازهٔ خروجی</h3>
              <div className="mc-sizes" role="group" aria-label="اندازه">
                {opts.sizes.map((s) => (
                  <button key={s.key} type="button" className="mc-size" aria-pressed={scene.size === s.key} onClick={() => setS({ size: s.key })}>
                    <b>{s.fa}</b>
                    <span>{fa(s.w)}×{fa(s.h)}</span>
                  </button>
                ))}
              </div>
              {scene.size === "story" && <p className="dz-muted mt-2">در استوری، متن و شخصیت از ۱۳٪ِ بالا و ۱۸٪ِ پایین (جایی که برنامه دکمه و نام می‌گذارد) دور می‌ماند؛ اعدادِ پلتفرم تقریبی‌اند.</p>}
              <div className="mc-fields mt-3">
                <label className="dz-field">
                  <span>جای شخصیت</span>
                  <Select value={scene.position} onChange={(e) => setS({ position: e.target.value })}>
                    {opts.positions.map((p) => <option key={p.key} value={p.key}>{p.fa}</option>)}
                  </Select>
                </label>
                <label className="dz-field">
                  <span>وسیلهٔ دست</span>
                  <Select value={scene.prop} onChange={(e) => setS({ prop: e.target.value })}>
                    <option value="auto">خودکار (وسیلهٔ نقش و ژست)</option>
                    <option value="none">بدونِ وسیله</option>
                    {(opts.choices.prop ?? []).filter((o) => o.key !== "none").map((o) => <option key={o.key} value={o.key}>{o.fa}</option>)}
                  </Select>
                </label>
                <label className="dz-field">
                  <span><input type="checkbox" checked={scene.flip} onChange={(e) => setS({ flip: e.target.checked })} /> رو به چپ</span>
                </label>
              </div>
            </Card>

            <Card>
              <h2 className="mc-title"><i>۳</i> متنِ حباب و کپشن</h2>
              <div className="mc-fields">
                <label className="dz-field wide">
                  <span>حبابِ گفتار (اختیاری)</span>
                  <Input value={bubbleText} maxLength={ov.limits.max_text} onChange={(e) => setBubbleText(e.target.value)} placeholder="مثلاً: با چغر، *چغر‌تر* شو" />
                </label>
                <label className="dz-field">
                  <span>نوعِ حباب</span>
                  <Select value={bubbleKind} onChange={(e) => setBubbleKind(e.target.value)}>
                    {opts.bubble_kinds.map((k) => <option key={k.key} value={k.key}>{k.fa}</option>)}
                  </Select>
                </label>
                <span />
                <label className="dz-field wide">
                  <span>کپشنِ نواری (اختیاری)</span>
                  <Input value={captionText} maxLength={ov.limits.max_text} onChange={(e) => setCaptionText(e.target.value)} placeholder="یک جمله زیرِ یا بالای تصویر" />
                </label>
                <label className="dz-field">
                  <span>جای کپشن</span>
                  <Select value={captionPos} onChange={(e) => setCaptionPos(e.target.value)}>
                    <option value="bottom">پایین</option>
                    <option value="top">بالا</option>
                  </Select>
                </label>
              </div>
              <p className="dz-muted mt-2">کلمهٔ مهم را بینِ دو ستاره بگذارید تا به رنگِ برند دربیاید: <b>*کلمه*</b>. حباب و کپشن فقط متنِ شماست؛ قیمت، آمار، وعدهٔ نتیجه، نظرِ مشتری و ادعای پزشکی ننویسید.</p>
              {ov.lines.length > 0 && (
                <>
                  <h3 className="mc-sub">جمله‌های پیشنهادیِ بی‌ادعا (برای شروع)</h3>
                  <div className="mc-lines">
                    {ov.lines.slice(0, 12).map((l) => (
                      <button key={l.text} type="button" className="mc-line" onClick={() => setBubbleText(l.text)} title={l.source === "generic" ? "جملهٔ عمومی" : `از واقعیت‌های تأییدشدهٔ برند: ${l.source}`}>
                        {l.text}{l.source !== "generic" ? " ✓" : ""}
                      </button>
                    ))}
                  </div>
                </>
              )}
              {(claims || claimWarn) && (
                <div className="mt-3">
                  <Alert tone="warn" title="این متن ادعا دارد">
                    {(claims?.message || claimWarn?.claims_message) ?? ""}
                    <div className="mt-1 flex flex-wrap gap-1">
                      {(claims?.found ?? claimWarn?.claims ?? []).map((c) => <Badge key={c.code} tone="warn">{c.label_fa}: {c.term}</Badge>)}
                    </div>
                    <label className="mt-2 block text-sm">
                      <input type="checkbox" checked={allowClaims} onChange={(e) => { setAllowClaims(e.target.checked); if (e.target.checked) setClaims(null); }} /> این ادعا را خودم تأیید کرده‌ام و منبعش را دارم
                    </label>
                  </Alert>
                </div>
              )}
            </Card>

            <Card>
              <h2 className="mc-title"><i>۴</i> ساخت</h2>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => void makeShot()} disabled={busy !== null}>{busy === "render" ? "در حالِ ساخت…" : `ساخت و ذخیره (${size.fa})`}</Button>
                <Button variant="secondary" onClick={() => void useInThumbnail()} disabled={busy !== null} title="استیکرِ شفافِ نیم‌تنه ساخته می‌شود و تامنیل‌ساز با آن باز می‌شود؛ هیچ «حذفِ پس‌زمینه»ای لازم نیست">
                  {busy === "sticker" ? "در حالِ ساخت…" : "استفاده در تامنیل"}
                </Button>
                <Button variant="secondary" onClick={() => void makeSticker("full")} disabled={busy !== null}>استیکرِ شفاف (تمام‌قد)</Button>
                <Button variant="secondary" onClick={() => void makeSticker("bust")} disabled={busy !== null}>استیکرِ شفاف (نیم‌تنه)</Button>
                <Button variant="ghost" onClick={() => void makeSheet()} disabled={busy !== null}>{busy === "sheet" ? "در حالِ ساخت…" : "برگهٔ مدل"}</Button>
                <Button variant="ghost" onClick={() => void runCheck()} disabled={busy !== null} title="همهٔ ژست‌ها در چهار اندازه کشیده و رنگ‌های امضا سنجیده می‌شود">
                  {busy === "check" ? "در حالِ بررسی…" : "بررسیِ ثبات"}
                </Button>
              </div>
              <p className="dz-muted mt-2">هر تصویر در «ادیتور عکس» و «تامنیل‌ساز» و «استودیوی موشن» (<span dir="ltr">photo:شناسه</span>) هم در دسترس است. ساختنِ دوباره با همان گزینه‌ها همان تصویر را برمی‌گرداند.</p>
              {m.check.at && (
                <div className="mt-3">
                  <Alert tone={m.check.ok ? "ok" : "bad"} title={m.check.ok ? "ثبات: شخصیت در همهٔ ژست‌ها و اندازه‌ها یکی است" : "ثبات: بعضی تصویرها رد شد"}>
                    {fa(m.check.passed ?? 0)} از {fa(m.check.total ?? 0)} تصویر ({fa(m.check.poses ?? 0)} ژست × {fa(m.check.sizes ?? 0)} اندازه) قبول شد{m.check.seconds ? ` · ${fa(m.check.seconds)} ثانیه` : ""}.
                    {(m.check.failed ?? []).slice(0, 5).map((f, i) => <div key={i}>ژستِ «{opts.poses.find((p) => p.key === f.pose)?.fa ?? f.pose}» در «{opts.sizes.find((s) => s.key === f.size)?.fa ?? f.size}»: {f.notes.join("؛ ")}</div>)}
                  </Alert>
                </div>
              )}
            </Card>
          </div>

          {/* ───────────── پیش‌نمایش و خروجی‌ها */}
          <div className="mc-preview-col">
            <div className="mc-sticky">
              <Card>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="mc-title" style={{ margin: 0 }}>پیش‌نمایش</h2>
                  <span className="flex flex-wrap gap-1">
                    <Badge tone={locked ? "ok" : "warn"}>{locked ? `نسخهٔ ${fa(m.version)} · قفل` : "پیش‌نویس"}</Badge>
                    {dirty && <Badge tone="warn">ذخیره‌نشده</Badge>}
                    {colourKey && <Badge tone={colourKey.ok ? "ok" : "bad"}>{colourKey.ok ? "همهٔ رنگ‌ها دیده می‌شود" : "رنگی گم شده"}</Badge>}
                  </span>
                </div>
                <ErrorBox message={prevError} />
                <div className={`mc-preview-frame ${prevBusy ? "is-busy" : ""} ${size.h > size.w ? "mc-tall" : ""}`} style={{ aspectRatio: `${size.w} / ${size.h}` }}>
                  {preview ? <img src={preview.image} alt="پیش‌نمایشِ ماسکوت" /> : <Spinner />}
                  {prevBusy && preview && <div className="mc-preview-busy"><Spinner /></div>}
                </div>
                {colourKey && (
                  <div className="mc-key mt-3" aria-label="کلیدِ رنگ">
                    {colourKey.colours.map((c) => (
                      <span key={c.hex} className={c.found ? "" : "miss"}><i style={{ background: c.hex }} />{c.found ? "دیده می‌شود" : "دیده نمی‌شود"}</span>
                    ))}
                  </div>
                )}
                {colourKey && colourKey.notes.map((n) => <p key={n} className="dz-muted" style={{ color: "var(--warn)" }}>{n}</p>)}
                <p className="dz-muted mt-2">{role ? `نقش: ${role.fa}. ` : ""}اندازهٔ نهایی {fa(size.w)}×{fa(size.h)} است؛ این پیش‌نمایش کوچک‌شده است.</p>
              </Card>
            </div>

            <Card>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h2 className="mc-title" style={{ margin: 0 }}>ساخته‌شده‌ها ({fa(items.length)})</h2>
                <Button size="sm" variant="ghost" onClick={() => mascotApi.shots(id, m.id).then(setItems).catch((e) => setError(errorMessage(e)))}>تازه‌سازی</Button>
              </div>
              {items.length === 0 ? (
                <EmptyState icon="image" title="هنوز چیزی نساخته‌اید" description="با «ساخت و ذخیره» یا «استیکرِ شفاف» اولین تصویر را بسازید؛ همه در کتابخانهٔ ادیتورِ عکس هم می‌آیند." />
              ) : (
                <div className="mc-gallery">
                  {items.map((it) => (
                    <div key={it.id} className="mc-card">
                      {it.urls.thumb ? <img src={it.urls.thumb} alt={it.kind_fa} loading="lazy" /> : <span className="dz-noimg" />}
                      <div className="mc-card-meta">
                        <Badge tone="brand">{it.kind_fa}</Badge>
                        <span>{fa(it.width)}×{fa(it.height)}</span>
                        <span>{fa(it.size_kb)} کیلوبایت</span>
                        {it.version > 0 && <Badge tone={it.locked ? "ok" : "neutral"}>نسخهٔ {fa(it.version)}</Badge>}
                        {it.qa.ok === false && <Badge tone="bad">رنگی گم شده</Badge>}
                      </div>
                      <div className="mc-card-actions">
                        <Button size="sm" variant="secondary" onClick={() => void downloadBlob(mascotApi.downloadPath(id, m.id, it.id), `mascot-${it.kind}-${it.id}.png`).catch((e) => setError(errorMessage(e)))}>PNG</Button>
                        {it.kind === "sticker" && <Button size="sm" variant="secondary" onClick={() => void useInThumbnail(it)}>استفاده در تامنیل</Button>}
                        <Button size="sm" variant="ghost" onClick={() => void removeItem(it)}>حذف</Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
