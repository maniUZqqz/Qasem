import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../../../../api/client";
import { Spinner, fa } from "../../../../components/ui";
import { Params, Preset, proApi } from "../api";
import type { PresetsPanelProps } from "./panelTypes";
import { Layer, ProState, nid } from "./types";
import "./panels.css";

type Recipe = { adjust: Record<string, number>; curve: Record<string, [number, number][]> };

/** شکلِ داده‌ای که در پریست (و کلیپ‌بوردِ کپی/چسباندن) نگه داشته می‌شود */
type PresetData = {
  adjust?: Record<string, number>;
  curve?: Record<string, [number, number][]>;
  kit_auto?: boolean;
  tools?: Record<string, Params>;
  layers?: unknown[];
  output?: unknown;
};

const CLIP_KEY = "nm.photo.clip";
const OVERLAY_TYPES = ["image", "text", "shape", "adjust", "group"];

// crop_format = قابِ شبکه‌ها / مربعِ فروشگاه (جای kit_square ِ قدیمی)؛ پنجرهٔ «سوژه» و جای دوربین (view) مالِ همین عکس‌اند و در پریست نمی‌مانند
const toolOk = (k: string) => k === "look" || k === "auto_tone" || k === "crop_format" || k.startsWith("kit_");
const pickTools = (tools: Record<string, Params>): Record<string, Params> =>
  Object.fromEntries(
    Object.entries(tools)
      .filter(([k]) => toolOk(k))
      .map(([k, v]) => [k, k === "crop_format" ? { ...v, window: [], view: [] } : v]),
  );

const isOverlay = (l: unknown): l is Layer =>
  typeof l === "object" && l !== null && OVERLAY_TYPES.includes(String((l as { type?: unknown }).type));

/** لایه‌های رویی (بدونِ عکس و روتوش، بدونِ ماسکِ نقاشی‌شده که فقط در همین پروژه معنا دارد) */
const overlayLayers = (layers: Layer[]): Layer[] =>
  layers.filter((l) => OVERLAY_TYPES.includes(l.type)).map((l) => (l.mask?.type === "paint" ? { ...l, mask: null } : l));

/** لایه‌های پریست ⇐ لایه‌های تازه با شناسهٔ نو */
const freshLayers = (ls: unknown[] | undefined): Layer[] => {
  const src = (ls ?? []).filter(isOverlay);
  const ids = new Map<string, string>(src.map((l) => [l.id, nid()]));
  return src.map((l) => {
    const copy = JSON.parse(JSON.stringify(l)) as Layer;
    const fresh = { ...copy, id: ids.get(l.id)!, mask: copy.mask?.type === "paint" ? null : copy.mask } as Layer;
    // گروه‌ها: parent به شناسهٔ تازهٔ گروه نگاشته می‌شود (گروهِ ناموجود ⇒ سطحِ بالا)
    if (copy.parent) {
      const np = ids.get(copy.parent);
      if (np) fresh.parent = np;
      else delete fresh.parent;
    }
    return fresh;
  });
};

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** کوچک‌نماها یکی‌یکی و با فاصله ساخته می‌شوند تا مرورگر/کارتِ گرافیک نفس بکشد */
function useThumbs(
  items: { key: string; recipe: Recipe }[],
  make: PresetsPanelProps["makeThumb"],
  version: number,
  size: number,
): Record<string, string> {
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const sig = items.map((i) => `${i.key}:${JSON.stringify(i.recipe).length}`).join("|");
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const makeRef = useRef(make);
  makeRef.current = make;
  useEffect(() => {
    let stop = false;
    let timer = 0;
    let i = 0;
    const list = itemsRef.current;
    const step = () => {
      if (stop || i >= list.length) return;
      const it = list[i++];
      const url = makeRef.current(it.recipe, size);
      if (url && !stop) setThumbs((t) => ({ ...t, [it.key]: url }));
      timer = window.setTimeout(step, 16);
    };
    timer = window.setTimeout(step, 0);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [version, sig, size]);
  return thumbs;
}

function Msg({ m }: { m: { tone: "ok" | "bad" | "warn"; text: string } | null }) {
  return m ? <p className={`pn-msg ${m.tone}`} role="status">{m.text}</p> : null;
}

export default function PresetsPanel(props: PresetsPanelProps) {
  const { storeId, state, hist, kit, assets, currentAssetId, nodeOn } = props;

  // ───────────────────────── فیلترهای کیت
  const kitLooks = kit.presets.filter((p) => p.kind === "look");
  const kitItems = [
    { key: "__none", recipe: { adjust: {}, curve: {} } as Recipe },
    ...kitLooks.map((p) => ({
      key: p.key,
      recipe: { adjust: p.recipe?.adjust ?? {}, curve: p.recipe?.curve ?? {} } as Recipe,
    })),
  ];
  const kitThumbs = useThumbs(kitItems, props.makeThumb, props.thumbVersion, 132);

  // ───────────────────────── پریست‌های شخصی
  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [withLayers, setWithLayers] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad" | "warn"; text: string } | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [editName, setEditName] = useState("");

  useEffect(() => {
    let stop = false;
    setPresets(null);
    setLoadErr(null);
    proApi
      .presets(storeId)
      .then((r) => !stop && setPresets(r))
      .catch((e) => !stop && setLoadErr(errorMessage(e)));
    return () => {
      stop = true;
    };
  }, [storeId]);

  const dataOf = (p: Preset): PresetData => (p.data ?? {}) as PresetData;
  const personalItems = (presets ?? []).map((p) => ({
    key: `p${p.id}:${p.updated_at}`,
    recipe: { adjust: dataOf(p).adjust ?? {}, curve: dataOf(p).curve ?? {} } as Recipe,
  }));
  const personalThumbs = useThumbs(personalItems, props.makeThumb, props.thumbVersion, 104);

  const currentData = (layers: boolean): Record<string, unknown> =>
    clone({
      adjust: state.adjust,
      curve: state.curve,
      kit_auto: state.kitAuto,
      tools: pickTools(state.tools),
      layers: layers ? overlayLayers(state.layers) : [],
      output: state.out,
    });

  const overlayCount = overlayLayers(state.layers).length;

  const save = async () => {
    const n = name.trim();
    if (!n) {
      setMsg({ tone: "warn", text: "برای پریست یک نام بنویسید." });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const p = await proApi.createPreset(storeId, n.slice(0, 80), currentData(withLayers));
      setPresets((list) => [p, ...(list ?? [])]);
      setName("");
      setMsg({ tone: "ok", text: `پریستِ «${p.name}» ذخیره شد.` });
    } catch (e) {
      setMsg({ tone: "bad", text: errorMessage(e) });
    } finally {
      setSaving(false);
    }
  };

  const applyData = (label: string, d: PresetData) =>
    hist.apply(label, (s): ProState => {
      const tools = { ...s.tools };
      for (const [k, v] of Object.entries(d.tools ?? {})) if (toolOk(k)) tools[k] = clone(v);
      return {
        ...s,
        adjust: { ...(d.adjust ?? {}) },
        curve: clone((d.curve ?? {}) as ProState["curve"]),
        kitAuto: !!d.kit_auto,
        tools,
        layers: [...s.layers, ...freshLayers(d.layers)],
      };
    });

  const applyPersonal = (p: Preset) => {
    applyData(`پریست: ${p.name}`, dataOf(p));
    setMsg({ tone: "ok", text: `«${p.name}» روی این عکس اعمال شد.` });
  };

  const startEdit = (p: Preset) => {
    setEditing(p.id);
    setEditName(p.name);
  };
  const commitEdit = async () => {
    const id = editing;
    setEditing(null);
    const n = editName.trim().slice(0, 80);
    const old = presets?.find((p) => p.id === id);
    if (id === null || !n || !old || n === old.name) return;
    try {
      const p = await proApi.patchPreset(storeId, id, { name: n });
      setPresets((list) => (list ?? []).map((x) => (x.id === id ? { ...x, ...p } : x)));
    } catch (e) {
      setMsg({ tone: "bad", text: errorMessage(e) });
    }
  };
  const remove = async (p: Preset) => {
    if (!window.confirm(`پریستِ «${p.name}» حذف شود؟`)) return;
    try {
      await proApi.removePreset(storeId, p.id);
      setPresets((list) => (list ?? []).filter((x) => x.id !== p.id));
      setBatchPreset((v) => (v === p.id ? "" : v));
    } catch (e) {
      setMsg({ tone: "bad", text: errorMessage(e) });
    }
  };

  // ───────────────────────── اعمال روی چند عکس
  const [sel, setSel] = useState<Set<number>>(() => new Set());
  const [batchPreset, setBatchPreset] = useState<number | "">("");
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchMsg, setBatchMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  useEffect(() => {
    if (batchPreset === "" && presets && presets.length) setBatchPreset(presets[0].id);
  }, [presets, batchPreset]);

  const toggleAsset = (id: number) =>
    setSel((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const runBatch = async () => {
    if (batchPreset === "" || sel.size === 0) return;
    setBatchBusy(true);
    setBatchMsg(null);
    try {
      const res = await proApi.applyPreset(storeId, batchPreset, [...sel]);
      const count = res.edits.length;
      setBatchMsg({ tone: "ok", text: `${fa(count)} نسخه ساخته شد؛ پیشرفتش را در «نسخه‌ها» ببینید.` });
      props.onBatch({ batch: res.batch, count });
    } catch (e) {
      setBatchMsg({ tone: "bad", text: errorMessage(e) });
    } finally {
      setBatchBusy(false);
    }
  };

  // ───────────────────────── کپی / چسباندنِ تنظیمات
  const [clipLayers, setClipLayers] = useState(false);
  const [clipMsg, setClipMsg] = useState<{ tone: "ok" | "bad" | "warn"; text: string } | null>(null);
  const copy = () => {
    try {
      window.localStorage.setItem(CLIP_KEY, JSON.stringify(currentData(clipLayers)));
      setClipMsg({ tone: "ok", text: clipLayers ? "تنظیمات و لایه‌ها کپی شد." : "تنظیمات کپی شد." });
    } catch {
      setClipMsg({ tone: "bad", text: "کپی ممکن نشد (مرورگر ذخیره‌سازی را نمی‌دهد)." });
    }
  };
  const paste = () => {
    let raw: string | null = null;
    try {
      raw = window.localStorage.getItem(CLIP_KEY);
    } catch {
      raw = null;
    }
    if (!raw) {
      setClipMsg({ tone: "warn", text: "چیزی برای چسباندن نیست؛ اول در عکسِ دیگر «کپی تنظیمات» را بزنید." });
      return;
    }
    try {
      const d = JSON.parse(raw) as PresetData;
      applyData("چسباندنِ تنظیمات", d);
      setClipMsg({ tone: "ok", text: "تنظیمات چسبانده شد." });
    } catch {
      setClipMsg({ tone: "bad", text: "دادهٔ کپی‌شده خراب است." });
    }
  };

  return (
    <div className="pn-root" data-testid="presets-panel">
      <div className="ws-card" data-testid="presets-kit">
        <div className="ws-card-title">فیلترهای حرفه‌ای (کیت) — پیش‌نمایشِ زنده</div>
        <div className="pn-grid">
          <button
            type="button" className="pn-tile" data-preset="__none" title="لغزنده‌ها و منحنی به حالتِ اولیه برمی‌گردد"
            onClick={() => hist.apply("بدونِ فیلتر", (s) => ({ ...s, adjust: {}, curve: {} }))}
          >
            {kitThumbs.__none ? <img src={kitThumbs.__none} alt="" /> : <span className="ph"><Spinner size={13} /></span>}
            <span className="t">بدونِ فیلتر</span>
          </button>
          {kitLooks.map((p) => (
            <button key={p.key} type="button" className="pn-tile" title={p.help} data-preset={p.key} onClick={() => props.applyKitPreset(p.key)}>
              {kitThumbs[p.key] ? <img src={kitThumbs[p.key]} alt="" /> : <span className="ph"><Spinner size={13} /></span>}
              <span className="t">{p.title}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="ws-card">
        <div className="ws-card-title">پریست‌های من</div>
        <div className="pn-pair" style={{ gridTemplateColumns: "minmax(0,1fr) auto", alignItems: "end" }}>
          <input
            className="u-input pn-num" style={{ textAlign: "start" }} placeholder="نامِ پریست" value={name} maxLength={80} aria-label="نامِ پریست" data-testid="preset-save-name"
            onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void save(); }}
          />
          <button type="button" className="pn-btn primary" disabled={saving} data-testid="preset-save" onClick={() => void save()}>
            {saving ? <Spinner size={13} /> : null} ذخیره
          </button>
        </div>
        <label className="pn-check">
          <input type="checkbox" checked={withLayers} onChange={(e) => setWithLayers(e.target.checked)} data-testid="preset-with-layers" />
          <span>همراه با لایه‌ها (لوگو، متن، واترمارک){overlayCount ? ` — ${fa(overlayCount)} لایه` : ""}</span>
        </label>
        <p className="pn-hint">تنظیمِ فعلیِ نور و رنگ، منحنی و فیلتر ذخیره می‌شود تا روی عکس‌های دیگر یا چند عکس با هم اعمال شود.</p>
        <Msg m={msg} />
        {presets === null && !loadErr && <div className="pn-muted" style={{ padding: 8 }}><Spinner size={14} /> در حالِ بارگذاری…</div>}
        {loadErr && <p className="pn-msg bad" role="alert">{loadErr}</p>}
        {presets && presets.length === 0 && <p className="pn-hint">هنوز پریستی نساخته‌اید.</p>}
        <div className="pn-presets">
          {(presets ?? []).map((p) => {
            const d = dataOf(p);
            const url = personalThumbs[`p${p.id}:${p.updated_at}`];
            const nl = (d.layers ?? []).length;
            return (
              <div key={p.id} className="pn-preset" data-testid="preset-row" data-preset-id={p.id}>
                <span className="pn-thumb">{url ? <img src={url} alt="" /> : <Spinner size={12} />}</span>
                {editing === p.id ? (
                  <input
                    className="u-input pn-rename" value={editName} autoFocus maxLength={80} aria-label="نامِ پریست" data-testid="preset-rename-input"
                    onChange={(e) => setEditName(e.target.value)} onBlur={() => void commitEdit()}
                    onKeyDown={(e) => { if (e.key === "Enter") void commitEdit(); else if (e.key === "Escape") setEditing(null); }}
                  />
                ) : (
                  <button type="button" className="nm" title="برای تغییر نام کلیک کنید" data-testid="preset-rename" onClick={() => startEdit(p)}>{p.name}</button>
                )}
                {nl > 0 && <span className="meta">{fa(nl)} لایه</span>}
                <button type="button" className="pn-btn sm primary" data-testid="preset-apply" onClick={() => applyPersonal(p)}>اعمال</button>
                <button type="button" className="pn-btn sm danger" data-testid="preset-delete" aria-label={`حذفِ پریستِ ${p.name}`} onClick={() => void remove(p)}>حذف</button>
              </div>
            );
          })}
        </div>
      </div>

      <div className="ws-card">
        <div className="ws-card-title">کپی و چسباندنِ تنظیمات بینِ عکس‌ها</div>
        <div className="pn-actions">
          <button type="button" className="pn-btn" data-testid="clip-copy" onClick={copy}>کپی تنظیمات</button>
          <button type="button" className="pn-btn" data-testid="clip-paste" onClick={paste}>چسباندن تنظیمات</button>
        </div>
        <label className="pn-check">
          <input type="checkbox" checked={clipLayers} onChange={(e) => setClipLayers(e.target.checked)} data-testid="clip-with-layers" />
          <span>کپی همراه با لایه‌ها</span>
        </label>
        <Msg m={clipMsg} />
      </div>

      <div className="ws-card">
        <div className="ws-card-title">اعمال روی چند عکس</div>
        <p className="pn-hint">عکس‌ها را تیک بزنید و یک پریست را روی همه اعمال کنید؛ برای هر عکس یک نسخهٔ تازه ساخته می‌شود.</p>
        {!nodeOn && <p className="pn-msg warn">سرورِ پردازش خاموش است؛ ساختِ سبک روی سرورِ سایت انجام می‌شود.</p>}
        <div className="pn-actions" style={{ marginBottom: 6 }}>
          <button type="button" className="pn-btn sm" onClick={() => setSel(new Set(assets.map((a) => a.id)))}>همه</button>
          <button type="button" className="pn-btn sm" onClick={() => setSel(new Set())}>هیچ‌کدام</button>
          <button type="button" className="pn-btn sm" onClick={() => setSel(new Set([currentAssetId]))}>فقط عکسِ فعلی</button>
          <span className="pn-count" style={{ alignSelf: "center" }}>{fa(sel.size)} عکس انتخاب شد</span>
        </div>
        <div className="pn-batch" data-testid="batch-grid" role="group" aria-label="عکس‌ها">
          {assets.map((a) => (
            <label key={a.id} className={sel.has(a.id) ? "is-on" : ""} title={a.title}>
              <input type="checkbox" checked={sel.has(a.id)} onChange={() => toggleAsset(a.id)} aria-label={a.title} data-asset-id={a.id} />
              <img src={a.thumb} alt="" />
            </label>
          ))}
        </div>
        <div className="pn-pair" style={{ gridTemplateColumns: "minmax(0,1fr) auto", marginTop: 8, alignItems: "center" }}>
          <select
            className="u-input pn-select-full" value={batchPreset} aria-label="پریست" disabled={!presets || presets.length === 0} data-testid="batch-preset"
            onChange={(e) => setBatchPreset(e.target.value ? Number(e.target.value) : "")}
          >
            {(!presets || presets.length === 0) && <option value="">پریستی نیست</option>}
            {(presets ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button type="button" className="pn-btn primary" data-testid="batch-apply" disabled={batchBusy || batchPreset === "" || sel.size === 0} onClick={() => void runBatch()}>
            {batchBusy ? <Spinner size={13} /> : null} اعمال
          </button>
        </div>
        <Msg m={batchMsg} />
      </div>
    </div>
  );
}
