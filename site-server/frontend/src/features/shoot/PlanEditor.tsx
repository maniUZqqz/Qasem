import { useEffect, useState } from "react";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card, Field, Input, Select, Spinner, TextArea } from "../../components/ui";
import Portal, { LAYER } from "./Portal";
import { ShotDiagram } from "./ShotGuide";
import { Overview, PhotoShot, Plan, Session, VideoShot, fa, shootApi } from "./api";

/** برنامهٔ تحلیل‌شده، ویرایش‌پذیر. سرور هر تغییر را دوباره اعتبارسنجی می‌کند (validate_plan). */

const SOURCE: Record<string, [string, "ok" | "info" | "brand"]> = {
  ai: ["تحلیل با هوش مصنوعی", "ok"],
  template: ["الگوی آماده", "info"],
  edited: ["ویرایش‌شده", "brand"],
};

function move<T>(list: T[], i: number, d: number): T[] {
  const j = i + d;
  if (j < 0 || j >= list.length) return list;
  const out = [...list];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

export default function PlanEditor({
  storeId,
  session,
  overview,
  onSession,
  onStart,
}: {
  storeId: string;
  session: Session;
  overview: Overview;
  onSession: (s: Session) => void;
  onStart: () => void;
}) {
  const [plan, setPlan] = useState<Plan>(session.plan);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const analyzing = session.state === "ANALYZING";

  useEffect(() => {
    if (!dirty) setPlan(session.plan);
  }, [session.plan, dirty]);

  const edit = (p: Plan) => {
    setPlan(p);
    setDirty(true);
  };
  const setPhoto = (i: number, patch: Partial<PhotoShot>) =>
    edit({ ...plan, photos: plan.photos.map((p, k) => (k === i ? { ...p, ...patch } : p)) });
  const setVideo = (i: number, patch: Partial<VideoShot>, regenerate = false) =>
    edit({
      ...plan,
      // حرکت/مدت/زاویه عوض شد ⇐ دستورِ قبلی دیگر درست نیست؛ سرور دستورِ تازه می‌سازد
      video: plan.video.map((v, k) => (k === i ? { ...v, ...patch, ...(regenerate ? { instruction: "", cues: [] } : {}) } : v)),
    });

  const save = async (): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      const s = await shootApi.savePlan(storeId, session.id, plan);
      setNotes(s.problems || []);
      setDirty(false);
      onSession(s);
      setPlan(s.plan);
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const reanalyze = async () => {
    setBusy(true);
    setError(null);
    try {
      setDirty(false);
      onSession(await shootApi.action(storeId, session.id, "analyze"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const usedAngles = new Set(plan.photos.map((p) => p.angle));
  const [src, tone] = SOURCE[session.plan_source] ?? ["", "info"];

  return (
    <div className="space-y-4 pb-24" data-testid="plan-editor">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-sm" style={{ color: "var(--text-3)" }}>
              نوعِ محصول
            </div>
            <div className="text-lg font-extrabold" style={{ color: "var(--text)" }}>
              {plan.product_type} <span className="text-sm font-normal">({plan.category_label})</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {src && <Badge tone={tone}>{src}</Badge>}
            <Button variant="secondary" size="sm" onClick={() => void reanalyze()} disabled={busy || analyzing}>
              <Icon name="refresh" size={14} />
              تحلیلِ دوباره
            </Button>
          </div>
        </div>
        {analyzing && (
          <div className="mt-3 flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }} data-testid="analyzing">
            <Spinner size={16} /> هوش مصنوعی عکس و توضیحِ محصول را می‌خواند… (تا آماده شود، برنامهٔ آمادهٔ همین دسته را
            می‌بینی و می‌توانی شروع کنی)
          </div>
        )}
        {(plan.notes || []).concat(notes).map((n) => (
          <p key={n} className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
            {n}
          </p>
        ))}
      </Card>

      <Card>
        <div className="mb-2 font-bold" style={{ color: "var(--text)" }}>
          ویژگی‌های فروش‌ساز
        </div>
        <div className="space-y-2">
          {plan.features.map((f, i) => (
            <div key={i} className="flex gap-2">
              <Input value={f} onChange={(e) => edit({ ...plan, features: plan.features.map((x, k) => (k === i ? e.target.value : x)) })} />
              <Button variant="ghost" size="sm" onClick={() => edit({ ...plan, features: plan.features.filter((_x, k) => k !== i) })} aria-label="حذف">
                <Icon name="x" size={14} />
              </Button>
            </div>
          ))}
          {plan.features.length < 5 && (
            <Button variant="secondary" size="sm" onClick={() => edit({ ...plan, features: [...plan.features, ""] })}>
              <Icon name="plus" size={14} />
              ویژگی
            </Button>
          )}
        </div>
      </Card>

      <Card>
        <div className="mb-2 font-bold" style={{ color: "var(--text)" }}>
          زاویه‌های عکس ({fa(plan.photos.length)})
        </div>
        <div className="space-y-3">
          {plan.photos.map((p, i) => (
            <div key={p.key} className="rounded-xl p-3" style={{ border: "1px solid var(--line)" }} data-testid={`plan-photo-${p.angle}`}>
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="font-bold" style={{ color: "var(--text)" }}>
                  {fa(i + 1)}. {p.title}
                </span>
                <span className="flex gap-1">
                  <Button variant="ghost" size="sm" onClick={() => edit({ ...plan, photos: move(plan.photos, i, -1) })} aria-label="بالا">
                    <Icon name="up" size={14} />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => edit({ ...plan, photos: move(plan.photos, i, 1) })} aria-label="پایین">
                    <Icon name="down" size={14} />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => edit({ ...plan, photos: plan.photos.filter((_x, k) => k !== i) })} aria-label="حذف">
                    <Icon name="trash" size={14} />
                  </Button>
                </span>
              </div>
              <div className="grid gap-2 sm:grid-cols-[1fr_180px]">
                <TextArea rows={2} value={p.instruction} onChange={(e) => setPhoto(i, { instruction: e.target.value })} />
                <ShotDiagram shot={p} animate={false} size={180} />
              </div>
            </div>
          ))}
          <Select
            value=""
            onChange={(e) => {
              const a = e.target.value;
              if (!a) return;
              const title = overview.angles.find((x) => x.key === a)?.title || a;
              edit({
                ...plan,
                photos: [
                  ...plan.photos,
                  { key: `p_${a}`, kind: "photo", angle: a, title, instruction: "", overlay: { arrow: "none", yaw: 0, pitch: 0, distance: "medium" }, check: {} },
                ],
              });
            }}
          >
            <option value="">+ افزودنِ زاویه…</option>
            {overview.angles
              .filter((a) => !usedAngles.has(a.key))
              .map((a) => (
                <option key={a.key} value={a.key}>
                  {a.title}
                </option>
              ))}
          </Select>
        </div>
      </Card>

      {session.purpose === "ad" && (
        <Card>
          <div className="mb-2 font-bold" style={{ color: "var(--text)" }}>
            نماهای ویدیو ({fa(plan.video.length)}) — به ترتیبِ تدوین
          </div>
          <div className="space-y-3">
            {plan.video.map((v, i) => (
              <div key={v.key + i} className="rounded-xl p-3" style={{ border: "1px solid var(--line)" }} data-testid={`plan-video-${i}`}>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="font-bold" style={{ color: "var(--text)" }}>
                    {fa(i + 1)}. {v.title}
                  </span>
                  <span className="flex gap-1">
                    <Button variant="ghost" size="sm" onClick={() => edit({ ...plan, video: move(plan.video, i, -1) })} aria-label="بالا">
                      <Icon name="up" size={14} />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => edit({ ...plan, video: move(plan.video, i, 1) })} aria-label="پایین">
                      <Icon name="down" size={14} />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => edit({ ...plan, video: plan.video.filter((_x, k) => k !== i) })} aria-label="حذف">
                      <Icon name="trash" size={14} />
                    </Button>
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Field label="حرکت">
                    <Select value={v.move} onChange={(e) => setVideo(i, { move: e.target.value }, true)}>
                      {overview.moves.map((m) => (
                        <option key={m.key} value={m.key}>
                          {m.title}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="ثانیه">
                    <Input type="number" min={2} max={12} value={v.duration} onChange={(e) => setVideo(i, { duration: Number(e.target.value) }, true)} />
                  </Field>
                  {v.move === "orbit" && (
                    <Field label="درجه">
                      <Input type="number" min={15} max={360} step={15} value={v.degrees ?? 90} onChange={(e) => setVideo(i, { degrees: Number(e.target.value) }, true)} />
                    </Field>
                  )}
                  {["orbit", "pan", "reveal", "tilt"].includes(v.move) && (
                    <Field label="جهت">
                      <Select value={v.direction} onChange={(e) => setVideo(i, { direction: e.target.value }, true)}>
                        {(v.move === "tilt" ? ["up", "down"] : ["right", "left"]).map((d) => (
                          <option key={d} value={d}>
                            {{ right: "راست", left: "چپ", up: "بالا", down: "پایین" }[d]}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  )}
                </div>
                <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_180px]">
                  <div className="space-y-2">
                    <TextArea rows={2} value={v.instruction} placeholder="خالی بگذار تا خودکار ساخته شود" onChange={(e) => setVideo(i, { instruction: e.target.value })} />
                    <Input value={v.caption || ""} placeholder="متنِ روی این نما" onChange={(e) => setVideo(i, { caption: e.target.value })} />
                  </div>
                  <ShotDiagram shot={v} animate={false} size={180} />
                </div>
              </div>
            ))}
            {plan.video.length < 6 && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  edit({
                    ...plan,
                    video: [
                      ...plan.video,
                      { key: `v${plan.video.length + 1}`, kind: "video", move: "orbit", title: "چرخش", instruction: "", duration: 5, speed: "slow", distance_cm: 40, degrees: 90, direction: "right", overlay: { arrow: "orbit_right", yaw: 90, pitch: 0, distance: "medium" }, cues: [], check: {} },
                    ],
                  })
                }
              >
                <Icon name="plus" size={14} />
                نمای تازه
              </Button>
            )}
          </div>
        </Card>
      )}

      {session.purpose === "ad" && (
        <Card>
          <div className="mb-2 font-bold" style={{ color: "var(--text)" }}>
            متنِ تبلیغ
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="تیتر">
              <Input value={plan.ad.headline} onChange={(e) => edit({ ...plan, ad: { ...plan.ad, headline: e.target.value } })} />
            </Field>
            <Field label="دعوت به خرید">
              <Input value={plan.ad.cta} onChange={(e) => edit({ ...plan, ad: { ...plan.ad, cta: e.target.value } })} />
            </Field>
            <div className="sm:col-span-2">
              <Field label="متنِ گوینده (اختیاری)">
                <TextArea rows={3} value={plan.ad.voiceover} onChange={(e) => edit({ ...plan, ad: { ...plan.ad, voiceover: e.target.value } })} />
              </Field>
            </div>
          </div>
        </Card>
      )}

      {error && <Alert tone="bad">{error}</Alert>}

      <Portal>
      <div className="fixed inset-x-0 bottom-0 flex gap-2 p-3" style={{ background: "var(--bg)", borderTop: "1px solid var(--line-strong)", zIndex: LAYER.bar }}>
        <Button variant="secondary" className="flex-1" style={{ minHeight: 52 }} disabled={!dirty || busy} onClick={() => void save()} data-testid="save-plan">
          <Icon name="check" size={16} />
          ذخیرهٔ برنامه
        </Button>
        <Button
          className="flex-1"
          style={{ minHeight: 52 }}
          disabled={busy}
          onClick={async () => {
            if (dirty && !(await save())) return;
            onStart();
          }}
          data-testid="start-capture"
        >
          شروعِ عکاسی و فیلم‌برداری
          <Icon name="next" size={16} />
        </Button>
      </div>
      </Portal>
    </div>
  );
}
