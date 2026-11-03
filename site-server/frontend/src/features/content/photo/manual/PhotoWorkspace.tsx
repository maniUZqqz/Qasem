import { useEffect, useMemo, useRef, useState } from "react";

import Icon from "../../../../components/Icon";
import Workspace from "../../../../components/Workspace";
import { Alert, Badge, Button, Select, Spinner, fa } from "../../../../components/ui";
import { useHistory } from "../../../../hooks/useHistory";
import type { Asset, Edit, Kit, Operation, Params, Tool } from "../api";
import { photoApi } from "../api";
import OperationForm from "../OperationForm";
import CurveEditor from "./CurveEditor";
import { Adjust, autoTone, imageDataFrom, process as processImage } from "./engine";
import {
  ASPECTS, EditState, FULL, NODE_TOOLS, Rect, SECTIONS, aspectRect, buildOperations, defaultState, hasCurve, isFullCrop,
  stateFromOperations, transformedSize,
} from "./model";
import { ParamSlider, SectionBody } from "./Sliders";
import Viewport, { ToolId, ZoomCmd } from "./Viewport";

type Props = {
  storeId: string;
  asset: Asset;
  assets: Asset[];
  onPick: (id: number) => void;
  tools: Record<string, Tool>;
  kit: Kit;
  nodeOn: boolean;
  nodeNames: string[];
  lastEdit: Edit | null;
  busy: boolean;
  onBuild: (ops: Operation[], recipe: string) => Promise<void>;
  onOpenVersions: () => void;
  /** ادامهٔ یک نسخهٔ قبلی: کارهایش به‌عنوانِ حالتِ آغازین */
  startFrom?: { tool: string; params: Params }[] | null;
};

type Tab = "edit" | "presets" | "history" | "export";

const TOOL_LIST: { id: ToolId; key: string; title: string; hint: string }[] = [
  { id: "hand", key: "H", title: "دست / زوم", hint: "بکشید و جابه‌جا کنید؛ چرخِ موس = زوم؛ Space = موقتاً دست" },
  { id: "crop", key: "C", title: "برش", hint: "قاب را بکشید یا یک نسبت انتخاب کنید" },
  { id: "straighten", key: "A", title: "صاف کردن و چرخش", hint: "افقِ کج را صاف کنید؛ چرخشِ ۹۰ درجه‌ای و قرینه" },
  { id: "heal", key: "J", title: "ترمیمِ لکه", hint: "روی لکه کلیک کنید (سرورِ پردازش)؛ کلیک روی دایره = برداشتن" },
  { id: "text", key: "T", title: "متن", hint: "متنِ فارسی روی عکس" },
  { id: "logo", key: "L", title: "لوگو", hint: "لوگوی فروشگاه یا عکسی از کتابخانه" },
  { id: "watermark", key: "W", title: "واترمارک", hint: "نامِ فروشگاه، گوشه‌ای یا تکرارشونده" },
  { id: "background", key: "B", title: "حذف/تعویضِ پس‌زمینه", hint: "کالا بی‌پس‌زمینه یا روی زمینهٔ سفید (سرورِ پردازش)" },
  { id: "square", key: "Q", title: "قابِ مربعِ فروشگاه", hint: "کالا وسطِ مربع با حاشیه (سرورِ پردازش)" },
  { id: "upscale", key: "U", title: "بزرگ‌نماییِ هوشمند", hint: "۲ یا ۴ برابر با Real-ESRGAN (سرورِ پردازش)" },
  { id: "denoise", key: "N", title: "نویزگیری", hint: "نویزِ روشنایی و رنگ (سرورِ پردازش)" },
  { id: "sharpen", key: "S", title: "شارپ", hint: "شارپِ لبه‌محور (سرورِ پردازش)" },
];

const TOOL_KEY: Partial<Record<ToolId, string>> = {
  text: "text", logo: "logo", watermark: "watermark", background: "kit_background", square: "kit_square", upscale: "kit_upscale",
};

const SERVER_LOOKS = [
  { value: "vivid", label: "پرجلوه", css: "saturate(1.35) contrast(1.1)" },
  { value: "warm", label: "گرم", css: "sepia(.25) saturate(1.1) brightness(1.04)" },
  { value: "cool", label: "سرد", css: "hue-rotate(185deg) saturate(.5) brightness(1.02)" },
  { value: "bw", label: "سیاه‌وسفید", css: "grayscale(1) contrast(1.12)" },
  { value: "sepia", label: "قهوه‌ای (قدیمی)", css: "sepia(.9) contrast(1.05)" },
  { value: "fade", label: "مات و ملایم", css: "saturate(.8) contrast(.85) brightness(1.1)" },
];

/** آیکون‌های ابزارها (ساده، هم‌ضخامت با آیکون‌های پنل) */
function ToolIcon({ id }: { id: ToolId }) {
  const d: Record<ToolId, string> = {
    hand: "M8 12V5.5a1.5 1.5 0 0 1 3 0V11m0-5.5a1.5 1.5 0 0 1 3 0V11m0-4a1.5 1.5 0 0 1 3 0v6.5a6 6 0 0 1-6 6h-.5a5 5 0 0 1-4-2L5 13.5a1.5 1.5 0 0 1 2.3-1.8L8 12.5",
    crop: "M7 3v14h14M3 7h14v14",
    straighten: "M4 15 20 9M5 20h14M12 4v3",
    heal: "M12 5a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm0 3.5v7m-3.5-3.5h7",
    text: "M5 6V4h14v2M12 4v16m-3 0h6",
    logo: "M4 5h16v14H4V5Zm0 10 4.5-4.5 4 4L16 11l4 4",
    watermark: "M12 3l8 3v6c0 4.5-3.2 8.3-8 9.5C7.2 20.3 4 16.5 4 12V6l8-3Z",
    background: "M5 5h8v8H5V5Zm6 6h8v8h-8v-8Z",
    square: "M5 5h14v14H5V5Zm4 4h6v6H9V9Z",
    upscale: "M14 4h6v6m0-6-7 7M10 20H4v-6m0 6 7-7",
    denoise: "M5 8h.01M9 5h.01M13 9h.01M17 6h.01M7 13h.01M11 15h.01M15 13h.01M19 11h.01M6 18h.01M12 19h.01M17 17h.01",
    sharpen: "M12 4 3 20h18L12 4Z",
  };
  return (
    <svg viewBox="0 0 24 24" width={20} height={20} fill="none" stroke="currentColor" strokeWidth={id === "denoise" ? 3 : 1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d={d[id]} />
    </svg>
  );
}

const defaultsOf = (t: Tool): Params => Object.fromEntries(t.params.map((p) => [p.key, p.default]));

function chip(on: boolean) {
  return `ws-chip ${on ? "is-on" : ""}`;
}

export default function PhotoWorkspace(props: Props) {
  const { asset, kit, tools, nodeOn } = props;
  const hist = useHistory<EditState>(props.startFrom ? stateFromOperations(props.startFrom) : defaultState());
  const state = hist.state;
  const [tool, setTool] = useState<ToolId>("hand");
  const [tab, setTab] = useState<Tab>("edit");
  const [open, setOpen] = useState<Record<string, boolean>>({ basic: true });
  const [compare, setCompare] = useState<"off" | "before" | "split">("off");
  const [zoomCmd, setZoomCmd] = useState<ZoomCmd>(null);
  const [zoomPct, setZoomPct] = useState(100);
  const [status, setStatus] = useState("");
  const [aspectKey, setAspectKey] = useState("free");
  const [flipAspect, setFlipAspect] = useState(false);
  const [spotR, setSpotR] = useState(0.02);
  const [precise, setPrecise] = useState(false);
  const [override, setOverride] = useState<{ url: string; w: number; h: number } | null>(null);
  const [previewInfo, setPreviewInfo] = useState<{ notes: string[]; skipped: string[] } | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [buildMsg, setBuildMsg] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const workRef = useRef<ImageData | null>(null);

  const src = asset.has_alpha ? asset.url : asset.preview;
  const [Wt, Ht] = transformedSize(asset.width, asset.height, state);

  // ───────────────────────── گام‌های ویرایش
  const liveAdjust = (key: string, v: number) => {
    const def = kit.params.find((p) => p.key === key)?.default ?? 0;
    hist.live((s) => {
      const a = { ...s.adjust };
      if (Math.abs(v - def) < 1e-9) delete a[key];
      else a[key] = v;
      return { ...s, adjust: a };
    });
  };
  const resetKeys = (keys: string[], label: string) =>
    hist.apply(label, (s) => {
      const a = { ...s.adjust };
      keys.forEach((k) => delete a[k]);
      return { ...s, adjust: a };
    });
  const setTools = (label: string, key: string, params: Params | null) =>
    hist.apply(label, (s) => {
      const t = { ...s.tools };
      if (params) t[key] = params;
      else delete t[key];
      return { ...s, tools: t };
    });
  const liveTools = (key: string, params: Params) => hist.live((s) => ({ ...s, tools: { ...s.tools, [key]: params } }));

  const setCrop = (r: Rect, commit: boolean) => {
    hist.live((s) => ({ ...s, crop: r }));
    if (commit) hist.end("برش");
  };

  const aspectRatio = useMemo(() => {
    const a = ASPECTS.find((x) => x.key === aspectKey);
    if (!a || a.ratio === null) return null;
    const r = a.ratio === 0 ? Wt / Ht : a.ratio;
    return flipAspect && a.ratio !== 0 && a.ratio !== 1 ? 1 / r : r;
  }, [aspectKey, flipAspect, Wt, Ht]);

  const chooseAspect = (key: string) => {
    setAspectKey(key);
    const a = ASPECTS.find((x) => x.key === key)!;
    if (a.ratio === null) return;
    const r0 = a.ratio === 0 ? Wt / Ht : a.ratio;
    const r = flipAspect && a.ratio !== 0 && a.ratio !== 1 ? 1 / r0 : r0;
    hist.apply(`برش ${a.title}`, (s) => ({ ...s, crop: aspectRect(r, Wt, Ht) }));
  };

  const addSpots = (spots: EditState["spots"]) => hist.apply(spots.length > state.spots.length ? "ترمیمِ لکه" : "برداشتنِ لکه", (s) => ({ ...s, spots }));

  // ───────────────────────── کلیدهای میان‌بر
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t instanceof HTMLInputElement && t.type !== "range" && t.type !== "checkbox") return;
      if (t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement) return;
      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) hist.redo();
        else hist.undo();
        return;
      }
      if (ctrl && e.key.toLowerCase() === "y") {
        e.preventDefault();
        hist.redo();
        return;
      }
      if (ctrl) return;
      if (e.key === "\\") {
        setCompare((c) => (c === "before" ? "off" : "before"));
        return;
      }
      if (e.key === "0") return setZoomCmd({ id: Date.now(), kind: "fit" });
      if (e.key === "1") return setZoomCmd({ id: Date.now(), kind: "100" });
      if (e.key === "+" || e.key === "=") return setZoomCmd({ id: Date.now(), kind: "in" });
      if (e.key === "-") return setZoomCmd({ id: Date.now(), kind: "out" });
      if (e.key === "[") return setSpotR((r) => Math.max(0.005, r - 0.005));
      if (e.key === "]") return setSpotR((r) => Math.min(0.1, r + 0.005));
      const hit = TOOL_LIST.find((x) => x.key.toLowerCase() === e.key.toLowerCase());
      if (hit) pickTool(hit.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hist.undo, hist.redo]);

  const pickTool = (id: ToolId) => {
    setTool(id);
    setPanelOpen(true);
    if (id === "denoise" || id === "sharpen") {
      setTab("edit");
      setOpen((o) => ({ ...o, detail: true }));
    }
  };

  // ───────────────────────── پیش‌نمایشِ دقیقِ سرور (متن، لوگو، برش، چرخش، فیلترِ ساده…)
  const serverOps = useMemo(
    () => buildOperations(state, {}).filter((o) => !NODE_TOOLS.has(o.tool) && o.tool !== "export"),
    [state],
  );
  const serverKey = JSON.stringify(serverOps);
  const needsGeometryView = tool === "crop" || tool === "straighten" || tool === "heal";
  useEffect(() => {
    if (!precise) {
      setOverride((o) => {
        if (o) URL.revokeObjectURL(o.url);
        return null;
      });
      setPreviewInfo(null);
      setPreviewErr(null);
      return;
    }
    let stop = false;
    const timer = window.setTimeout(async () => {
      setPreviewBusy(true);
      try {
        const { blob, info } = await photoApi.preview(props.storeId, asset.id, serverOps);
        if (stop) return;
        const url = URL.createObjectURL(blob);
        setOverride((o) => {
          if (o) URL.revokeObjectURL(o.url);
          return { url, w: info.size[0] || asset.width, h: info.size[1] || asset.height };
        });
        setPreviewInfo({ notes: info.notes, skipped: info.skipped });
        setPreviewErr(null);
      } catch (err) {
        if (!stop) setPreviewErr(err instanceof Error ? err.message : "پیش‌نمایشِ دقیق ساخته نشد.");
      } finally {
        if (!stop) setPreviewBusy(false);
      }
    }, 650);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [precise, serverKey, asset.id]);

  // ───────────────────────── کوچک‌نمایِ پریست‌ها (با همان موتورِ پیش‌نمایش)
  useEffect(() => {
    if (tab !== "presets" || Object.keys(thumbs).length) return;
    let stop = false;
    const img = new Image();
    img.onload = () => {
      if (stop) return;
      const small = imageDataFrom(img, img.naturalWidth, img.naturalHeight, 132);
      workRef.current = small;
      const out: Record<string, string> = {};
      const c = document.createElement("canvas");
      c.width = small.width;
      c.height = small.height;
      const ctx = c.getContext("2d")!;
      for (const pr of kit.presets) {
        if (!pr.recipe?.adjust) continue;
        ctx.putImageData(processImage(small, pr.recipe.adjust as Adjust, (pr.recipe.curve ?? {}) as never), 0, 0);
        out[pr.key] = c.toDataURL("image/jpeg", 0.8);
      }
      c.getContext("2d")!.putImageData(small, 0, 0);
      out.__original = c.toDataURL("image/jpeg", 0.8);
      setThumbs(out);
    };
    img.src = src;
    return () => {
      stop = true;
    };
  }, [tab, src, kit.presets, thumbs]);

  const applyPreset = (key: string) => {
    const pr = kit.presets.find((p) => p.key === key);
    if (!pr?.recipe) return;
    hist.apply(`فیلتر: ${pr.title}`, (s) => {
      const next: EditState = { ...s, adjust: { ...(pr.recipe!.adjust ?? {}) }, curve: (pr.recipe!.curve ?? {}) as never };
      const bg = pr.recipe!.background;
      if (bg?.remove && tools.kit_background) {
        next.tools = { ...s.tools, kit_background: { ...defaultsOf(tools.kit_background), bg: bg.color === "transparent" ? "transparent" : "white", shadow: bg.shadow ?? 0 } };
      }
      if (pr.recipe!.output?.square && tools.kit_square) {
        next.tools = { ...(next.tools ?? s.tools), kit_square: { ...defaultsOf(tools.kit_square), padding: Math.round((pr.recipe!.output.padding ?? 0.06) * 100) } };
      }
      return next;
    });
  };

  const quickAuto = () => {
    const b = workRef.current;
    const finish = (small: ImageData) => hist.apply("خودکار (مرورگر)", (s) => ({ ...s, adjust: { ...s.adjust, ...autoTone(small) } }));
    if (b) return finish(b);
    const img = new Image();
    img.onload = () => finish(imageDataFrom(img, img.naturalWidth, img.naturalHeight, 320));
    img.src = src;
  };

  // ───────────────────────── ساخت
  const nodeOps = buildOperations(state, {}).filter((o) => NODE_TOOLS.has(o.tool));
  async function build(quick: boolean) {
    setBuildMsg(null);
    try {
      await props.onBuild(buildOperations(state, { quick }), "manual");
      setBuildMsg(quick ? "ساختِ سریع (سرورِ سایت) شروع شد." : "ساخت شروع شد.");
      setTab("export");
    } catch (err) {
      setBuildMsg(err instanceof Error ? err.message : "ساخت شروع نشد.");
    }
  }

  const modified =
    Object.keys(state.adjust).length + (hasCurve(state.curve) ? 1 : 0) + state.spots.length + Object.keys(state.tools).length +
    (isFullCrop(state.crop) ? 0 : 1) + (state.turn || state.straighten || state.flipH || state.flipV ? 1 : 0) + (state.kitAuto ? 1 : 0);

  const activeKey = TOOL_KEY[tool];
  const activeTool = activeKey ? tools[activeKey] : undefined;
  const info = TOOL_LIST.find((x) => x.id === tool)!;

  const rotate = (delta: number) =>
    hist.apply("چرخش", (s) => ({ ...s, turn: ((((s.turn + delta) % 360) + 360) % 360) as EditState["turn"], crop: { ...FULL } }));

  // ───────────────────────── اجزای پنل
  const toolOptions = (
    <div className="ws-card" data-testid="tool-options">
      <div className="ws-card-title">
        {info.title}
        {NODE_TOOLS.has(activeKey ?? "") || tool === "heal" || tool === "denoise" || tool === "sharpen" ? (
          <Badge tone={nodeOn ? "info" : "warn"}>{nodeOn ? "سرورِ پردازش" : "سرورِ پردازش — خاموش"}</Badge>
        ) : null}
      </div>
      <p className="ws-hint">{info.hint}</p>

      {tool === "crop" && (
        <>
          <div className="flex flex-wrap gap-1">
            {ASPECTS.map((a) => (
              <button key={a.key} type="button" className={chip(aspectKey === a.key)} onClick={() => chooseAspect(a.key)} data-aspect={a.key}>
                {a.title}
              </button>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={flipAspect} onChange={(e) => setFlipAspect(e.target.checked)} />
              جابه‌جا کردنِ افقی/عمودی
            </label>
            <span dir="ltr" data-testid="crop-size">
              {fa(Math.round(state.crop.w * Wt))}×{fa(Math.round(state.crop.h * Ht))} px
            </span>
            <button type="button" className="ws-link" onClick={() => hist.apply("بازنشانیِ برش", (s) => ({ ...s, crop: { ...FULL } }))}>
              بازنشانیِ برش
            </button>
          </div>
        </>
      )}

      {tool === "straighten" && (
        <>
          <label className="ws-slider">
            <span className="ws-slider-head">
              <span>صاف کردنِ افق</span>
              <span className="ws-slider-val" dir="ltr">{fa(state.straighten)}°</span>
            </span>
            <input
              type="range" min={-15} max={15} step={0.1} value={state.straighten} aria-label="صاف کردنِ افق"
              onChange={(e) => hist.live((s) => ({ ...s, straighten: Number(e.target.value), crop: { ...FULL } }))}
              onPointerUp={() => hist.end("صاف کردن")} onKeyUp={() => hist.end("صاف کردن")}
              onDoubleClick={() => hist.apply("صاف کردن", (s) => ({ ...s, straighten: 0 }))}
            />
          </label>
          <div className="mt-2 flex flex-wrap gap-1">
            <button type="button" className="ws-chip" onClick={() => rotate(90)}>۹۰° پادساعتگرد</button>
            <button type="button" className="ws-chip" onClick={() => rotate(-90)}>۹۰° ساعتگرد</button>
            <button type="button" className={chip(state.flipH)} onClick={() => hist.apply("قرینهٔ افقی", (s) => ({ ...s, flipH: !s.flipH }))}>قرینهٔ افقی</button>
            <button type="button" className={chip(state.flipV)} onClick={() => hist.apply("قرینهٔ عمودی", (s) => ({ ...s, flipV: !s.flipV }))}>قرینهٔ عمودی</button>
          </div>
        </>
      )}

      {tool === "heal" && (
        <>
          <label className="ws-slider">
            <span className="ws-slider-head">
              <span>اندازهٔ قلم ( [ و ] )</span>
              <span className="ws-slider-val" dir="ltr">{fa(Math.round(spotR * 1000) / 10)}%</span>
            </span>
            <input type="range" min={0.005} max={0.1} step={0.005} value={spotR} onChange={(e) => setSpotR(Number(e.target.value))} aria-label="اندازهٔ قلم" />
          </label>
          <div className="mt-1 flex items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
            <span data-testid="spot-count">{fa(state.spots.length)} لکه</span>
            {state.spots.length > 0 && (
              <button type="button" className="ws-link" onClick={() => hist.apply("پاک کردنِ لکه‌ها", (s) => ({ ...s, spots: [] }))}>پاک کردنِ همه</button>
            )}
          </div>
          <p className="ws-hint">برای ترمیم، عکس بدونِ برش/چرخش نشان داده می‌شود (مختصاتِ لکه‌ها نسبت به عکسِ اصل است).</p>
        </>
      )}

      {activeTool && activeKey && (
        <>
          <label className="mb-2 flex items-center gap-2 text-sm" style={{ color: "var(--text)" }}>
            <input
              type="checkbox"
              checked={!!state.tools[activeKey]}
              onChange={(e) => setTools(e.target.checked ? activeTool.title : `برداشتنِ ${activeTool.title}`, activeKey, e.target.checked ? defaultsOf(activeTool) : null)}
              data-testid="tool-enable"
            />
            روی عکس اعمال شود
          </label>
          {state.tools[activeKey] && (
            <div onPointerUp={() => hist.end(activeTool.title)} onKeyUp={() => hist.end(activeTool.title)} onBlur={() => hist.end(activeTool.title)}>
              <OperationForm tool={activeTool} params={state.tools[activeKey]} kit={kit} spotImage={null} onChange={(p) => liveTools(activeKey, p)} />
            </div>
          )}
          {tool === "background" && (
            <div className="mt-2 flex flex-wrap gap-1">
              <button
                type="button" className="ws-chip"
                onClick={() => hist.apply("عکسِ فروشگاهی", (s) => {
                  const t: Record<string, Params> = { ...s.tools, kit_background: { ...defaultsOf(tools.kit_background), bg: "white", shadow: 25 } };
                  if (tools.kit_square) t.kit_square = defaultsOf(tools.kit_square);
                  return { ...s, tools: t };
                })}
              >
                عکسِ فروشگاهی (سفید + مربع)
              </button>
              <button
                type="button" className="ws-chip"
                onClick={() => hist.apply("کالا بی‌پس‌زمینه", (s) => {
                  const t: Record<string, Params> = { ...s.tools, kit_background: { ...defaultsOf(tools.kit_background), bg: "transparent", shadow: 0 } };
                  delete t.kit_square;
                  return { ...s, tools: t, out: { ...s.out, format: "png" } };
                })}
              >
                کالا بی‌پس‌زمینه (PNG)
              </button>
            </div>
          )}
        </>
      )}

      {(tool === "denoise" || tool === "sharpen") && (
        <div>
          {kit.params
            .filter((p) => (tool === "denoise" ? p.key.startsWith("noise") : p.key.startsWith("sharpen")))
            .map((p) => (
              <ParamSlider
                key={p.key} p={p} value={p.key in state.adjust ? state.adjust[p.key] : p.default}
                onLive={(v) => liveAdjust(p.key, v)} onEnd={() => hist.end(p.title)} onReset={() => resetKeys([p.key], `بازنشانیِ ${p.title}`)}
              />
            ))}
        </div>
      )}
    </div>
  );

  const editTab = (
    <div className="ws-sections" data-testid="edit-sections">
      <div className="mb-2 flex flex-wrap gap-1">
        <button type="button" className="ws-chip" onClick={quickAuto} title="از روی هیستوگرام نوردهی و کنتراست را می‌چیند (تقریبِ مرورگر)" data-testid="auto-browser">
          خودکار (مرورگر)
        </button>
        <button type="button" className={chip(state.kitAuto)} onClick={() => hist.apply("بهبودِ خودکارِ کیت", (s) => ({ ...s, kitAuto: !s.kitAuto }))} title="هنگامِ ساخت، کیت روی سرورِ پردازش خودش نور و رنگ را درست می‌کند">
          بهبودِ خودکارِ کیت {state.kitAuto ? "✓" : ""}
        </button>
        <button type="button" className={chip(!!state.tools.auto_tone)} onClick={() => setTools("نور و رنگِ خودکارِ سبک", "auto_tone", state.tools.auto_tone ? null : defaultsOf(tools.auto_tone))} title="نسخهٔ سبکِ سرورِ سایت؛ بی سرورِ پردازش">
          خودکارِ سبک (سرور) {state.tools.auto_tone ? "✓" : ""}
        </button>
      </div>
      {SECTIONS.map((sec) => (
        <div key={sec.key} className="ws-acc" data-section={sec.key}>
          <button type="button" className="ws-acc-head" onClick={() => setOpen((o) => ({ ...o, [sec.key]: !o[sec.key] }))} aria-expanded={!!open[sec.key]}>
            <span>{sec.title}</span>
            {sec.groups.some((g) => kit.params.some((p) => p.group === g && p.key in state.adjust)) && <i className="ws-dot" />}
            {sec.key === "curves" && hasCurve(state.curve) && <i className="ws-dot" />}
            <Icon name={open[sec.key] ? "up" : "down"} size={14} />
          </button>
          {open[sec.key] && (
            <>
              {sec.key === "curves" && (
                <div className="mb-3">
                  <CurveEditor value={state.curve} onChange={(c, commit) => { hist.live((s) => ({ ...s, curve: c })); if (commit) hist.end("منحنی"); }} />
                </div>
              )}
              <SectionBody kit={kit} section={sec} adjust={state.adjust} onLive={liveAdjust} onEnd={(l) => hist.end(l)} onReset={resetKeys} />
            </>
          )}
        </div>
      ))}
    </div>
  );

  const presetsTab = (
    <div data-testid="presets-tab">
      <div className="ws-group-title">فیلترهای حرفه‌ای (کیت) — پیش‌نمایشِ زنده</div>
      <div className="ws-thumbs">
        {kit.presets.filter((p) => p.kind === "look").map((p) => (
          <button key={p.key} type="button" className="ws-thumb" title={p.help} onClick={() => applyPreset(p.key)} data-preset={p.key}>
            {thumbs[p.key] ? <img src={thumbs[p.key]} alt="" /> : <span className="ws-thumb-ph"><Spinner size={14} /></span>}
            <span>{p.title}</span>
          </button>
        ))}
      </div>
      <div className="ws-group-title mt-4">فیلترهای ساده (سرورِ سایت — بی سرورِ پردازش)</div>
      <div className="ws-thumbs">
        <button type="button" className={`ws-thumb ${!state.tools.look ? "is-on" : ""}`} onClick={() => setTools("بی‌فیلتر", "look", null)}>
          {thumbs.__original ? <img src={thumbs.__original} alt="" /> : <span className="ws-thumb-ph" />}
          <span>بی‌فیلتر</span>
        </button>
        {SERVER_LOOKS.map((l) => (
          <button
            key={l.value} type="button" className={`ws-thumb ${state.tools.look?.style === l.value ? "is-on" : ""}`} data-look={l.value}
            onClick={() => setTools(`فیلتر ${l.label}`, "look", { ...defaultsOf(tools.look), style: l.value })}
          >
            {thumbs.__original ? <img src={thumbs.__original} alt="" style={{ filter: l.css }} /> : <span className="ws-thumb-ph" />}
            <span>{l.label}</span>
          </button>
        ))}
      </div>
      {state.tools.look && (
        <label className="ws-slider mt-2">
          <span className="ws-slider-head"><span>شدتِ فیلتر</span><span className="ws-slider-val" dir="ltr">{fa(Number(state.tools.look.strength))}</span></span>
          <input type="range" min={0} max={100} value={Number(state.tools.look.strength)} aria-label="شدتِ فیلتر"
            onChange={(e) => liveTools("look", { ...state.tools.look, strength: Number(e.target.value) })} onPointerUp={() => hist.end("شدتِ فیلتر")} />
        </label>
      )}
      <p className="ws-hint mt-2">فیلترهای ساده روی سرورِ سایت اعمال می‌شوند و با «پیش‌نمایشِ دقیق» دیده می‌شوند.</p>
    </div>
  );

  const historyTab = (
    <div data-testid="history-tab">
      <div className="mb-2 flex gap-2">
        <Button size="sm" variant="secondary" disabled={!hist.canUndo} onClick={hist.undo}>برگشت (Ctrl+Z)</Button>
        <Button size="sm" variant="secondary" disabled={!hist.canRedo} onClick={hist.redo}>جلو (Ctrl+Y)</Button>
      </div>
      <ol className="ws-history">
        {hist.entries.map((e, i) => (
          <li key={i}>
            <button type="button" className={`${i === hist.index ? "is-on" : ""} ${i > hist.index ? "is-future" : ""}`} onClick={() => hist.jump(i)}>
              <span>{fa(i)}</span> {e.label}
            </button>
          </li>
        ))}
      </ol>
    </div>
  );

  const exportTab = (
    <div data-testid="export-tab">
      <div className="ws-card">
        <div className="ws-card-title">تنظیماتِ خروجی</div>
        <label className="ws-field">
          <span>قالب</span>
          <Select value={state.out.format} onChange={(e) => hist.apply("قالبِ خروجی", (s) => ({ ...s, out: { ...s.out, format: e.target.value as EditState["out"]["format"] } }))}>
            <option value="jpeg">JPEG</option>
            <option value="png">PNG (شفاف)</option>
            <option value="webp">WebP</option>
          </Select>
        </label>
        <label className="ws-slider">
          <span className="ws-slider-head"><span>کیفیت</span><span className="ws-slider-val" dir="ltr">{fa(state.out.quality)}</span></span>
          <input type="range" min={40} max={100} value={state.out.quality} aria-label="کیفیت"
            onChange={(e) => hist.live((s) => ({ ...s, out: { ...s.out, quality: Number(e.target.value) } }))} onPointerUp={() => hist.end("کیفیت")} />
        </label>
        <label className="ws-field">
          <span>حداکثر حجم (کیلوبایت، ۰ = آزاد)</span>
          <input className="u-input" type="number" min={0} max={20000} step={10} value={state.out.max_kb}
            onChange={(e) => hist.apply("حداکثر حجم", (s) => ({ ...s, out: { ...s.out, max_kb: Math.max(0, Number(e.target.value) || 0) } }))} />
        </label>
        <div className="ws-field">
          <span>ضلعِ بلندتر</span>
          <div className="flex flex-wrap gap-1">
            {[0, 3000, 2400, 1600, 1080].map((n) => (
              <button key={n} type="button" className={chip(state.out.long_edge === n)} onClick={() => hist.apply("اندازهٔ خروجی", (s) => ({ ...s, out: { ...s.out, long_edge: n } }))}>
                {n ? `${fa(n)} px` : "اندازهٔ اصل"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {tools.crop_format && (
        <div className="ws-card">
          <div className="ws-card-title">قالبِ شبکه‌های اجتماعی</div>
          <label className="mb-2 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!state.tools.crop_format} onChange={(e) => setTools("قالبِ شبکه‌ها", "crop_format", e.target.checked ? defaultsOf(tools.crop_format) : null)} data-testid="social-enable" />
            برش/جا دادن در اندازهٔ دقیقِ شبکه (روی سرورِ سایت)
          </label>
          {state.tools.crop_format && (
            <div onPointerUp={() => hist.end("قالبِ شبکه‌ها")} onKeyUp={() => hist.end("قالبِ شبکه‌ها")}>
              <OperationForm tool={tools.crop_format} params={state.tools.crop_format} kit={kit} spotImage={null} onChange={(p) => liveTools("crop_format", p)} />
            </div>
          )}
        </div>
      )}

      <div className="ws-card" data-testid="build-card">
        <div className="ws-card-title">ساخت</div>
        {nodeOps.length > 0 && (
          <div className="mb-2">
            <Alert tone={nodeOn ? "info" : "warn"}>
              {nodeOn
                ? `کارهای کیت (${nodeOps.map((o) => tools[o.tool]?.title).join("، ")}) روی ${props.nodeNames.join("، ")} انجام می‌شود.`
                : `سرورِ پردازش الان خاموش است: ${fa(nodeOps.length)} کار (${nodeOps.map((o) => tools[o.tool]?.title).join("، ")}) در صف می‌ماند تا روشن شود. «ساختِ سریع» بی‌آن‌ها و فقط با سرورِ سایت، همین حالا نتیجه می‌دهد (لغزنده‌ها به رنگِ سادهٔ سرور تبدیل می‌شوند).`}
            </Alert>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void build(false)} disabled={props.busy} data-testid="build">
            {nodeOps.length && !nodeOn ? "ساخت (در صفِ سرورِ پردازش)" : "ساخت و ذخیره"}
          </Button>
          <Button variant="secondary" onClick={() => void build(true)} disabled={props.busy} data-testid="build-quick" title="فقط سرورِ سایت: برش، چرخش، متن، لوگو، فیلترِ ساده و رنگِ ساده">
            ساختِ سریع (سرورِ سایت)
          </Button>
        </div>
        {buildMsg && <p className="mt-2 text-sm" style={{ color: "var(--text-2)" }} data-testid="build-msg">{buildMsg}</p>}
        {props.lastEdit && (
          <div className="mt-3 text-sm" data-testid="last-edit">
            <div className="flex flex-wrap items-center gap-2">
              <span>نسخهٔ {fa(props.lastEdit.number)}:</span>
              <Badge tone={props.lastEdit.state === "READY" ? "ok" : props.lastEdit.state === "FAILED" ? "bad" : "info"}>{props.lastEdit.state_label}</Badge>
              {props.lastEdit.size && <span dir="ltr">{fa(props.lastEdit.size[0])}×{fa(props.lastEdit.size[1])}</span>}
            </div>
            {props.lastEdit.active && <p className="text-xs" style={{ color: "var(--warn)" }}>{props.lastEdit.message}</p>}
            {props.lastEdit.state === "FAILED" && <p className="text-xs" style={{ color: "var(--bad)" }}>{props.lastEdit.error}</p>}
            {props.lastEdit.state === "READY" && props.lastEdit.urls.preview && (
              <div className="mt-2">
                <img src={props.lastEdit.urls.preview} alt="نتیجه" className="ws-result" />
                <div className="mt-2 flex flex-wrap gap-2">
                  {props.lastEdit.urls.result && <a href={props.lastEdit.urls.result} download><Button size="sm" variant="secondary">دانلود</Button></a>}
                  <Button size="sm" variant="ghost" onClick={props.onOpenVersions}>قبل/بعد، ذخیره در محصول…</Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );

  const zoomBtn = (kind: "fit" | "100" | "in" | "out", label: string, title: string) => (
    <button type="button" className="ws-btn" title={title} onClick={() => setZoomCmd({ id: Date.now() + Math.random(), kind })} data-zoom={kind}>
      {label}
    </button>
  );

  return (
    <Workspace
      testId="photo-workspace"
      title="فضای کارِ دستیِ عکس"
      actions={
        <>
          <Badge tone={nodeOn ? "ok" : "warn"}>{nodeOn ? "سرورِ پردازش آنلاین" : "سرورِ پردازش خاموش"}</Badge>
          <span className="ws-muted">{fa(modified)} تغییر</span>
        </>
      }
    >
      <div className="pw-grid" dir="ltr">
        <div className="pw-top" dir="rtl">
          <Select value={asset.id} onChange={(e) => props.onPick(Number(e.target.value))} aria-label="عکس" className="!w-48">
            {props.assets.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
          </Select>
          <button type="button" className="ws-btn" disabled={!hist.canUndo} onClick={hist.undo} title="برگشت (Ctrl+Z)" data-testid="undo">↶ برگشت</button>
          <button type="button" className="ws-btn" disabled={!hist.canRedo} onClick={hist.redo} title="جلو (Ctrl+Y)" data-testid="redo">↷ جلو</button>
          <span className="ws-sep" />
          <button type="button" className={`ws-btn ${compare === "before" ? "is-on" : ""}`} onClick={() => setCompare((c) => (c === "before" ? "off" : "before"))} title="نمایشِ «قبل» ( \ )" data-testid="compare-before">قبل</button>
          <button type="button" className={`ws-btn ${compare === "split" ? "is-on" : ""}`} onClick={() => setCompare((c) => (c === "split" ? "off" : "split"))} title="قبل و بعد کنارِ هم" data-testid="compare-split">قبل | بعد</button>
          <span className="ws-sep" />
          {zoomBtn("out", "−", "کوچک‌نمایی")}
          <span className="ws-muted" dir="ltr" data-testid="zoom-pct">{fa(zoomPct)}%</span>
          {zoomBtn("in", "+", "بزرگ‌نمایی")}
          {zoomBtn("fit", "جا شدن", "جا شدن در قاب (0)")}
          {zoomBtn("100", "۱۰۰٪", "اندازهٔ واقعی (1)")}
          <span className="ws-sep" />
          <label className="ws-check" title="کارهای سرورِ سایت (متن، لوگو، برش، چرخش، فیلترِ ساده) را دقیق از سرور می‌گیرد؛ لغزنده‌های کیت همچنان تقریبی‌اند">
            <input type="checkbox" checked={precise} onChange={(e) => setPrecise(e.target.checked)} data-testid="precise" />
            پیش‌نمایشِ دقیقِ سرور
          </label>
          {previewBusy && <Spinner size={14} />}
          <span className="ws-spacer" />
          <button type="button" className="ws-btn primary" onClick={() => void build(false)} disabled={props.busy} data-testid="build-top">ساخت</button>
          <button type="button" className="ws-btn pw-panel-toggle" onClick={() => setPanelOpen((v) => !v)}>پنل</button>
        </div>

        <div className="pw-tools" dir="rtl" role="toolbar" aria-label="ابزارها" data-testid="toolbar">
          {TOOL_LIST.map((t) => (
            <button
              key={t.id} type="button" className={`ws-tool ${tool === t.id ? "is-on" : ""}`} onClick={() => pickTool(t.id)}
              title={`${t.title} (${t.key})`} aria-label={t.title} aria-pressed={tool === t.id} data-tool={t.id}
            >
              <ToolIcon id={t.id} />
            </button>
          ))}
        </div>

        <div className="pw-canvas">
          <Viewport
            src={src} origW={asset.width} origH={asset.height} state={state} tool={tool} compare={compare}
            override={precise && !needsGeometryView ? override : null}
            aspect={aspectRatio} spotR={spotR} zoomCmd={zoomCmd}
            onCrop={setCrop} onSpots={addSpots} onZoom={setZoomPct} onStatus={setStatus}
          />
          {precise && previewErr && <div className="pw-overlay-msg bad">{previewErr}</div>}
          {precise && previewInfo && previewInfo.skipped.length > 0 && (
            <div className="pw-overlay-msg">در پیش‌نمایشِ دقیق نیست (فقط روی سرورِ پردازش): {previewInfo.skipped.join("، ")}</div>
          )}
        </div>

        <div className={`pw-panel ${panelOpen ? "" : "is-closed"}`} dir="rtl" data-testid="right-panel">
          <div className="ws-tabs" role="tablist">
            {([["edit", "ویرایش"], ["presets", "فیلتر"], ["history", "تاریخچه"], ["export", "خروجی"]] as [Tab, string][]).map(([k, t]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "is-on" : ""} onClick={() => setTab(k)} data-tab={k}>{t}</button>
            ))}
          </div>
          <div className="pw-panel-scroll">
            {tool !== "hand" && toolOptions}
            {tab === "edit" && editTab}
            {tab === "presets" && presetsTab}
            {tab === "history" && historyTab}
            {tab === "export" && exportTab}
          </div>
        </div>

        <div className="pw-status" dir="rtl">
          <span>{fa(asset.width)}×{fa(asset.height)} ← {fa(Math.round(state.crop.w * Wt))}×{fa(Math.round(state.crop.h * Ht))}</span>
          <span>{status}</span>
          <span className="ws-spacer" />
          <span>میان‌برها: H دست · C برش · A صاف · J ترمیم · \ قبل · Ctrl+Z برگشت</span>
        </div>
      </div>
    </Workspace>
  );
}

export type { Props as PhotoWorkspaceProps };
