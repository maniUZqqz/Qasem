import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card, Field, Input, Select, TextArea } from "../../components/ui";
import { useFeature } from "../panel/FlagsContext";
import { Output, Overview, Session, fa, shootApi } from "./api";

/** تدوینِ خودکار و خروجی‌ها: ویدیوی تبلیغاتی (۹:۱۶، ۱:۱) و پوستر (۱:۱، ۴:۵، ۹:۱۶)، با نسخه‌ها. */

const ASPECT_FA: Record<string, string> = { "9:16": "۹:۱۶ (استوری/ریلز)", "1:1": "۱:۱ (پست)", "4:5": "۴:۵ (پستِ بلند)" };

export default function OutputsPanel({
  storeId,
  session,
  overview,
  onSession,
}: {
  storeId: string;
  session: Session;
  overview: Overview;
  onSession: (s: Session) => void;
}) {
  const plan = session.plan;
  const showVideo = useFeature("shoot.video") && session.purpose === "ad";
  const showPoster = useFeature("shoot.poster");
  const caps = overview.capabilities;
  const [title, setTitle] = useState(plan.ad.headline);
  const [features, setFeatures] = useState(plan.features.join("\n"));
  const [price, setPrice] = useState(plan.ad.price);
  const [oldPrice, setOldPrice] = useState("");
  const [cta, setCta] = useState(plan.ad.cta);
  const [logo, setLogo] = useState(true);
  // ویدیو
  const [vAspects, setVAspects] = useState<string[]>(["9:16"]);
  const [transition, setTransition] = useState("fade");
  const [stabilize, setStabilize] = useState(caps.stabilize);
  const [music, setMusic] = useState<string>(overview.music[0] ? String(overview.music[0].id) : "");
  const [musicDb, setMusicDb] = useState(-24);
  const [voiceover, setVoiceover] = useState(false);
  const [voText, setVoText] = useState(plan.ad.voiceover);
  const [outroTemplate, setOutroTemplate] = useState("bold");
  // پوستر
  const [pAspects, setPAspects] = useState<string[]>(["1:1", "4:5"]);
  const [template, setTemplate] = useState("clean");
  const [cutout, setCutout] = useState(true);
  const [photoTake, setPhotoTake] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const acceptedPhotos = useMemo(
    () => session.takes.filter((t) => t.kind === "photo" && t.accepted).sort((a, b) => b.score - a.score),
    [session.takes],
  );
  const acceptedVideoShots = useMemo(
    () => new Set(session.takes.filter((t) => t.kind === "video" && t.accepted).map((t) => t.shot)),
    [session.takes],
  );

  const texts = () => ({
    title,
    features: features.split("\n").map((f) => f.trim()).filter(Boolean),
    price,
    old_price: oldPrice,
    cta,
  });

  const make = async (kind: "video" | "poster") => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const s = await shootApi.makeOutputs(storeId, session.id, {
        kind,
        aspects: kind === "video" ? vAspects : pAspects,
        template: kind === "video" ? outroTemplate : template,
        options:
          kind === "video"
            ? { stabilize, transition, music: music ? Number(music) : null, music_level_db: musicDb, voiceover, voiceover_text: voText, logo, texts: texts() }
            : { cutout, take: photoTake, logo, texts: texts() },
      });
      onSession(s);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const act = async (o: Output, action: "product" | "content" | "editor") => {
    setError(null);
    try {
      const r = await shootApi.outputAction(storeId, session.id, o.id, action);
      onSession({ ...session, outputs: session.outputs.map((x) => (x.id === o.id ? r.output : x)) });
      setDone(
        action === "product"
          ? o.kind === "poster"
            ? "پوستر به عکس‌های محصول اضافه شد."
            : "ویدیو به ویدیوهای همین محصول (ادیتورِ ویدیو) رفت."
          : action === "content"
            ? "پوستر در «تصویرهای ساخته‌شده» است (استودیو، کپشن، کمپین)."
            : "ویدیو در ادیتورِ ویدیو است.",
      );
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const remove = async (o: Output) => {
    try {
      await shootApi.deleteOutput(storeId, session.id, o.id);
      onSession({ ...session, outputs: session.outputs.filter((x) => x.id !== o.id) });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const toggle = (list: string[], v: string, set: (x: string[]) => void) =>
    set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const bigBtn = { minHeight: 54 } as const;

  return (
    <div className="space-y-4 pb-10" data-testid="outputs-panel">
      <Card>
        <div className="mb-2 font-bold" style={{ color: "var(--text)" }}>
          هر مرحله کجا اجرا می‌شود
        </div>
        <ul className="space-y-1 text-sm leading-6" style={{ color: "var(--text-2)" }}>
          <li>• انتخابِ بهترین برداشت، برش، لرزش‌گیری{caps.stabilize ? "" : " (این ffmpeg ندارد)"}، نور و رنگ، متن، گذار، موسیقی: سرورِ سایت (ffmpeg با اولویتِ پایین)</li>
          <li>• گوینده: موتورِ گفتارِ سایت</li>
          <li>• پوستر: سرورِ سایت (Pillow)؛ حذفِ پس‌زمینه: سرورِ پردازش (GPU) — الان {caps.node_online ? "روشن" : "خاموش ⇐ زمینهٔ محو و رنگی"}</li>
          <li>• فضای خالیِ سرور: {overview.disk}</li>
        </ul>
      </Card>

      <Card>
        <div className="mb-2 font-bold" style={{ color: "var(--text)" }}>
          متن‌ها (برای ویدیو و پوستر)
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="نام / تیتر">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="دعوت به خرید">
            <Input value={cta} onChange={(e) => setCta(e.target.value)} />
          </Field>
          <Field label="قیمت">
            <Input value={price} onChange={(e) => setPrice(e.target.value)} />
          </Field>
          <Field label="قیمتِ قبل (خط‌خورده، اختیاری)">
            <Input value={oldPrice} onChange={(e) => setOldPrice(e.target.value)} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="ویژگی‌ها (هر خط یکی؛ روی نماها و پوستر)">
              <TextArea rows={3} value={features} onChange={(e) => setFeatures(e.target.value)} />
            </Field>
          </div>
          <label className="flex items-center gap-2 text-sm" style={{ minHeight: 40 }}>
            <input type="checkbox" checked={logo} onChange={(e) => setLogo(e.target.checked)} />
            لوگوی فروشگاه (از «پروفایل برند»)
          </label>
        </div>
      </Card>

      {showVideo && (
        <Card>
          <div className="mb-1 font-bold" style={{ color: "var(--text)" }}>
            ویدیوی تبلیغاتی
          </div>
          <p className="mb-3 text-sm" style={{ color: "var(--text-3)" }}>
            نماهای آماده: {fa(acceptedVideoShots.size)} از {fa(plan.video.length)}
            {acceptedVideoShots.size < plan.video.length ? " (نماهای بی‌برداشت کنار می‌روند؛ اگر کم باشد عکس‌ها هم با حرکتِ آرام می‌آیند)" : ""}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="mb-1 text-sm font-semibold">اندازه</div>
              {overview.aspects.video.map((a) => (
                <label key={a} className="flex items-center gap-2 text-sm" style={{ minHeight: 40 }}>
                  <input type="checkbox" checked={vAspects.includes(a)} onChange={() => toggle(vAspects, a, setVAspects)} />
                  {ASPECT_FA[a] || a}
                </label>
              ))}
            </div>
            <div className="space-y-2">
              <Field label="گذار بینِ نماها">
                <Select value={transition} onChange={(e) => setTransition(e.target.value)}>
                  {overview.transitions.map((t) => (
                    <option key={t.key} value={t.key}>
                      {t.title}
                    </option>
                  ))}
                </Select>
              </Field>
              <label className="flex items-center gap-2 text-sm" style={{ minHeight: 40 }}>
                <input type="checkbox" checked={stabilize} disabled={!caps.stabilize} onChange={(e) => setStabilize(e.target.checked)} />
                لرزش‌گیری {caps.stabilize ? "" : "(در دسترس نیست)"}
              </label>
            </div>
            <Field label="موسیقی (از کتابخانهٔ صدا)">
              <Select value={music} onChange={(e) => setMusic(e.target.value)}>
                <option value="">بی‌موسیقی</option>
                {overview.music.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.title} ({fa(Math.round(m.seconds))} ث)
                  </option>
                ))}
              </Select>
            </Field>
            {overview.music.length === 0 ? (
              <p className="self-end text-xs" style={{ color: "var(--text-3)" }}>
                کتابخانه موسیقی ندارد؛ در{" "}
                <Link to={`/stores/${storeId}/audio/music`} className="underline">
                  صدا › موسیقیِ زمینه
                </Link>{" "}
                بساز.
              </p>
            ) : (
              <Field label={`بلندیِ موسیقی (${fa(musicDb)} دسی‌بل)`}>
                <input type="range" min={-36} max={-12} value={musicDb} onChange={(e) => setMusicDb(Number(e.target.value))} className="w-full" />
              </Field>
            )}
            <div className="sm:col-span-2">
              <label className="flex items-center gap-2 text-sm" style={{ minHeight: 40 }}>
                <input type="checkbox" checked={voiceover} onChange={(e) => setVoiceover(e.target.checked)} />
                گوینده (متن به گفتار) — موسیقی زیرِ صدای گوینده پایین می‌آید
              </label>
              {voiceover && <TextArea rows={3} value={voText} onChange={(e) => setVoText(e.target.value)} />}
            </div>
            <Field label="طرحِ کارتِ پایانی">
              <Select value={outroTemplate} onChange={(e) => setOutroTemplate(e.target.value)}>
                {overview.templates.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.title}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Button className="mt-3 w-full" style={bigBtn} disabled={busy || vAspects.length === 0} onClick={() => void make("video")} data-testid="make-video">
            <Icon name="film" size={17} />
            ساختِ ویدیوی تبلیغاتی
          </Button>
        </Card>
      )}

      {showPoster && (
        <Card>
          <div className="mb-3 font-bold" style={{ color: "var(--text)" }}>
            پوسترِ تبلیغاتی
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="mb-1 text-sm font-semibold">طرح</div>
              {overview.templates.map((t) => (
                <label key={t.key} className="flex items-center gap-2 text-sm" style={{ minHeight: 40 }}>
                  <input type="radio" name="tpl" checked={template === t.key} onChange={() => setTemplate(t.key)} />
                  {t.title}
                </label>
              ))}
            </div>
            <div>
              <div className="mb-1 text-sm font-semibold">اندازه</div>
              {overview.aspects.poster.map((a) => (
                <label key={a} className="flex items-center gap-2 text-sm" style={{ minHeight: 40 }}>
                  <input type="checkbox" checked={pAspects.includes(a)} onChange={() => toggle(pAspects, a, setPAspects)} />
                  {ASPECT_FA[a] || a}
                </label>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm sm:col-span-2" style={{ minHeight: 40 }}>
              <input type="checkbox" checked={cutout} onChange={(e) => setCutout(e.target.checked)} />
              حذفِ پس‌زمینه {caps.node_online ? "(سرورِ پردازش روشن است)" : "(سرورِ پردازش خاموش است ⇐ زمینهٔ محو)"}
            </label>
          </div>
          {acceptedPhotos.length > 0 && (
            <div className="mt-2">
              <div className="mb-1 text-sm font-semibold">عکس</div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                <button
                  onClick={() => setPhotoTake(null)}
                  className="h-20 w-20 shrink-0 rounded-xl text-xs"
                  style={{ border: `2px solid ${photoTake === null ? "var(--brand)" : "var(--line)"}` }}
                >
                  بهترین (خودکار)
                </button>
                {acceptedPhotos.map((t) => (
                  <button key={t.id} onClick={() => setPhotoTake(t.id)} className="shrink-0 rounded-xl p-0.5" style={{ border: `2px solid ${photoTake === t.id ? "var(--brand)" : "var(--line)"}` }}>
                    <img src={t.thumb || t.url} alt="" className="h-[72px] w-[72px] rounded-lg object-cover" />
                  </button>
                ))}
              </div>
            </div>
          )}
          <Button className="mt-3 w-full" style={bigBtn} disabled={busy || pAspects.length === 0} onClick={() => void make("poster")} data-testid="make-poster">
            <Icon name="image" size={17} />
            ساختِ پوستر
          </Button>
        </Card>
      )}

      {error && <Alert tone="bad">{error}</Alert>}
      {done && <Alert tone="ok">{done}</Alert>}

      <div className="space-y-3">
        {session.outputs.map((o) => (
          <Card key={o.id}>
            <div data-testid={`output-${o.kind}`} data-state={o.state}>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div className="font-bold" style={{ color: "var(--text)" }}>
                  {o.kind === "video" ? "ویدیو" : "پوستر"} {ASPECT_FA[o.aspect] || o.aspect} — نسخهٔ {fa(o.version)}
                </div>
                <Badge tone={o.state === "READY" ? "ok" : o.state === "FAILED" ? "bad" : "info"}>
                  {o.state === "READY" ? "آماده" : o.state === "FAILED" ? "ناموفق" : o.message || "در صف"}
                </Badge>
              </div>
              {(o.state === "QUEUED" || o.state === "RUNNING") && (
                <div>
                  <div className="mb-1 text-sm" style={{ color: "var(--text-2)" }}>
                    {o.message}
                  </div>
                  <div className="u-meter">
                    <span style={{ width: `${Math.max(4, o.progress * 100)}%` }} />
                  </div>
                </div>
              )}
              {o.state === "FAILED" && <Alert tone="bad">{o.error}</Alert>}
              {o.state === "READY" && o.url && (
                <>
                  <div className="mb-2 overflow-hidden rounded-xl" style={{ background: "#000" }}>
                    {o.kind === "video" ? (
                      <video src={o.url} poster={o.thumb || undefined} controls playsInline className="max-h-[70vh] w-full" />
                    ) : (
                      <img src={o.url} alt="" className="max-h-[70vh] w-full object-contain" />
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <a href={o.url} download className="u-btn u-btn-secondary" style={bigBtn}>
                      <Icon name="download" size={16} />
                      دانلود
                    </a>
                    {o.kind === "poster" ? (
                      <>
                        <Button variant="secondary" style={bigBtn} onClick={() => void act(o, "product")}>
                          ذخیره در محصول
                        </Button>
                        <Button className="col-span-2" style={bigBtn} onClick={() => void act(o, "content")}>
                          استفاده در محتوا
                        </Button>
                      </>
                    ) : (
                      <Button style={bigBtn} onClick={() => void act(o, "editor")}>
                        استفاده در محتوا
                      </Button>
                    )}
                  </div>
                  {o.saved?.uploaded_videos?.length ? (
                    <Link to={`/stores/${storeId}/editor`} className="mt-2 block text-sm underline">
                      بازکردن در ادیتورِ ویدیو
                    </Link>
                  ) : null}
                </>
              )}
              {!!(o.stats?.steps?.length || o.stats?.notes?.length) && (
                <details className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
                  <summary>چه شد و کجا اجرا شد</summary>
                  {o.stats.steps?.map((s) => (
                    <div key={s.step}>
                      • {s.step} — {s.where}
                    </div>
                  ))}
                  {o.stats.notes?.map((n) => (
                    <div key={n}>• {n}</div>
                  ))}
                  {o.stats.render_seconds ? <div>زمانِ ساخت: {fa(o.stats.render_seconds)} ثانیه</div> : null}
                </details>
              )}
              <button className="mt-2 text-xs underline" style={{ color: "var(--bad)" }} onClick={() => void remove(o)}>
                حذفِ این نسخه
              </button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
