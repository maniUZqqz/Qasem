import { Field, Select } from "../../../../components/ui";
import { label } from "../api";
import type { Catalog, SceneDoc, UploadResult } from "../types";
import { DraftInput, DraftNumber, DraftRange, Details, H3, Hr, SubCard } from "./fields";
import ParamInputs from "./ParamInputs";
import { byId } from "./model";

/**
 * تنظیماتِ صحنه، تکه‌تکه، تا هر تکه در بخشِ خودش در جریانِ راهنما بنشیند:
 *   SceneBasics          مدت/قاب/fps/عنوان                       ⇐ بخشِ ۱
 *   EnvironmentLighting  محیط و نور (+پارامترها در «تنظیمِ محیط»)   ⇐ بخشِ ۱
 *   ActorsEditor         بازیگرها (کاراکتر، جایگاه، ظاهر)           ⇐ بخشِ ۱
 *   ProductsEditor       محصول‌ها (نام، شکل، سطح، برچسب/رنگ/جنس)   ⇐ بخشِ ۱
 *   AudioSettings        زیرنویس، موسیقی، بلندی                   ⇐ بخشِ ۳
 * `SceneSettings` همهٔ این‌ها پشتِ سرِ هم است (همان چیدمانِ قدیمی).
 */

type Base = { cat: Catalog; doc: SceneDoc; change: (fn: (d: SceneDoc) => void) => void };
type WithUpload = Base & { upload: (file: File) => Promise<UploadResult | null> };

export function SceneBasics({ doc, change }: Base) {
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-2">
        <Field label="مدت (ث)">
          <DraftNumber value={doc.output.duration} step={0.1} min={3} max={60} onCommit={(v) => change((d) => void (d.output.duration = v ?? 10))} />
        </Field>
        <Field label="قاب">
          <Select value={doc.output.aspect} onChange={(e) => change((d) => void (d.output.aspect = e.target.value))}>
            <option value="9:16">۹:۱۶ عمودی</option>
            <option value="16:9">۱۶:۹ افقی</option>
            <option value="1:1">۱:۱ مربع</option>
            <option value="4:5">۴:۵ پست</option>
          </Select>
        </Field>
        <Field label="fps">
          <Select value={String(doc.output.fps)} onChange={(e) => change((d) => void (d.output.fps = Number(e.target.value)))}>
            <option value="24">24</option>
            <option value="25">25</option>
            <option value="30">30</option>
          </Select>
        </Field>
      </div>
      <Field label="عنوانِ ویدئو">
        <DraftInput
          value={doc.meta?.title || ""}
          onCommit={(v) =>
            change((d) => {
              d.meta = d.meta || {};
              d.meta.title = v;
            })
          }
        />
      </Field>
    </div>
  );
}

export function EnvironmentLighting({ cat, doc, change }: Base) {
  const env = byId(cat, "environment", doc.environment.id);
  const light = byId(cat, "lighting", doc.lighting.id);
  return (
    <div className="space-y-2">
      <Field label="محیط (صحنه)">
        <Select
          value={doc.environment.id}
          onChange={(e) =>
            change((d) => {
              d.environment = { id: e.target.value, params: {} };
              const en = byId(cat, "environment", e.target.value);
              if (en) {
                const mk = Object.keys(en.marks);
                const sf = Object.keys(en.surfaces);
                d.actors.forEach((a, i) => void (a.mark = mk[i] || mk[0]));
                d.products.forEach((p, i) => void (p.surface = sf[i] || sf[0]));
                if (en.default_lighting) d.lighting = { id: en.default_lighting, params: {} };
              }
            })
          }
        >
          {cat.environment.map((x) => (
            <option key={x.id} value={x.id}>
              {label(x)}
            </option>
          ))}
        </Select>
      </Field>
      <Details summary="تنظیمِ محیط (رنگِ پس‌زمینه، میز، تزئین)">
        <ParamInputs
          spec={env?.params}
          values={doc.environment.params || {}}
          onChange={(k, v) =>
            change((d) => {
              d.environment.params = d.environment.params || {};
              d.environment.params[k] = v;
            })
          }
        />
      </Details>
      <Field label="نورپردازی">
        <Select value={doc.lighting.id} onChange={(e) => change((d) => void (d.lighting = { id: e.target.value, params: {} }))}>
          {cat.lighting.map((x) => (
            <option key={x.id} value={x.id}>
              {label(x)}
            </option>
          ))}
        </Select>
      </Field>
      <Details summary="شدت و گرمیِ نور">
        <ParamInputs
          spec={light?.params}
          values={doc.lighting.params || {}}
          onChange={(k, v) =>
            change((d) => {
              d.lighting.params = d.lighting.params || {};
              d.lighting.params[k] = typeof v === "string" ? Number(v) : v;
            })
          }
        />
      </Details>
    </div>
  );
}

export function ActorsEditor({ cat, doc, change }: Base) {
  const env = byId(cat, "environment", doc.environment.id);
  const marks = Object.keys(env?.marks || {});
  return (
    <div className="space-y-2">
      {doc.actors.length === 0 && (
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          بازیگری نیست (فقط محصول با صدای راوی).
        </p>
      )}
      {doc.actors.map((a, i) => {
        const ch = byId(cat, "character", a.character);
        return (
          <SubCard key={a.id} title={`مجری: ${a.id}`}>
            <Field label="کاراکتر">
              <Select
                value={a.character}
                onChange={(e) =>
                  change((d) => {
                    d.actors[i].character = e.target.value;
                    d.actors[i].params = {};
                  })
                }
              >
                {cat.character.map((x) => (
                  <option key={x.id} value={x.id}>
                    {label(x)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="جایگاه در صحنه">
              <Select value={a.mark} onChange={(e) => change((d) => void (d.actors[i].mark = e.target.value))}>
                {marks.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </Select>
            </Field>
            <Details summary="ظاهر (لباس، مو)">
              <ParamInputs
                spec={ch?.params}
                values={a.params || {}}
                onChange={(k, v) =>
                  change((d) => {
                    d.actors[i].params = d.actors[i].params || {};
                    d.actors[i].params![k] = v;
                  })
                }
              />
            </Details>
          </SubCard>
        );
      })}
    </div>
  );
}

export function ProductsEditor({ cat, doc, change, upload }: WithUpload) {
  const env = byId(cat, "environment", doc.environment.id);
  const surfaces = Object.keys(env?.surfaces || {});
  return (
    <div className="space-y-2">
      {doc.products.map((p, i) => {
        const pa = byId(cat, "product", p.asset);
        return (
          <SubCard key={p.id} title={`محصول: ${p.id}`}>
            <Field label="نام">
              <DraftInput value={p.name || ""} onCommit={(v) => change((d) => void (d.products[i].name = v))} />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="شکل">
                <Select value={p.asset} onChange={(e) => change((d) => void (d.products[i].asset = e.target.value))}>
                  {cat.product.map((x) => (
                    <option key={x.id} value={x.id}>
                      {label(x)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="جا روی میز">
                <Select value={p.surface || ""} onChange={(e) => change((d) => void (d.products[i].surface = e.target.value))}>
                  {surfaces.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Details summary="برچسب، رنگ و جنس">
              <ParamInputs
                spec={pa?.params}
                values={p.params || {}}
                onChange={(k, v) =>
                  change((d) => {
                    d.products[i].params = d.products[i].params || {};
                    d.products[i].params![k] = v;
                  })
                }
                onFile={(k, f) =>
                  void upload(f).then((r) => {
                    if (!r) return;
                    change((d) => {
                      d.products[i].params = d.products[i].params || {};
                      d.products[i].params![k] = r.path;
                    });
                  })
                }
              />
            </Details>
          </SubCard>
        );
      })}
    </div>
  );
}

export function AudioSettings({ doc, change, upload }: Omit<WithUpload, "cat">) {
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
        <input type="checkbox" checked={doc.audio.subtitles !== false} onChange={(e) => change((d) => void (d.audio.subtitles = e.target.checked))} />
        زیرنویسِ خودکار از گفتار
      </label>
      <Field label="موسیقیِ پس‌زمینه (اختیاری)" hint={doc.audio.music ? `فعلی: ${String(doc.audio.music).split(/[\\/]/).pop()}` : "mp3 / wav / ogg / m4a"}>
        <input
          type="file"
          accept="audio/*"
          className="u-input"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            void upload(f).then((r) => {
              if (r) change((d) => void (d.audio.music = r.path));
            });
          }}
        />
      </Field>
      <Field label={`بلندیِ موسیقی: ${doc.audio.music_volume ?? 0.14}`} hint="زیرِ گفتار خودکار آرام می‌شود">
        <DraftRange value={doc.audio.music_volume ?? 0.14} min={0} max={0.5} step={0.01} onCommit={(v) => change((d) => void (d.audio.music_volume = v))} />
      </Field>
    </div>
  );
}

/** همهٔ تنظیمات پشتِ سرِ هم (چیدمانِ قدیمیِ ستونِ کناری). */
export default function SceneSettings(props: WithUpload) {
  return (
    <div className="space-y-2">
      <H3>تنظیماتِ صحنه</H3>
      <SceneBasics {...props} />
      <Hr />
      <H3>محیط و نور</H3>
      <EnvironmentLighting {...props} />
      <Hr />
      <H3>بازیگرها</H3>
      <ActorsEditor {...props} />
      <Hr />
      <H3>محصول‌ها</H3>
      <ProductsEditor {...props} />
      <Hr />
      <H3>صدا</H3>
      <AudioSettings {...props} />
    </div>
  );
}
