import { DragEvent, useState } from "react";

import { desc, fa, label, thumbUrl } from "../api";
import { CAT_FA } from "../editor/model";
import type { Asset, Catalog, LightType } from "../types";
import { LIGHT_FA } from "./model";
import { DND_TYPE, type DragPayload } from "./Viewport";

/**
 * کتابخانه: دارایی‌های موتور + بسته‌های بارگذاری‌شده. هر کارت را می‌شود به نما کشید (یا زد تا اضافه شود):
 * محیط، آدم، محصول، شیء، نور ⇐ نما · حرکت ⇐ ردیفِ یک آدم در خطِ زمان · نمای دوربین ⇐ ردیفِ «نماها».
 */

type Tab = "environment" | "character" | "product" | "prop" | "motion" | "shot" | "light";

const TABS: { id: Tab; fa: string; hint: string }[] = [
  { id: "environment", fa: "محیط", hint: "بزنید یا به نما بکشید تا محیطِ صحنه عوض شود" },
  { id: "character", fa: "آدم‌ها", hint: "به نما بکشید؛ هر جا رها کنید همان‌جا می‌ایستد" },
  { id: "product", fa: "محصول", hint: "محصولِ تبلیغ (برچسب، برداشتن با دست، نمای محصول)" },
  { id: "prop", fa: "اشیا", hint: "شیءِ تزئینیِ صحنه — هر اندازه و هر جا" },
  { id: "motion", fa: "حرکت‌ها", hint: "به ردیفِ یک آدم در خطِ زمان بکشید (یا بزنید: آدمِ انتخاب‌شده، زمانِ فعلی)" },
  { id: "shot", fa: "دوربین", hint: "نمای آماده را به ردیفِ «نماها» بکشید؛ یا دوربینِ آزاد بسازید و از نما کلید بزنید" },
  { id: "light", fa: "نور", hint: "نورِ تازه به نما بکشید؛ یا نورپردازیِ آمادهٔ کلِ صحنه را بزنید" },
];

const LIGHT_TYPES: LightType[] = ["point", "spot", "area", "sun"];
const LIGHT_ICON: Record<LightType, string> = { point: "💡", spot: "🔦", area: "⬜", sun: "☀️" };

function Card({
  asset,
  kind,
  payload,
  onPick,
  meta,
  icon,
  active,
}: {
  asset?: Asset;
  kind: string;
  payload: DragPayload;
  onPick: () => void;
  meta?: string;
  icon?: string;
  active?: boolean;
}) {
  const img = asset ? thumbUrl(kind, asset) : null;
  const onDragStart = (e: DragEvent<HTMLButtonElement>) => {
    e.dataTransfer.setData(DND_TYPE, JSON.stringify(payload));
    e.dataTransfer.setData("text/plain", payload.id);
    e.dataTransfer.effectAllowed = "copy";
  };
  return (
    <button
      type="button"
      className={`u3e-card ${active ? "on" : ""}`}
      draggable
      onDragStart={onDragStart}
      onClick={onPick}
      title={asset ? desc(asset) || label(asset) : meta}
      data-asset={`${payload.kind}:${payload.id}`}
    >
      <span className="u3e-thumb">{img ? <img src={img} alt="" loading="lazy" draggable={false} /> : <span className="ico">{icon || "◻︎"}</span>}</span>
      <span className="nm">{asset ? label(asset) : meta}</span>
      {asset && meta && <span className="mt">{meta}</span>}
      {asset?.pack && <span className="pk">بسته</span>}
    </button>
  );
}

export default function Library({
  cat,
  envId,
  lightingId,
  onAdd,
}: {
  cat: Catalog;
  envId: string;
  lightingId: string;
  /** همان کاری که رها کردن در نما/خطِ زمان می‌کند، بی‌جای مشخص */
  onAdd: (p: DragPayload) => void;
}) {
  const [tab, setTab] = useState<Tab>("environment");
  const [q, setQ] = useState("");
  const match = (a: Asset) => !q || label(a).includes(q) || a.id.includes(q.toLowerCase());
  const t = TABS.find((x) => x.id === tab)!;
  return (
    <div className="u3e-lib">
      <div className="u3e-chips">
        {TABS.map((x) => (
          <button key={x.id} type="button" className={`u3e-chip ${tab === x.id ? "on" : ""}`} onClick={() => setTab(x.id)}>
            {x.fa}
          </button>
        ))}
      </div>
      <input className="u-input u3e-search" placeholder="جست‌وجو…" value={q} onChange={(e) => setQ(e.target.value)} />
      <p className="u3e-hint">{t.hint}</p>
      <div className="u3e-grid">
        {tab === "environment" &&
          cat.environment.filter(match).map((a) => (
            <Card key={a.id} asset={a} kind="environment" payload={{ kind: "environment", id: a.id }} onPick={() => onAdd({ kind: "environment", id: a.id })} active={a.id === envId} />
          ))}
        {tab === "character" &&
          cat.character.filter(match).map((a) => (
            <Card key={a.id} asset={a} kind="character" payload={{ kind: "character", id: a.id }} onPick={() => onAdd({ kind: "character", id: a.id })} meta={a.gender === "male" ? "مرد" : a.gender === "female" ? "زن" : ""} />
          ))}
        {tab === "product" &&
          cat.product.filter(match).map((a) => (
            <Card key={a.id} asset={a} kind="product" payload={{ kind: "product", id: a.id }} onPick={() => onAdd({ kind: "product", id: a.id })} meta={a.dimensions ? `${fa(Math.round(a.dimensions[2] * 100))} سانت` : ""} />
          ))}
        {tab === "prop" &&
          cat.product.filter(match).map((a) => (
            <Card key={a.id} asset={a} kind="product" payload={{ kind: "prop", id: a.id }} onPick={() => onAdd({ kind: "prop", id: a.id })} meta="شیءِ صحنه" />
          ))}
        {tab === "motion" &&
          cat.motion.filter(match).map((a) => (
            <Card
              key={a.id}
              asset={a}
              kind="motion"
              payload={{ kind: "motion", id: a.id }}
              onPick={() => onAdd({ kind: "motion", id: a.id })}
              meta={`${CAT_FA[a.category] || a.category || ""} · ${fa(a.duration.default)}ث${a.source?.type === "clip" ? " · mocap" : ""}${a.layer ? " · لایه" : ""}`}
            />
          ))}
        {tab === "shot" && (
          <>
            <Card kind="camera" payload={{ kind: "camera", id: "new" }} onPick={() => onAdd({ kind: "camera", id: "new" })} meta="دوربینِ آزادِ تازه" icon="🎥" />
            {cat.shot.filter(match).map((a) => (
              <Card key={a.id} asset={a} kind="shot" payload={{ kind: "shot", id: a.id }} onPick={() => onAdd({ kind: "shot", id: a.id })} meta={`${a.subject === "product" ? "محصول" : "آدم"} · ${fa(a.framing.lens)}mm`} icon="🎬" />
            ))}
          </>
        )}
        {tab === "light" && (
          <>
            {LIGHT_TYPES.map((lt) => (
              <Card key={lt} kind="light" payload={{ kind: "light", id: lt }} onPick={() => onAdd({ kind: "light", id: lt })} meta={LIGHT_FA[lt]} icon={LIGHT_ICON[lt]} />
            ))}
            {cat.lighting.filter(match).map((a) => (
              <Card key={a.id} asset={a} kind="lighting" payload={{ kind: "lighting", id: a.id }} onPick={() => onAdd({ kind: "lighting", id: a.id })} meta="نورپردازیِ آماده" icon="✨" active={a.id === lightingId} />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
