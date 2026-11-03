import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Icon from "../../../../components/Icon";
import Workspace from "../../../../components/Workspace";
import { Alert, Badge, Button, Select, Spinner, fa } from "../../../../components/ui";
import { useHistory } from "../../../../hooks/useHistory";
import type { Asset, FontInfo, Operation, Params, Tool } from "../api";
import { photoApi, proApi } from "../api";
import CurveEditor from "../manual/CurveEditor";
import type { Adjust } from "../manual/engine";
import { ASPECTS, FULL, SECTIONS, aspectRect } from "../manual/model";
import { ParamSlider, SectionBody } from "../manual/Sliders";
import type { PhotoWorkspaceProps } from "../manual/PhotoWorkspace";
import OperationForm from "../OperationForm";
import FrameCard, { STORE_FRAME } from "./FrameCard";
import { cropFormatOpParams, effectiveCropFormat, makeFrameSpec } from "./frame";
import { photoGeoSizes } from "./geo";
import { neutralizeToTempTint } from "./gl/engine";
import GenFillPanel from "./GenFillPanel";
import Histogram, { HistData } from "./Histogram";
import LayerInspector from "./LayerInspector";
import LayersPanel from "./LayersPanel";
import { LiquifyStore } from "./liquify";
import type { Hist, MaskKind, ProActions } from "./panelTypes";
import { PenPath, penToSelection, penToShape } from "./pen";
import PresetsPanel from "./PresetsPanel";
import { MaskStore, Selection, ToolId, ToolOpts, ZoomCmd, defaultToolOpts } from "./session";
import Stage, { StageApi, frameInputOf } from "./Stage";
import {
  AdjustLayer, Layer, MaskSpec, ProState, Quad, buildProOperations, defaultProState, developKeys, makeAdjust, makeImage, makePathShape, makeRetouch,
  makeShape, makeText, nid, proStateFromOperations, serializeProject, withBase,
} from "./types";
import type { GenFillResult } from "../api";
import { makeGroup } from "./types";
import {
  canonical, cloneSubtree, clipTarget, descendantIds, effectivelyLocked, moveSibling as treeMoveSibling, moveTo, parentIdOf, removeWithDescendants,
  siblingsOf, ungroupLayers, wrapInGroup,
} from "./tree";
import "./pro.css";

type Props = PhotoWorkspaceProps & { storeLogo?: string | null };
type Tab = "edit" | "layers" | "presets" | "smart" | "history" | "export";

type ToolDef = { id: ToolId; key: string; title: string; hint: string; icon: string; dashed?: boolean; sep?: boolean };
const TOOLS: ToolDef[] = [
  { id: "move", key: "V", title: "جابه‌جایی و تبدیل", hint: "لایه را بکشید، با گوشه‌ها اندازه و با دایرهٔ بالا بچرخانید؛ کلیدهای جهت = جابه‌جایی دقیق", icon: "M12 3v18M3 12h18M12 3l-3 3m3-3 3 3M12 21l-3-3m3 3 3-3M3 12l3-3m-3 3 3 3M21 12l-3-3m3 3-3 3" },
  { id: "hand", key: "H", title: "دست / زوم", hint: "بکشید و جابه‌جا کنید؛ چرخِ موس = زوم؛ Space = موقتاً دست", icon: "M8 12V5.5a1.5 1.5 0 0 1 3 0V11m0-5.5a1.5 1.5 0 0 1 3 0V11m0-4a1.5 1.5 0 0 1 3 0v6.5a6 6 0 0 1-6 6h-.5a5 5 0 0 1-4-2L5 13.5a1.5 1.5 0 0 1 2.3-1.8L8 12.5" },
  { id: "crop", key: "C", title: "برش", hint: "قاب را بکشید یا یک نسبت انتخاب کنید", icon: "M7 3v14h14M3 7h14v14", sep: true },
  { id: "straighten", key: "A", title: "صاف کردن و چرخش", hint: "افقِ کج را صاف کنید؛ چرخشِ ۹۰ درجه‌ای و قرینه", icon: "M4 15 20 9M5 20h14M12 4v3" },
  { id: "persp", key: "Y", title: "پرسپکتیو (اصلاحِ اعوجاجِ ساختمان)", hint: "چهار گوشه را روی لبه‌های کج بکشید تا صاف شود", icon: "M6 5h12l3 14H3L6 5Z" },
  { id: "text", key: "T", title: "متن", hint: "روی عکس کلیک کنید و متن بنویسید (فارسی و انگلیسی)", icon: "M5 6V4h14v2M12 4v16m-3 0h6", sep: true },
  { id: "brush", key: "B", title: "قلمِ ماسک", hint: "روی ماسکِ لایهٔ فعال نقاشی کنید (سفید = دیده شود؛ X = پاک‌کن)", icon: "M4 20c3 0 5-1 5-4l9-9a2.1 2.1 0 0 0-3-3l-9 9c-3 0-4 2-4 5 0 1 1 2 2 2Z" },
  { id: "gradient", key: "G", title: "شیبِ موضعی (خطی/شعاعی)", hint: "بکشید تا یک لایهٔ تنظیم با ماسکِ شیب ساخته شود", icon: "M4 4h16v16H4V4Zm0 12L20 8" },
  { id: "clone", key: "S", title: "مهرِ کپی (Clone Stamp)", hint: "Alt + کلیک = منبع؛ بعد روی جای دیگر نقاشی کنید", icon: "M9 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm6 12a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM9 9l6 6", sep: true },
  { id: "heal", key: "J", title: "قلمِ ترمیم (Healing)", hint: "مثلِ مهرِ کپی ولی رنگ و روشنیِ اطراف را هم می‌گیرد", icon: "M12 5a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm0 3.5v7m-3.5-3.5h7" },
  { id: "spot", key: "K", title: "ترمیمِ لکه (کیت)", hint: "روی لکه کلیک کنید (سرورِ پردازش یا ساختِ سریع)؛ کلیک روی دایره = برداشتن", icon: "M12 3l2.5 5 5.5.8-4 3.9 1 5.5-5-2.6-5 2.6 1-5.5-4-3.9 5.5-.8L12 3Z" },
  { id: "marquee", key: "M", title: "انتخابِ مستطیلی", hint: "بکشید؛ Shift = افزودن، Alt = کم کردن", icon: "M4 4h16v16H4V4Z", dashed: true, sep: true },
  { id: "ellipse", key: "E", title: "انتخابِ بیضی", hint: "بکشید؛ Shift = افزودن، Alt = کم کردن", icon: "M12 5c5 0 9 3 9 7s-4 7-9 7-9-3-9-7 4-7 9-7Z", dashed: true },
  { id: "lasso", key: "L", title: "انتخابِ آزاد (کمند)", hint: "دورِ ناحیه بکشید", icon: "M5 13c0-4 3-8 8-8s7 2 7 5-3 5-8 5c-1 0-2 0-3-.3L7 20l1-3.5C6 16 5 14.5 5 13Z" },
  { id: "subject", key: "W", title: "انتخابِ سوژه", hint: "روی عکس کلیک کنید تا سوژه خودکار انتخاب شود (کیت یا الگوریتمِ سبک)", icon: "M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm-7 18a7 7 0 0 1 14 0" },
  { id: "wb", key: "I", title: "قطره‌چکانِ تعادلِ سفیدی", hint: "روی یک بخشِ خاکستریِ عکس کلیک کنید تا رنگ‌زدگی برطرف شود", icon: "M14 4l6 6-9 9H5v-6l9-9Zm-2 2 6 6", sep: true },
  { id: "redeye", key: "R", title: "قرمزیِ چشم", hint: "روی مردمکِ قرمز کلیک کنید؛ لکهٔ قرمز خودکار پیدا و اصلاح می‌شود (هر کلیک یک چشم در لایهٔ «قرمزیِ چشم»)", icon: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z", sep: true },
  { id: "pen", key: "P", title: "قلم (Pen)", hint: "کلیک = نقطه، کلیک و کشیدن = منحنیِ نرم، کلیک روی نقطهٔ اول = بستن؛ Enter = پایان، Esc = لغو، Backspace = حذفِ آخرین، Alt+کلیک روی نقطه = گوشه/نرم", icon: "M4 20l4-1 11-11-3-3L5 16l-1 4Zm10-14 3 3" },
  { id: "liquify", key: "Q", title: "مایع‌سازی (Liquify)", hint: "روی عکس بکشید تا بخش‌ها جابه‌جا شوند؛ باد کردن، جمع کردن و بازسازی هم دارد", icon: "M3 8c3-3 5 3 9 0s6-3 9 0M3 16c3-3 5 3 9 0s6-3 9 0" },
  { id: "genfill", key: "F", title: "پرکردنِ هوشمند", hint: "با قلم جایی را که باید عوض/حذف شود رنگ کنید (Alt = کم کردن)؛ بعد در پنل «اجرا» را بزنید", icon: "M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8L12 3Zm7 11 .9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14Z" },
];

const KIT_TOOLS: { key: string; title: string }[] = [
  { key: "kit_background", title: "حذف / تعویضِ پس‌زمینه" },
  { key: "kit_upscale", title: "بزرگ‌نماییِ هوشمند" },
  { key: "kit_denoise", title: "نویزگیری (کیت)" },
  { key: "kit_sharpen", title: "شارپِ حرفه‌ای (کیت)" },
];

const defaultsOf = (t: Tool): Params => Object.fromEntries(t.params.map((p) => [p.key, p.default]));
const chip = (on: boolean) => `ws-chip ${on ? "is-on" : ""}`;
const EXTRA_KEYS = ["auto_tone", "color", "look", "kit_preset"];
const EXACT_TOOLS = new Set(["kit_auto", "kit_adjust", "kit_heal", "kit_denoise", "kit_sharpen"]);

function ToolIcon({ t }: { t: ToolDef }) {
  return (
    <svg viewBox="0 0 24 24" width={20} height={20} fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={t.dashed ? "3 2.4" : undefined}>
      <path d={t.icon} />
    </svg>
  );
}

/**
 * پروژهٔ ذخیره‌شده ⇒ حالتِ ادیتور. `fv` همان‌طور که ذخیره شده می‌ماند (سرور پروژهٔ قدیمی را هنگامِ بازکردن کوچ می‌دهد و fv=2 می‌زند؛
 * اگر کوچ ممکن نبود fv نیست ⇒ legacy=true و ذخیرهٔ خودکار تا اولین ویرایشِ کاربر نگه داشته می‌شود).
 */
function normalizeLoaded(raw: Record<string, unknown>): { data: ProState; legacy: boolean } {
  const base = defaultProState();
  const data = { ...base, ...(raw as Partial<ProState>) } as ProState;
  const fv = Number((raw as { fv?: unknown }).fv);
  const legacy = !(fv >= 2);
  data.fv = legacy ? 1 : fv;
  data.tools = { ...(data.tools ?? {}) };
  // «قابِ مربعِ فروشگاه»ِ قدیمی (kit_square) ⇒ «قابِ شبکه‌ها: مربعِ دلخواه، جا دادن، سفید» (مثلِ کوچِ سرور)
  if (data.tools.kit_square) {
    const cf = data.tools.crop_format ? null : effectiveCropFormat({ kit_square: data.tools.kit_square });
    delete data.tools.kit_square;
    if (cf) data.tools.crop_format = cropFormatOpParams(cf);
  }
  data.layers = (Array.isArray(data.layers) ? data.layers : []).map((l) => {
    if (l.mask && l.mask.type === "paint") return { ...l, mask: { ...l.mask, rev: 0 } } as Layer;
    return l;
  });
  data.crop = { ...FULL, ...(data.crop ?? {}) };
  return { data: withBase(data), legacy };
}

const loadImg = (url: string) =>
  new Promise<HTMLImageElement>((resolve, reject) => {
    const i = new Image();
    i.crossOrigin = "anonymous";
    i.onload = () => resolve(i);
    i.onerror = () => reject(new Error("تصویر بارگذاری نشد."));
    i.src = url;
  });

export default function ProWorkspace(props: Props) {
  const { asset, kit, tools, nodeOn, storeId } = props;
  const initial = useMemo(() => (props.startFrom ? withBase(proStateFromOperations(props.startFrom)) : defaultProState()), []); // eslint-disable-line react-hooks/exhaustive-deps
  const hist = useHistory<ProState>(initial);
  const state = hist.state;
  const stateRef = useRef(state);
  stateRef.current = state;
  const H: Hist = hist;

  const masks = useMemo(() => new MaskStore(), []);
  const selection = useMemo(() => new Selection(), []);
  const [selVer, setSelVer] = useState(0);
  /** قلم (Pen): مسیرِ در حالِ ساخت؛ مایع‌سازی: نقشهٔ جابه‌جاییِ پروژه (فضای عکس) */
  const pen = useMemo(() => new PenPath(), []);
  const [, setPenVer] = useState(0);
  const bumpPen = useCallback(() => setPenVer((v) => v + 1), []);
  const liquify = useMemo(() => {
    const s = new LiquifyStore();
    s.init(asset.width, asset.height);
    return s;
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  /** پرکردنِ هوشمند: پنل باز است؟ و شناسهٔ کارِ در جریان (برای ادامه پس از بازکردنِ دوبارهٔ صفحه) */
  const [gfOpen, setGfOpen] = useState(false);
  const [gfBusy, setGfBusy] = useState(false);
  const gfKey = `nm.photo.genfill.${storeId}.${asset.id}`;
  const [gfResume] = useState<string | null>(() => {
    try {
      return window.localStorage.getItem(gfKey);
    } catch {
      return null;
    }
  });
  const [stage, setStage] = useState<StageApi | null>(null);
  const stageRef = useRef<StageApi | null>(null);
  stageRef.current = stage;

  const [tool, setToolState] = useState<ToolId>("move");
  const [opts, setOptsState] = useState<ToolOpts>(defaultToolOpts());
  const [tab, setTab] = useState<Tab>("layers");
  const [open, setOpen] = useState<Record<string, boolean>>({ basic: true });
  const [activeId, setActiveId] = useState<string | null>("base");
  const [compare, setCompare] = useState<"off" | "before" | "split">("off");
  const [zoomCmd, setZoomCmd] = useState<ZoomCmd>(null);
  const [zoomPct, setZoomPct] = useState(100);
  const [status, setStatus] = useState("");
  const [aspectKey, setAspectKey] = useState("free");
  const [flipAspect, setFlipAspect] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [hdata, setHdata] = useState<HistData | null>(null);
  const [buildMsg, setBuildMsg] = useState<string | null>(null);
  const [fonts, setFonts] = useState<FontInfo[]>([{ key: "vazirmatn", title: "وزیرمتن", family: "Vazirmatn", weights: [300, 400, 500, 600, 700, 800], rtl: true }]);
  const [extraAssets, setExtraAssets] = useState<Asset[]>([]);
  const [saveMsg, setSaveMsg] = useState("");
  const [projectReady, setProjectReady] = useState(false);
  const [notice, setNotice] = useState<{ tone: "warn" | "bad" | "info"; text: string } | null>(null);
  const [busyOp, setBusyOp] = useState("");
  const [thumbVersion, setThumbVersion] = useState(0);
  const projRef = useRef<{ id: number; rev: number } | null>(null);
  const saving = useRef(false);
  /** پروژهٔ قدیمیِ کوچ‌نشده: تا کاربر چیزی را عوض نکرده ذخیرهٔ خودکار نکن (ذخیره fv=2 می‌زند) */
  const holdSave = useRef(false);

  const allAssets = useMemo(() => [...props.assets, ...extraAssets.filter((e) => !props.assets.some((a) => a.id === e.id))], [props.assets, extraAssets]);
  const src = asset.has_alpha ? asset.url : asset.preview;
  const setOpts = useCallback((p: Partial<ToolOpts>) => setOptsState((o) => ({ ...o, ...p })), []);
  const setTool = useCallback((t: ToolId) => {
    setToolState(t);
    setPanelOpen(true);
  }, []);

  // ───────────────────────── پروژه: بازکردن، ذخیرهٔ خودکار
  useEffect(() => {
    let stop = false;
    (async () => {
      try {
        let proj = null as Awaited<ReturnType<typeof proApi.project>> | null;
        if (!props.startFrom) {
          const list = await proApi.projects(storeId, asset.id);
          if (list.length) proj = await proApi.project(storeId, list[0].id);
        }
        if (stop) return;
        if (proj && proj.data && Array.isArray((proj.data as { layers?: unknown }).layers)) {
          const { data, legacy } = normalizeLoaded(proj.data);
          holdSave.current = legacy;
          const ids = data.layers.flatMap((l) => (l.mask && l.mask.type === "paint" ? [l.mask.id] : []));
          await Promise.all(ids.map((id) => (proj!.masks[id] ? masks.loadUrl(id, proj!.masks[id]) : Promise.resolve(false))));
          // نقشهٔ مایع‌سازی (liquify.bin): اگر پروژه نشانش را دارد ولی فایل نیامد/خراب بود، نشان را بردار تا حالت و نقشه یکی بمانند
          liquify.onServer = !!proj.liquify;
          if (data.liquify) {
            let ok = false;
            if (proj.liquify) {
              try {
                ok = liquify.load(await proApi.getLiquify(storeId, proj.id), Number(data.liquify.rev) || proj.liquify.rev || 1);
              } catch {
                ok = false;
              }
            }
            if (!ok) data.liquify = null;
          }
          if (stop) return;
          hist.reset(data);
          projRef.current = { id: proj.id, rev: proj.rev };
          setSaveMsg("پروژهٔ ذخیره‌شده باز شد");
          const mig = (proj as { migration?: { migrated?: boolean; trivial?: boolean; notes?: string[]; error?: string } }).migration;
          if (mig?.error || legacy) {
            setNotice({ tone: "warn", text: "این پروژه با ویرایشگرِ قدیمی ساخته شده و تبدیلِ خودکارش به «قاب‌اول» ممکن نبود؛ جای لایه‌ها ممکن است جابه‌جا دیده شود. تا چیزی را عوض نکنید ذخیره نمی‌شود." });
          } else if (mig?.migrated && !mig.trivial) {
            setNotice({ tone: "info", text: `پروژه به مدلِ «قاب‌اول» (لایه‌ها نسبت به قابِ نهایی) تبدیل شد${mig.notes?.length ? ": " + mig.notes.join("؛ ") : ""}` });
          }
        } else {
          const created = await proApi.createProject(storeId, asset.id, serializeProject(stateRef.current) as unknown as Record<string, unknown>, asset.title);
          projRef.current = { id: created.id, rev: created.rev };
        }
      } catch {
        setNotice({ tone: "warn", text: "ذخیرهٔ خودکارِ پروژه در دسترس نیست؛ کارتان همچنان کار می‌کند ولی ذخیره نمی‌شود." });
      } finally {
        if (!stop) setProjectReady(true);
      }
    })();
    return () => {
      stop = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset.id]);

  const saveProject = useCallback(async (): Promise<boolean> => {
    const pr = projRef.current;
    if (!pr || saving.current) return !!pr;
    saving.current = true;
    setSaveMsg("در حال ذخیره…");
    try {
      const layers = stateRef.current.layers;
      for (const id of [...masks.dirty]) {
        const used = layers.some((l) => l.mask?.type === "paint" && l.mask.id === id);
        if (!used) {
          masks.dirty.delete(id);
          continue;
        }
        const b = await masks.toBlob(id);
        if (b) {
          await proApi.putMask(storeId, pr.id, id, b);
          masks.dirty.delete(id);
        }
      }
      // نقشهٔ مایع‌سازی: با ماسک‌ها هم‌زمان ذخیره می‌شود (حالت نشان دارد ⇒ بنویس؛ نشان ندارد و روی سرور فایل هست ⇒ بردار)
      if (stateRef.current.liquify) {
        if (liquify.dirty || !liquify.onServer) {
          const v = liquify.ver;
          await proApi.putLiquify(storeId, pr.id, liquify.encode());
          liquify.onServer = true;
          if (liquify.ver === v) liquify.dirty = false;
        }
      } else if (liquify.onServer) {
        await proApi.deleteLiquify(storeId, pr.id);
        liquify.onServer = false;
        liquify.dirty = false;
      }
      const data = serializeProject(stateRef.current) as unknown as Record<string, unknown>;
      try {
        const res = await proApi.saveProject(storeId, pr.id, data, pr.rev);
        pr.rev = res.rev;
      } catch (e) {
        const resp = (e as { response?: { status?: number; data?: { project?: { rev: number } } } }).response;
        if (resp?.status === 409 && resp.data?.project) {
          const res = await proApi.saveProject(storeId, pr.id, data);
          pr.rev = res.rev;
        } else throw e;
      }
      setSaveMsg(`ذخیره شد ${new Date().toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" })}`);
      return true;
    } catch {
      setSaveMsg("ذخیره نشد");
      return false;
    } finally {
      saving.current = false;
    }
  }, [masks, storeId, liquify]);

  useEffect(() => {
    if (!projectReady || !projRef.current) return;
    if (holdSave.current && !hist.canUndo) return;
    holdSave.current = false;
    const t = window.setTimeout(() => void saveProject(), 1500);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, projectReady, saveProject]);

  // برگشت/جلو ⇒ ماسک‌های نقاشی‌شده را به نسخهٔ همان گام برگردان
  useEffect(() => {
    let changed = false;
    for (const l of state.layers) {
      if (l.mask?.type === "paint" && masks.has(l.mask.id)) {
        const want = l.mask.rev ?? 0;
        if ((masks.revs.get(l.mask.id) ?? 0) !== want && masks.restore(l.mask.id, want)) {
          masks.dirty.add(l.mask.id);
          changed = true;
        }
      }
    }
    if (changed) stage?.redraw();
  }, [state.layers, masks, stage]);

  // برگشت/جلو ⇒ نقشهٔ مایع‌سازی را به نسخهٔ همان گام برگردان (state.liquify.rev؛ نبودنش = نقشهٔ صفر)
  useEffect(() => {
    const want = state.liquify?.rev ?? 0;
    if (liquify.rev !== want && liquify.restore(want)) stage?.redraw();
  }, [state.liquify, liquify, stage]);

  useEffect(() => {
    proApi.fonts(storeId).then(setFonts).catch(() => undefined);
  }, [storeId]);

  // ───────────────────────── پیش‌نمایشِ دقیق از سرورِ پردازش (کیت)
  const [exactImg, setExactImg] = useState<HTMLImageElement | null>(null);
  const [exactStatus, setExactStatus] = useState<"off" | "offline" | "pending" | "ready" | "error">("off");
  const exactJob = useRef<string | null>(null);
  const exactToken = useRef(0);
  const devKey = developKeys(state);
  useEffect(() => {
    exactToken.current++;
    const token = exactToken.current;
    setExactImg(null);
    const ops = buildProOperations(stateRef.current, { quick: false }).filter((o) => EXACT_TOOLS.has(o.tool));
    if (exactJob.current) {
      void proApi.exactCancel(storeId, exactJob.current);
      exactJob.current = null;
    }
    if (!ops.length) {
      setExactStatus("off");
      return;
    }
    setExactStatus(nodeOn ? "pending" : "offline");
    if (!nodeOn) return;
    const timer = window.setTimeout(async () => {
      try {
        const start = await proApi.exact(storeId, asset.id, ops.map((o) => ({ tool: o.tool, params: o.params })), 1280);
        if (token !== exactToken.current) {
          if (start.job) void proApi.exactCancel(storeId, start.job);
          return;
        }
        if (!start.online || start.state === "OFFLINE") return setExactStatus("offline");
        if (start.state === "NOOP" || !start.job) return setExactStatus("off");
        exactJob.current = start.job;
        for (let i = 0; i < 200; i++) {
          const st = await proApi.exactStatus(storeId, start.job);
          if (token !== exactToken.current) return;
          if (st.state === "COMPLETED" && st.url) {
            const img = await loadImg(st.url);
            if (token !== exactToken.current) return;
            exactJob.current = null;
            setExactImg(img);
            setExactStatus("ready");
            return;
          }
          if (st.state === "FAILED" || st.state === "CANCELLED") {
            exactJob.current = null;
            return setExactStatus("error");
          }
          await new Promise((r) => setTimeout(r, 1200));
        }
        setExactStatus("error");
      } catch {
        if (token === exactToken.current) setExactStatus("error");
      }
    }, 1000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [devKey, nodeOn, asset.id]);

  // ───────────────────────── لغزنده‌ها
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

  // اندازهٔ عکس پس از پرسپکتیو/چرخش/صاف‌کردن (برای نسبتِ برش) و قابِ نهایی (اندازهٔ بوم) — محاسبهٔ خالص، مستقل از نما
  const { Wt, Ht } = useMemo(() => photoGeoSizes(asset.width, asset.height, state), [asset.width, asset.height, state.turn, state.straighten, state.persp]); // eslint-disable-line react-hooks/exhaustive-deps
  const frameSpec = useMemo(
    () => makeFrameSpec(asset.width, asset.height, frameInputOf(state)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [asset.width, asset.height, state.turn, state.straighten, state.flipH, state.flipV, state.crop, state.persp, state.tools],
  );
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
  const rotate = (delta: number) =>
    hist.apply("چرخش", (s) => ({ ...s, turn: ((((s.turn + delta) % 360) + 360) % 360) as ProState["turn"], crop: { ...FULL } }));

  // قلابِ آزمونِ مرورگر (فقط خواندنی/اعمالِ حالت؛ برای کاربر بی‌اثر است)
  useEffect(() => {
    (window as unknown as { __photoProCtl?: unknown }).__photoProCtl = {
      apply: (p: Partial<ProState>) => hist.apply("آزمون", (s) => ({ ...s, ...p })),
      state: () => stateRef.current,
      tool: (t: ToolId) => setTool(t),
      active: (id: string | null) => setActiveId(id),
      opts: (o: Partial<ToolOpts>) => setOpts(o),
      fromOps: (ops: { tool: string; params: Params }[]) => proStateFromOperations(ops),
      buildOps: (quick: boolean) => buildProOperations(stateRef.current, { quick, projectId: 0, window: stageRef.current?.smartWindow(stateRef.current) ?? null }),
      /** بومِ نهایی: اندازهٔ واقعی (Wf×Hf) و کاری (Wc×Hc)، پنجرهٔ سوژه */
      canvasSize: () => {
        const e = stageRef.current?.engine;
        const f = stageRef.current?.frame();
        return e && f ? { Wf: f.Wf, Hf: f.Hf, Wc: e.Wc, Hc: e.Hc, trivial: f.trivial, smartPending: f.smartPending } : null;
      },
      frame: () => stageRef.current?.frame() ?? null,
      smartWindow: () => stageRef.current?.smartWindow(stateRef.current) ?? null,
      /** انتخابِ فعلی (فضای بومِ نهایی) به‌صورتِ data URL — برای آزمون */
      selectionInfo: () => ({ active: selection.active, w: selection.w, h: selection.h, url: selection.canvas ? selection.canvas.toDataURL("image/png") : null }),
      /** قلم و مایع‌سازی (آزمون) */
      penInfo: () => ({ pts: pen.pts, closed: pen.closed, done: pen.done }),
      liqInfo: () => {
        let m = 0;
        for (let i = 0; i < liquify.field.length; i++) m = Math.max(m, Math.abs(liquify.field[i]));
        return { rev: liquify.rev, ver: liquify.ver, active: liquify.active, dirty: liquify.dirty, onServer: liquify.onServer, gw: liquify.gw, gh: liquify.gh, maxAbs: m };
      },
      liqBytes: () => Array.from(liquify.encode()),
      /** آزمون: میدانِ مایع‌سازی را از بایت‌های LQF1 بخوان و ثبت کن */
      liqSet: (bytes: number[], label = "مایع‌سازی") => {
        const tmp = new LiquifyStore();
        tmp.init(asset.width, asset.height);
        if (!tmp.load(new Uint8Array(bytes).buffer, 1) || tmp.gw !== liquify.gw || tmp.gh !== liquify.gh) return false;
        liquify.field.set(tmp.field);
        liquify.touch();
        const rev = liquify.commit();
        hist.apply(label, (s) => ({ ...s, liquify: { rev } }));
        return true;
      },
    };
  });

  // ───────────────────────── لایه‌ها
  const patch = (id: string, p: Partial<Layer>, label: string) =>
    hist.apply(label, (s) => ({ ...s, layers: s.layers.map((l) => (l.id === id ? ({ ...l, ...p } as Layer) : l)) }));
  const addLayer = (l: Layer, label: string, after?: string) => {
    hist.apply(label, (s) => {
      if (!after) return { ...s, layers: [...s.layers, l] };
      const i = s.layers.findIndex((x) => x.id === after);
      const arr = [...s.layers];
      arr.splice(i + 1, 0, l);
      return { ...s, layers: arr };
    });
    setActiveId(l.id);
  };
  const activeLayer = state.layers.find((l) => l.id === activeId) ?? null;

  const imgUrl = (id: number) => {
    const a = allAssets.find((x) => x.id === id);
    return a ? (a.has_alpha ? a.url : a.preview || a.url) : null;
  };

  const actions: ProActions = {
    addText: () => {
      const l = makeText(0.5, 0.5);
      addLayer(l, "متن");
      setTool("move");
      setTab("layers");
      window.setTimeout(() => actions.focusText(), 80);
    },
    addShape: (shape) => {
      addLayer(makeShape(shape), shape === "rect" ? "مستطیل" : shape === "ellipse" ? "بیضی" : "خط");
      setTool("move");
    },
    addImageFromAsset: (aid) => {
      const a = allAssets.find((x) => x.id === aid);
      if (!a) return;
      const l = makeImage({ kind: "asset", asset: aid }, a.title);
      l.w = 0.45;
      addLayer(l, "تصویر");
      setTool("move");
    },
    addLogo: () => {
      const l = makeImage({ kind: "logo" }, "لوگو");
      l.w = 0.18;
      l.cx = 0.86;
      l.cy = 0.9;
      addLayer(l, "لوگو");
      setTool("move");
    },
    uploadImage: async (file) => {
      setBusyOp("آپلود تصویر…");
      try {
        const res = await photoApi.upload(storeId, [file]);
        const a = res.assets[0];
        if (!a) throw new Error(res.errors[0] ?? "آپلود نشد.");
        setExtraAssets((e) => [...e, a]);
        const l = makeImage({ kind: "asset", asset: a.id }, a.title);
        l.w = 0.45;
        addLayer(l, "تصویر");
        setTool("move");
      } catch (e) {
        setNotice({ tone: "bad", text: e instanceof Error ? e.message : "آپلود نشد." });
      } finally {
        setBusyOp("");
      }
    },
    addAdjust: () => {
      addLayer(makeAdjust("لایهٔ تنظیم"), "لایهٔ تنظیم");
      setTab("layers");
    },
    addRetouch: () => {
      addLayer(makeRetouch(), "لایهٔ روتوش");
      setTool("clone");
    },
    addWatermark: () => {
      const l = makeText(0.5, 0.5, props.asset.product_name ?? "برند شما");
      l.name = "واترمارک";
      l.size = 0.04;
      l.opacity = 0.35;
      l.tile = { angle: 28, gap: 1.6 };
      l.shadow = null;
      addLayer(l, "واترمارک");
    },
    duplicate: (id) => {
      const st0 = stateRef.current;
      const src0 = st0.layers.find((l) => l.id === id);
      if (!src0 || src0.type === "base") return;
      // رونوشتِ عمیق: گروه ⇒ با همهٔ نوادگان (شناسه‌ها نو، parent نگاشته، ماسکِ نقاشی‌شده کپی)
      const { clones, map } = cloneSubtree(st0.layers, id, nid);
      const topId = map.get(id)!;
      for (const copy of clones) {
        if (copy.id === topId) copy.name = `${src0.name} کپی`;
        if ("cx" in copy) {
          copy.cx = Math.min(0.98, copy.cx + 0.03);
          copy.cy = Math.min(0.98, copy.cy + 0.03);
        }
        if (copy.mask && copy.mask.type === "paint") {
          const nm = nid();
          masks.copy(copy.mask.id, nm);
          copy.mask = { ...copy.mask, id: nm, rev: 0 };
        }
      }
      // جای رونوشت: درست بالای خودِ لایه (برای گروه: بالای سرگروه)
      hist.apply("رونوشتِ لایه", (s) => {
        const i = s.layers.findIndex((x) => x.id === id);
        const arr = [...s.layers];
        arr.splice(i + 1, 0, ...clones);
        return { ...s, layers: canonical(arr) };
      });
      setActiveId(topId);
    },
    remove: (id) => {
      const st0 = stateRef.current;
      const l = st0.layers.find((x) => x.id === id);
      if (!l || l.type === "base" || effectivelyLocked(st0.layers, l)) return;
      const idx = st0.layers.findIndex((x) => x.id === id);
      // گروه ⇒ همراهِ همهٔ نوادگانش حذف می‌شود (یک گامِ تاریخچه)؛ ماسک‌های نقاشی‌شدهٔ همه پاک می‌شود
      const { layers: rest, removed } = removeWithDescendants(st0.layers, id);
      for (const r of removed) if (r.mask?.type === "paint") masks.remove(r.mask.id);
      hist.apply(removed.length > 1 ? "حذفِ گروه" : "حذفِ لایه", (s) => ({ ...s, layers: removeWithDescendants(s.layers, id).layers }));
      setActiveId(rest[Math.max(0, Math.min(rest.length - 1, idx - 1 - (removed.length - 1)))]?.id ?? null);
    },
    mergeDown: async (id) => {
      const st = stateRef.current;
      const i = st.layers.findIndex((l) => l.id === id);
      const upper = st.layers[i];
      const sibs = siblingsOf(st.layers, id);
      const lower = sibs[sibs.findIndex((l) => l.id === id) - 1]; // نزدیک‌ترین هم‌خواهرِ پایین‌تر (در همان گروه)
      const ok = (l?: Layer) => l && (l.type === "image" || l.type === "text" || l.type === "shape");
      const api = stageRef.current;
      if (!api || !ok(upper) || !ok(lower)) return null;
      setBusyOp("تلفیق…");
      try {
        api.engine.render(st, { masks: masks.map, only: new Set([upper.id, lower.id]) });
        const full = api.readFull();
        api.redraw();
        if (!full) return null;
        const { data, w, h } = full;
        let x0 = w;
        let y0 = h;
        let x1 = -1;
        let y1 = -1;
        for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (data[(y * w + x) * 4 + 3] > 2) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
        if (x1 < 0) return null;
        const bw = x1 - x0 + 1;
        const bh = y1 - y0 + 1;
        const cv = document.createElement("canvas");
        cv.width = bw;
        cv.height = bh;
        const sub = new ImageData(bw, bh);
        for (let y = 0; y < bh; y++) sub.data.set(data.subarray(((y + y0) * w + x0) * 4, ((y + y0) * w + x0 + bw) * 4), y * bw * 4);
        cv.getContext("2d")!.putImageData(sub, 0, 0);
        const blob = await new Promise<Blob | null>((r) => cv.toBlob(r, "image/png"));
        if (!blob) return null;
        const res = await photoApi.upload(storeId, [new File([blob], `merged-${nid()}.png`, { type: "image/png" })]);
        const a = res.assets[0];
        if (!a) throw new Error(res.errors[0] ?? "آپلود نشد.");
        setExtraAssets((e) => [...e, a]);
        const nl = makeImage({ kind: "asset", asset: a.id }, `${lower.name} + ${upper.name}`);
        nl.w = bw / w;
        nl.cx = (x0 + bw / 2) / w;
        nl.cy = (y0 + bh / 2) / h;
        if (lower.parent) nl.parent = lower.parent;
        hist.apply("تلفیقِ لایه‌ها", (s) => {
          const arr = s.layers.filter((l) => l.id !== upper.id && l.id !== lower.id);
          const at = Math.max(0, s.layers.findIndex((l) => l.id === lower.id));
          arr.splice(Math.min(at, arr.length), 0, nl);
          return { ...s, layers: arr };
        });
        setActiveId(nl.id);
        return nl.id;
      } catch (e) {
        setNotice({ tone: "bad", text: e instanceof Error ? e.message : "تلفیق نشد." });
        return null;
      } finally {
        setBusyOp("");
      }
    },
    reorder: (id, index) =>
      hist.apply("جابه‌جاییِ لایه", (s) => {
        const arr = [...s.layers];
        const from = arr.findIndex((l) => l.id === id);
        if (from < 0) return s;
        const [l] = arr.splice(from, 1);
        arr.splice(Math.max(0, Math.min(arr.length, index)), 0, l);
        return { ...s, layers: arr };
      }),
    newGroup: () => {
      const st0 = stateRef.current;
      const g = makeGroup(`گروه ${fa(st0.layers.filter((l) => l.type === "group").length + 1)}`);
      const act = st0.layers.find((l) => l.id === activeIdRef.current);
      const gs = new Set(st0.layers.filter((l) => l.type === "group").map((l) => l.id));
      const par = act ? parentIdOf(act, gs) : null;
      if (par) g.parent = par;
      hist.apply("گروهِ جدید", (s) => {
        const i = act ? s.layers.findIndex((x) => x.id === act.id) : -1;
        const arr = [...s.layers];
        arr.splice(i >= 0 ? i + 1 : arr.length, 0, g);
        return { ...s, layers: canonical(arr) };
      });
      setActiveId(g.id);
    },
    group: (id) => {
      const st0 = stateRef.current;
      const g = makeGroup(`گروه ${fa(st0.layers.filter((l) => l.type === "group").length + 1)}`);
      const r = wrapInGroup(st0.layers, id, g);
      if (!r) {
        setNotice({ tone: "info", text: "این لایه را نمی‌شود گروه کرد (لایهٔ عکس، یا بیش از ۴ سطح تودرتو)." });
        return null;
      }
      hist.apply("گروه کردنِ لایه", (s) => {
        const rr = wrapInGroup(s.layers, id, g);
        return rr ? { ...s, layers: rr.layers } : s;
      });
      setActiveId(r.groupId);
      return r.groupId;
    },
    ungroup: (id) => {
      const st0 = stateRef.current;
      const g = st0.layers.find((l) => l.id === id);
      if (!g || g.type !== "group" || effectivelyLocked(st0.layers, g)) return;
      if (g.mask?.type === "paint") masks.remove(g.mask.id);
      const kids = st0.layers.filter((l) => l.parent === id);
      hist.apply("بازکردنِ گروه", (s) => ({ ...s, layers: ungroupLayers(s.layers, id) }));
      setActiveId(kids[kids.length - 1]?.id ?? null);
    },
    moveLayer: (id, parent, index) =>
      hist.apply("جابه‌جاییِ لایه", (s) => {
        const next = moveTo(s.layers, id, parent, index);
        return next === s.layers ? s : { ...s, layers: next };
      }),
    moveSibling: (id, dir) =>
      hist.apply("جابه‌جاییِ لایه", (s) => {
        const next = treeMoveSibling(s.layers, id, dir);
        return next === s.layers ? s : { ...s, layers: next };
      }),
    toggleClip: (id) => {
      const l = stateRef.current.layers.find((x) => x.id === id);
      if (!l || l.type === "base") return;
      if (!l.clip && !clipTarget(stateRef.current.layers, id)) return;
      hist.apply(l.clip ? "برداشتنِ برش به لایهٔ زیرین" : "برش به لایهٔ زیرین", (s) => ({
        ...s, layers: s.layers.map((x) => (x.id === id ? ({ ...x, clip: !x.clip } as Layer) : x)),
      }));
    },
    setCollapsed: (id, v) =>
      hist.live((s) => ({ ...s, layers: s.layers.map((l) => (l.id === id && l.type === "group" ? { ...l, collapsed: v } : l)) })),
    addMask: (id, kind: MaskKind) => {
      let m: MaskSpec;
      if (kind === "reveal" || kind === "hide") {
        const mid = nid();
        masks.create(mid, kind === "reveal");
        m = { type: "paint", id: mid, invert: false, rev: 0 };
        if (kind === "reveal") setOpts({ erase: true });
      } else if (kind === "linear") m = { type: "linear", p0: [0.5, 0.3], p1: [0.5, 0.7], invert: false };
      else m = { type: "radial", c: [0.5, 0.5], rx: 0.3, ry: 0.2, feather: 0.6, invert: false };
      patch(id, { mask: m } as Partial<Layer>, "افزودنِ ماسک");
      if (m.type !== "paint") setTool("move");
    },
    removeMask: (id) => {
      const l = stateRef.current.layers.find((x) => x.id === id);
      if (l?.mask?.type === "paint") masks.remove(l.mask.id);
      patch(id, { mask: null } as Partial<Layer>, "حذفِ ماسک");
    },
    maskFromSelection: (id) => {
      if (!selection.active) return setNotice({ tone: "info", text: "اول با ابزارهای انتخاب (M, E, L, W) ناحیه‌ای را انتخاب کنید." });
      const mid = nid();
      selection.toMask(mid, masks);
      patch(id, { mask: { type: "paint", id: mid, invert: false, rev: 0 } } as Partial<Layer>, "ماسک از انتخاب");
    },
    paintMask: (id) => {
      setActiveId(id);
      setTool("brush");
    },
    focusText: () => {
      const el = document.querySelector<HTMLTextAreaElement>('[data-testid="text-input"]');
      el?.focus();
      el?.select();
    },
  };

  // لایهٔ تنظیمِ موضعی
  const localBrush = () => {
    const mid = nid();
    masks.create(mid, false);
    const l: AdjustLayer = { ...makeAdjust("تنظیمِ موضعی (قلم)", { exposure: 0.5 }), mask: { type: "paint", id: mid, invert: false, rev: 0 } };
    addLayer(l, "تنظیمِ موضعی");
    setOpts({ erase: false });
    setTool("brush");
    setTab("layers");
    setStatus("با قلم روی جاهایی که می‌خواهید اثر کند نقاشی کنید؛ لغزنده‌ها در زبانهٔ «لایه‌ها»");
  };
  const localGradient = (kind: "linear" | "radial") => {
    setOpts({ gradKind: kind });
    setTool("gradient");
    setTab("layers");
  };
  const adjustFromSelection = () => {
    if (!selection.active) return setNotice({ tone: "info", text: "اول ناحیه‌ای را انتخاب کنید." });
    const mid = nid();
    selection.toMask(mid, masks);
    const l: AdjustLayer = { ...makeAdjust("تنظیم روی انتخاب", { exposure: 0.4 }), mask: { type: "paint", id: mid, invert: false, rev: 0 } };
    addLayer(l, "تنظیم روی انتخاب");
    selection.clear();
    setSelVer((v) => v + 1);
    setTab("layers");
  };

  // ───────────────────────── انتخاب (selection)
  const bumpSel = () => setSelVer((v) => v + 1);
  const selInvert = () => {
    if (!selection.active) {
      selection.paint((c) => c.rect(0, 0, selection.w, selection.h), "new");
    } else selection.invert();
    bumpSel();
    stage?.redraw();
  };
  const selClear = () => {
    selection.clear();
    bumpSel();
    stage?.redraw();
  };
  const selFeather = (px: number) => {
    setOpts({ feather: px });
  };
  const selApplyFeather = () => {
    selection.feather(opts.feather);
    bumpSel();
    stage?.redraw();
  };
  const pickSubject = async () => {
    setBusyOp("انتخابِ سوژه…");
    try {
      let r = await proApi.subject(storeId, asset.id);
      for (let i = 0; i < 60 && r.state !== "READY" && r.state !== "FAILED" && r.job; i++) {
        await new Promise((res) => setTimeout(res, 1500));
        r = await proApi.subjectStatus(storeId, r.job);
      }
      if (r.state !== "READY" || !r.url) throw new Error(r.error || r.message || "سوژه پیدا نشد.");
      const img = await loadImg(r.url);
      // ماسکِ سوژه از سرور در فضای عکس است؛ انتخاب در فضای بومِ نهایی ⇒ از همان قاب رد می‌شود
      selection.fromImage(stage?.warpToCanvas(img) ?? img, "new");
      bumpSel();
      stage?.redraw();
      setStatus(r.method === "kit" ? "سوژه با کیتِ سرورِ پردازش انتخاب شد" : "سوژه با الگوریتمِ سبکِ سرورِ سایت انتخاب شد (روی پس‌زمینهٔ شلوغ ممکن است ناپاک باشد)");
    } catch (e) {
      setNotice({ tone: "bad", text: e instanceof Error ? e.message : "انتخابِ سوژه شکست خورد." });
    } finally {
      setBusyOp("");
    }
  };

  // ───────────────────────── قلم (Pen): مسیر ⇒ انتخاب / ماسک / لایهٔ شکل
  const selModeOf = (e: { shiftKey: boolean; altKey: boolean }): "new" | "add" | "sub" => (e.altKey ? "sub" : e.shiftKey ? "add" : "new");
  const penToSel = (mode: "new" | "add" | "sub"): boolean => {
    if (!penToSelection(pen, selection, mode)) {
      setNotice({ tone: "info", text: "برای انتخاب/ماسک، مسیر دست‌کم ۳ نقطه می‌خواهد." });
      return false;
    }
    if (opts.feather >= 0.5) selection.feather(opts.feather);
    pen.clear();
    bumpPen();
    bumpSel();
    stage?.redraw();
    return true;
  };
  const penMask = () => {
    if (!activeId) return setNotice({ tone: "info", text: "اول یک لایه را انتخاب کنید." });
    if (!penToSel("new")) return;
    actions.maskFromSelection(activeId);
    selection.clear();
    bumpSel();
    stage?.redraw();
  };
  const penShape = () => {
    const fr = stage?.frame() ?? frameSpec;
    const r = penToShape(pen, fr.Wf, fr.Hf);
    if (!r) return setNotice({ tone: "info", text: "مسیر دست‌کم ۲ نقطه می‌خواهد." });
    const l = makePathShape(r.path, r.box);
    if (!r.path.closed) {
      // مسیرِ باز پُر نمی‌شود؛ فقط خطِ دور
      l.fill = null;
      l.stroke = { color: "#ffffff", w: 0.006 };
    }
    pen.clear();
    bumpPen();
    addLayer(l, "لایهٔ شکلِ مسیر");
    setTool("move");
    setTab("layers");
  };
  const penKey = (key: string): boolean => {
    if (!pen.active) return false;
    if (key === "Enter") pen.finish();
    else if (key === "Escape") pen.clear();
    else if (key === "Backspace" || key === "Delete") pen.removeLast();
    else return false;
    bumpPen();
    return true;
  };

  // ───────────────────────── پرکردنِ هوشمند: ترکیبِ فعلی + انتخاب ⇒ سرور ⇒ لایهٔ تصویریِ تازه
  const gfCanvas = async (): Promise<{ cv: HTMLCanvasElement; w: number; h: number }> => {
    stage?.redraw();
    await new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
    const full = stage?.readFull();
    if (!full) throw new Error("بوم هنوز آماده نیست.");
    const cv = document.createElement("canvas");
    cv.width = full.w;
    cv.height = full.h;
    cv.getContext("2d")!.putImageData(new ImageData(new Uint8ClampedArray(full.data), full.w, full.h), 0, 0);
    return { cv, w: full.w, h: full.h };
  };
  const gfSized = (src: HTMLCanvasElement, bg: string | null) => {
    const k = Math.min(1, 2048 / Math.max(src.width, src.height));
    const out = document.createElement("canvas");
    out.width = Math.max(1, Math.round(src.width * k));
    out.height = Math.max(1, Math.round(src.height * k));
    const x = out.getContext("2d")!;
    if (bg) {
      x.fillStyle = bg;
      x.fillRect(0, 0, out.width, out.height);
    }
    x.imageSmoothingQuality = "high";
    x.drawImage(src, 0, 0, out.width, out.height);
    return out;
  };
  const toPng = (cv: HTMLCanvasElement) => new Promise<Blob>((res, rej) => cv.toBlob((b) => (b ? res(b) : rej(new Error("ساختِ تصویر شکست خورد."))), "image/png"));
  const gfGetImage = async (): Promise<Blob> => {
    const { cv } = await gfCanvas();
    return toPng(gfSized(cv, "#ffffff")); // بومِ شفاف (حاشیهٔ «جا دادن») روی سفید می‌نشیند؛ نشانِ انتخاب در این تصویر نیست
  };
  const gfGetMask = async (): Promise<Blob | null> => {
    if (!selection.active || !selection.canvas) return null;
    const cv = gfSized(selection.canvas, "#000000");
    const d = cv.getContext("2d")!.getImageData(0, 0, cv.width, cv.height).data;
    let any = false;
    for (let i = 0; i < d.length; i += 4) if (d[i] > 127) { any = true; break; }
    return any ? toPng(cv) : null;
  };
  const gfDone = (res: GenFillResult) => {
    setExtraAssets((e) => (e.some((a) => a.id === res.asset.id) ? e : [...e, res.asset]));
    const l = makeImage({ kind: "asset", asset: res.asset.id }, "پرکردن هوشمند");
    l.cx = res.layer.cx;
    l.cy = res.layer.cy;
    l.w = res.layer.w;
    addLayer(l, "پرکردنِ هوشمند");
    selection.clear();
    bumpSel();
    stage?.redraw();
  };
  const gfJob = (job: string | null) => {
    try {
      if (job) window.localStorage.setItem(gfKey, job);
      else window.localStorage.removeItem(gfKey);
    } catch {
      /* حافظهٔ مرورگر در دسترس نیست؛ فقط ادامه پس از بازکردنِ دوبارهٔ صفحه کار نمی‌کند */
    }
  };
  const openGenFill = () => {
    setGfOpen(true);
    setPanelOpen(true);
  };

  const onWb = (nx: number, ny: number) => {
    const c = stage?.engine.sampleBase(nx, ny, 3);
    if (!c) return;
    const { temperature, tint } = neutralizeToTempTint(c[0], c[1], c[2]);
    const cl = (v: number) => Math.max(-100, Math.min(100, Math.round(v)));
    hist.apply("تعادلِ سفیدی", (s) => ({ ...s, adjust: { ...s.adjust, temperature: cl(temperature), tint: cl(tint) } }));
    setStatus(`تعادلِ سفیدی: دما ${fa(cl(temperature))}، ته‌رنگ ${fa(cl(tint))}`);
    setTool("move");
  };

  // ───────────────────────── فیلترهای کیت
  const applyKitPreset = (key: string) => {
    const pr = kit.presets.find((p) => p.key === key);
    if (!pr?.recipe) return;
    hist.apply(`فیلتر: ${pr.title}`, (s) => {
      const next: ProState = { ...s, adjust: { ...(pr.recipe!.adjust ?? {}) }, curve: (pr.recipe!.curve ?? {}) as never };
      const bg = pr.recipe!.background;
      if (bg?.remove && tools.kit_background) next.tools = { ...s.tools, kit_background: { ...defaultsOf(tools.kit_background), bg: bg.color === "transparent" ? "transparent" : "white", shadow: bg.shadow ?? 0 } };
      if (pr.recipe!.output?.square) {
        const pad = Math.max(0, Math.min(40, Math.round((pr.recipe!.output.padding ?? 0.06) * 100)));
        next.tools = { ...(next.tools ?? s.tools), crop_format: { ...STORE_FRAME, padding: pad } };
      }
      return next;
    });
  };
  const makeThumb = useCallback(
    (recipe: { adjust: Record<string, number>; curve: Record<string, [number, number][]> }, size: number) => stage?.thumbnail(recipe.adjust, recipe.curve, size) ?? null,
    [stage],
  );
  useEffect(() => {
    if (stage) setThumbVersion((v) => v + 1);
  }, [stage, asset.id]);

  const quickAuto = () => {
    const eng = stage?.engine;
    if (!eng?.baseCpu) return;
    const d = eng.baseCpu;
    const hist8 = new Uint32Array(256);
    let n = 0;
    for (let i = 0; i < d.data.length; i += 16) {
      hist8[Math.round(0.299 * d.data[i] + 0.587 * d.data[i + 1] + 0.114 * d.data[i + 2])]++;
      n++;
    }
    const pct = (p: number) => {
      let acc = 0;
      for (let i = 0; i < 256; i++) {
        acc += hist8[i];
        if (acc >= n * p) return i;
      }
      return 255;
    };
    const lo = pct(0.005);
    const hi = pct(0.995);
    const med = pct(0.5);
    const out: Adjust = {};
    const clampN = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
    const ev = clampN(Math.log2((0.46 * 255) / Math.max(20, med)) * 0.6, -1.5, 1.5);
    if (Math.abs(ev) > 0.08) out.exposure = Math.round(ev * 100) / 100;
    if (hi < 235) out.whites = clampN(Math.round((235 - hi) * 0.5), 0, 60);
    if (lo > 20) out.blacks = -clampN(Math.round((lo - 20) * 0.6), 0, 50);
    if (hi - lo < 170) out.contrast = clampN(Math.round((170 - (hi - lo)) * 0.35), 0, 40);
    hist.apply("خودکار (مرورگر)", (s) => ({ ...s, adjust: { ...s.adjust, ...out } }));
  };

  // ───────────────────────── ساخت
  async function build(quick: boolean) {
    setBuildMsg(null);
    try {
      await saveProject();
      // «سوژه (خودکار)»: پنجرهٔ برش را مرورگر حساب می‌کند و همان به خروجی می‌رود (پیش‌نمایش = خروجی)
      const window = stageRef.current?.smartWindow(stateRef.current) ?? null;
      const ops: Operation[] = buildProOperations(stateRef.current, { quick, projectId: projRef.current?.id, window });
      await props.onBuild(ops, "manual");
      setBuildMsg(quick ? "ساختِ سریع (سرورِ سایت) شروع شد." : "ساخت شروع شد.");
      setTab("export");
    } catch (err) {
      setBuildMsg(err instanceof Error ? err.message : "ساخت شروع نشد.");
    }
  }
  const nodeOps = buildProOperations(state, { quick: false }).filter((o) => o.tool.startsWith("kit_"));

  // ───────────────────────── کلیدهای میان‌بر
  const actionsRef = useRef(actions);
  actionsRef.current = actions;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t instanceof HTMLInputElement && t.type !== "range" && t.type !== "checkbox") return;
      if (t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement || t.isContentEditable) return;
      const ctrl = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      const act = stateRef.current.layers.find((l) => l.id === activeIdRef.current) ?? null;
      if (ctrl) {
        if (k === "z") { e.preventDefault(); if (e.shiftKey) hist.redo(); else hist.undo(); return; }
        if (k === "y") { e.preventDefault(); hist.redo(); return; }
        if (k === "j" && act) { e.preventDefault(); actionsRef.current.duplicate(act.id); return; }
        if (k === "t") { e.preventDefault(); setTool("move"); return; }
        if (k === "d") { e.preventDefault(); selClear(); return; }
        if (k === "e" && act) { e.preventDefault(); void actionsRef.current.mergeDown(act.id); return; }
        if (k === "g" && act) {
          e.preventDefault();
          if (e.shiftKey) { if (act.type === "group") actionsRef.current.ungroup(act.id); } else if (act.type !== "base") actionsRef.current.group(act.id);
          return;
        }
        if (k === "i" && e.shiftKey) { e.preventDefault(); selInvert(); return; }
        return;
      }
      // قلم (Pen): Enter = پایانِ مسیر، Esc = لغو، Backspace/Delete = حذفِ آخرین نقطه (پیش از «حذفِ لایه» ِ پایین)
      if (toolRef.current === "pen" && penRef.current(e.key)) { e.preventDefault(); return; }
      if (e.key === "\\") return setCompare((c) => (c === "before" ? "off" : "before"));
      if (e.key === "0") return setZoomCmd({ id: Date.now(), kind: "fit" });
      if (e.key === "1") return setZoomCmd({ id: Date.now(), kind: "100" });
      if (e.key === "+" || e.key === "=") return setZoomCmd({ id: Date.now(), kind: "in" });
      if (e.key === "-") return setZoomCmd({ id: Date.now(), kind: "out" });
      if (e.key === "[") return e.shiftKey ? setOpts({ hardness: Math.max(0, optsRef.current.hardness - 0.1) }) : setOpts({ size: Math.max(0.002, optsRef.current.size * 0.85) });
      if (e.key === "]") return e.shiftKey ? setOpts({ hardness: Math.min(1, optsRef.current.hardness + 0.1) }) : setOpts({ size: Math.min(0.25, optsRef.current.size * 1.18) });
      if (k === "x") return setOpts({ erase: !optsRef.current.erase });
      if (e.key === "Delete" || e.key === "Backspace") {
        if (act && act.type !== "base" && !effectivelyLocked(stateRef.current.layers, act)) { e.preventDefault(); actionsRef.current.remove(act.id); }
        return;
      }
      if (e.key.startsWith("Arrow") && act && act.type === "group" && !effectivelyLocked(stateRef.current.layers, act)) {
        // گروه: همهٔ نوادگان با هم جابه‌جا می‌شوند
        e.preventDefault();
        const step = e.shiftKey ? 0.01 : 0.001;
        const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
        const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
        const ids = new Set(descendantIds(stateRef.current.layers, act.id));
        hist.apply("جابه‌جاییِ گروه", (s) => ({ ...s, layers: s.layers.map((l) => (ids.has(l.id) && "cx" in l ? ({ ...l, cx: +(l.cx + dx).toFixed(5), cy: +(l.cy + dy).toFixed(5) } as Layer) : l)) }));
        return;
      }
      if (e.key.startsWith("Arrow") && act && "cx" in act && !effectivelyLocked(stateRef.current.layers, act)) {
        e.preventDefault();
        const step = e.shiftKey ? 0.01 : 0.001;
        const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
        const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
        hist.apply("جابه‌جایی", (s) => ({ ...s, layers: s.layers.map((l) => (l.id === act.id && "cx" in l ? ({ ...l, cx: +(l.cx + dx).toFixed(5), cy: +(l.cy + dy).toFixed(5) } as Layer) : l)) }));
        return;
      }
      const hit = TOOLS.find((x) => x.key.toLowerCase() === k);
      if (hit) setTool(hit.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hist.undo, hist.redo, stage]);
  const activeIdRef = useRef(activeId);
  activeIdRef.current = activeId;
  const toolRef = useRef(tool);
  toolRef.current = tool;
  const penRef = useRef(penKey);
  penRef.current = penKey;
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const modified =
    Object.keys(state.adjust).length + (state.curve.rgb || state.curve.red || state.curve.green || state.curve.blue ? 1 : 0) + state.spots.length +
    Object.keys(state.tools).length + state.layers.filter((l) => l.type !== "base").length + (state.kitAuto ? 1 : 0);

  const info = TOOLS.find((x) => x.id === tool)!;

  // ───────────────────────── نوارِ گزینه‌های ابزار
  const redeyeLayer = activeLayer?.type === "redeye" && !activeLayer.locked ? activeLayer : null;
  const sizeSlider = (
    <>
      <label className="pro-opt">
        <span>اندازه</span>
        <input type="range" min={0.003} max={0.2} step={0.001} value={opts.size} onChange={(e) => setOpts({ size: Number(e.target.value) })} aria-label="اندازهٔ قلم" data-testid="brush-size" />
        <b dir="ltr">{fa(Math.round(opts.size * 1000) / 10)}%</b>
      </label>
      <label className="pro-opt">
        <span>سختی</span>
        <input type="range" min={0} max={1} step={0.05} value={opts.hardness} onChange={(e) => setOpts({ hardness: Number(e.target.value) })} aria-label="سختیِ قلم" data-testid="brush-hardness" />
        <b dir="ltr">{fa(Math.round(opts.hardness * 100))}</b>
      </label>
      <label className="pro-opt">
        <span>{tool === "brush" ? "شدت" : "پیدایی"}</span>
        <input type="range" min={0.05} max={1} step={0.05} value={opts.flow} onChange={(e) => setOpts({ flow: Number(e.target.value) })} aria-label="شدتِ قلم" data-testid="brush-flow" />
        <b dir="ltr">{fa(Math.round(opts.flow * 100))}</b>
      </label>
    </>
  );
  const optionsBar = (
    <div className="pro-opts" data-testid="tool-options-bar">
      <span className="pro-opt-title">{info.title}</span>
      {tool === "brush" && (
        <>
          {sizeSlider}
          <button type="button" className={`ws-btn ${opts.erase ? "is-on" : ""}`} onClick={() => setOpts({ erase: !opts.erase })} title="X" data-testid="brush-erase">
            {opts.erase ? "پاک‌کن (سیاه)" : "رنگ‌کن (سفید)"}
          </button>
          <button type="button" className="ws-btn" onClick={localBrush} data-testid="local-brush">+ قلمِ تنظیمِ موضعی</button>
        </>
      )}
      {(tool === "clone" || tool === "heal") && (
        <>
          {sizeSlider}
          <span className="ws-muted">Alt + کلیک = منبع</span>
        </>
      )}
      {tool === "gradient" && (
        <>
          <button type="button" className={chip(opts.gradKind === "linear")} onClick={() => setOpts({ gradKind: "linear" })} data-testid="grad-linear">خطی</button>
          <button type="button" className={chip(opts.gradKind === "radial")} onClick={() => setOpts({ gradKind: "radial" })} data-testid="grad-radial">شعاعی</button>
          <span className="ws-muted">بکشید؛ لغزنده‌ها در «لایه‌ها»</span>
        </>
      )}
      {(tool === "marquee" || tool === "ellipse" || tool === "lasso" || tool === "subject") && (
        <>
          <label className="pro-opt">
            <span>لبهٔ نرم</span>
            <input type="range" min={0} max={60} step={1} value={opts.feather} onChange={(e) => selFeather(Number(e.target.value))} aria-label="لبهٔ نرم" data-testid="sel-feather" />
            <b dir="ltr">{fa(opts.feather)}px</b>
          </label>
          <button type="button" className="ws-btn" onClick={selApplyFeather} disabled={!selection.active} data-testid="sel-apply-feather">اعمالِ لبهٔ نرم</button>
          <button type="button" className="ws-btn" onClick={selInvert} data-testid="sel-invert">معکوس (Ctrl+Shift+I)</button>
          <button type="button" className="ws-btn" onClick={selClear} disabled={!selection.active} data-testid="sel-clear">برداشتن (Ctrl+D)</button>
          <button type="button" className="ws-btn" onClick={() => activeId && actions.maskFromSelection(activeId)} disabled={!selection.active || !activeId} data-testid="sel-to-mask">ماسک روی لایهٔ فعال</button>
          <button type="button" className="ws-btn" onClick={adjustFromSelection} disabled={!selection.active} data-testid="sel-to-adjust">لایهٔ تنظیم از انتخاب</button>
          <button type="button" className="ws-btn" onClick={openGenFill} disabled={!selection.active} data-testid="sel-genfill" title="جای انتخاب‌شده را با هوش مصنوعی عوض یا حذف کنید">پرکردنِ هوشمند</button>
        </>
      )}
      {tool === "redeye" && (
        <>
          <label className="pro-opt">
            <span>اندازه</span>
            <input type="range" min={0.003} max={0.05} step={0.001} value={opts.eyeR} onChange={(e) => setOpts({ eyeR: Number(e.target.value) })} aria-label="اندازهٔ چشم (اگر خودکار پیدا نشد)" data-testid="eye-size" />
            <b dir="ltr">{fa(Math.round(opts.eyeR * 1000) / 10)}%</b>
          </label>
          <label className="pro-opt">
            <span>شدت</span>
            <input type="range" min={0} max={1} step={0.01} value={redeyeLayer?.amount ?? opts.eyeAmount} aria-label="شدتِ اصلاح" data-testid="eye-amount"
              onChange={(e) => { const v = Number(e.target.value); setOpts({ eyeAmount: v }); if (redeyeLayer) hist.live((s) => ({ ...s, layers: s.layers.map((l) => (l.id === redeyeLayer.id && l.type === "redeye" ? { ...l, amount: v } : l)) })); }}
              onPointerUp={() => hist.end("شدتِ قرمزیِ چشم")} onKeyUp={() => hist.end("شدتِ قرمزیِ چشم")} />
            <b dir="ltr">{fa(Math.round((redeyeLayer?.amount ?? opts.eyeAmount) * 100))}</b>
          </label>
          <label className="pro-opt">
            <span>تیره‌کردن</span>
            <input type="range" min={0} max={1} step={0.01} value={redeyeLayer?.darken ?? opts.eyeDarken} aria-label="تیره‌کردنِ مردمک" data-testid="eye-darken"
              onChange={(e) => { const v = Number(e.target.value); setOpts({ eyeDarken: v }); if (redeyeLayer) hist.live((s) => ({ ...s, layers: s.layers.map((l) => (l.id === redeyeLayer.id && l.type === "redeye" ? { ...l, darken: v } : l)) })); }}
              onPointerUp={() => hist.end("تیره‌کردنِ مردمک")} onKeyUp={() => hist.end("تیره‌کردنِ مردمک")} />
            <b dir="ltr">{fa(Math.round((redeyeLayer?.darken ?? opts.eyeDarken) * 100))}</b>
          </label>
          <span className="ws-muted">روی مردمکِ قرمز کلیک کنید · {redeyeLayer ? `${fa(redeyeLayer.eyes.length)} چشم در لایهٔ فعال` : "هر کلیک چشمی به لایهٔ «قرمزیِ چشم» می‌افزاید"}</span>
        </>
      )}
      {tool === "pen" && (
        <>
          <label className="pro-opt">
            <span>لبهٔ نرم</span>
            <input type="range" min={0} max={60} step={1} value={opts.feather} onChange={(e) => selFeather(Number(e.target.value))} aria-label="لبهٔ نرمِ انتخاب" data-testid="pen-feather" />
            <b dir="ltr">{fa(opts.feather)}px</b>
          </label>
          <button type="button" className="ws-btn" onClick={(e) => penToSel(selModeOf(e))} disabled={pen.pts.length < 3} data-testid="pen-select" title="مسیر را به انتخاب تبدیل می‌کند؛ Shift = افزودن، Alt = کم کردن">انتخاب</button>
          <button type="button" className="ws-btn" onClick={penMask} disabled={pen.pts.length < 3 || !activeId} data-testid="pen-mask" title="مسیر را ماسکِ لایهٔ فعال می‌کند">ماسک روی لایهٔ فعال</button>
          <button type="button" className="ws-btn" onClick={penShape} disabled={pen.pts.length < 2} data-testid="pen-shape" title="مسیر را به یک لایهٔ شکل (پر/خطِ دور) تبدیل می‌کند">لایهٔ شکل</button>
          <button type="button" className="ws-btn" onClick={() => { if (penToSel("new")) openGenFill(); }} disabled={pen.pts.length < 3} data-testid="pen-genfill" title="جای داخلِ مسیر را با هوش مصنوعی عوض یا حذف کنید">پرکردنِ هوشمند</button>
          <button type="button" className="ws-btn" onClick={() => { pen.close(); bumpPen(); }} disabled={pen.pts.length < 3 || pen.closed} data-testid="pen-close">بستنِ مسیر</button>
          <button type="button" className="ws-btn" onClick={() => penKey("Enter")} disabled={pen.pts.length < 2 || pen.finished} data-testid="pen-finish" title="Enter">پایانِ مسیرِ باز</button>
          <button type="button" className="ws-btn" onClick={() => penKey("Backspace")} disabled={!pen.active} data-testid="pen-undo" title="Backspace">حذفِ آخرین نقطه</button>
          <button type="button" className="ws-btn" onClick={() => penKey("Escape")} disabled={!pen.active} data-testid="pen-cancel" title="Esc">لغو</button>
          <span className="ws-muted" data-testid="pen-info">{pen.active ? `${fa(pen.pts.length)} نقطه${pen.closed ? " · بسته" : pen.done ? " · باز (تمام‌شده)" : ""}` : "کلیک = نقطه · کلیک و کشیدن = منحنی · کلیک روی نقطهٔ اول = بستن · Alt+کلیک روی نقطه = گوشه/نرم"}</span>
        </>
      )}
      {tool === "liquify" && (
        <>
          {([["push", "کشیدن"], ["bloat", "باد کردن"], ["pucker", "جمع کردن"], ["reconstruct", "بازسازی"]] as [ToolOpts["liq"], string][]).map(([k, t]) => (
            <button key={k} type="button" className={chip(opts.liq === k)} onClick={() => setOpts({ liq: k })} data-liq={k} aria-pressed={opts.liq === k}>{t}</button>
          ))}
          <label className="pro-opt">
            <span>اندازه</span>
            <input type="range" min={0.01} max={0.25} step={0.005} value={opts.liqSize} onChange={(e) => setOpts({ liqSize: Number(e.target.value) })} aria-label="اندازهٔ قلمِ مایع‌سازی" data-testid="liq-size" />
            <b dir="ltr">{fa(Math.round(opts.liqSize * 1000) / 10)}%</b>
          </label>
          <label className="pro-opt">
            <span>فشار</span>
            <input type="range" min={0.05} max={1} step={0.05} value={opts.liqStrength} onChange={(e) => setOpts({ liqStrength: Number(e.target.value) })} aria-label="فشارِ قلمِ مایع‌سازی" data-testid="liq-strength" />
            <b dir="ltr">{fa(Math.round(opts.liqStrength * 100))}</b>
          </label>
          {opts.liq !== "push" && (
            <label className="pro-opt">
              <span>آهنگ</span>
              <input type="range" min={0} max={1} step={0.05} value={opts.liqRate} onChange={(e) => setOpts({ liqRate: Number(e.target.value) })} aria-label="آهنگِ اثر (ثابت ماندن)" data-testid="liq-rate" />
              <b dir="ltr">{fa(Math.round(opts.liqRate * 100))}</b>
            </label>
          )}
          <button type="button" className="ws-btn" disabled={!liquify.active && !state.liquify} data-testid="liq-reset"
            onClick={() => { liquify.resetAll(); hist.apply("بازنشانیِ مایع‌سازی", (s) => ({ ...s, liquify: null })); stage?.redraw(); }}>
            بازنشانیِ همه
          </button>
          <span className="ws-muted" data-testid="liq-hint">
            {frameSpec.trivial ? "روی عکس بکشید؛ هر ضربه یک گامِ برگشت است" : "قاب/برش فعال است: ضربه‌ها از قاب به عکس برمی‌گردند و حاشیهٔ قاب بی‌اثر است"}
          </span>
        </>
      )}
      {tool === "genfill" && (
        <>
          <label className="pro-opt">
            <span>اندازه</span>
            <input type="range" min={0.003} max={0.2} step={0.001} value={opts.size} onChange={(e) => setOpts({ size: Number(e.target.value) })} aria-label="اندازهٔ قلم" data-testid="gf-size" />
            <b dir="ltr">{fa(Math.round(opts.size * 1000) / 10)}%</b>
          </label>
          <label className="pro-opt">
            <span>سختی</span>
            <input type="range" min={0} max={1} step={0.05} value={opts.hardness} onChange={(e) => setOpts({ hardness: Number(e.target.value) })} aria-label="سختیِ قلم" data-testid="gf-hardness" />
            <b dir="ltr">{fa(Math.round(opts.hardness * 100))}</b>
          </label>
          <button type="button" className="ws-btn" onClick={selInvert} data-testid="gf-invert">معکوس</button>
          <button type="button" className="ws-btn" onClick={selClear} disabled={!selection.active} data-testid="gf-clear">برداشتنِ ناحیه</button>
          <span className="ws-muted">Alt + کشیدن = کم کردن · «اجرا» در پنلِ سمتِ راست</span>
        </>
      )}
      {tool === "crop" && (
        <>
          {ASPECTS.map((a) => (
            <button key={a.key} type="button" className={chip(aspectKey === a.key)} onClick={() => chooseAspect(a.key)} data-aspect={a.key}>{a.title}</button>
          ))}
          <label className="ws-check"><input type="checkbox" checked={flipAspect} onChange={(e) => setFlipAspect(e.target.checked)} />جابه‌جا کردنِ افقی/عمودی</label>
          <span dir="ltr" data-testid="crop-size" className="ws-muted">{fa(Math.round(state.crop.w * Wt))}×{fa(Math.round(state.crop.h * Ht))} px</span>
          <button type="button" className="ws-link" onClick={() => hist.apply("بازنشانیِ برش", (s) => ({ ...s, crop: { ...FULL } }))}>بازنشانیِ برش</button>
        </>
      )}
      {tool === "straighten" && (
        <>
          <label className="pro-opt">
            <span>افق</span>
            <input type="range" min={-15} max={15} step={0.1} value={state.straighten} aria-label="صاف کردنِ افق" data-testid="straighten"
              onChange={(e) => hist.live((s) => ({ ...s, straighten: Number(e.target.value), crop: { ...FULL } }))}
              onPointerUp={() => hist.end("صاف کردن")} onKeyUp={() => hist.end("صاف کردن")}
              onDoubleClick={() => hist.apply("صاف کردن", (s) => ({ ...s, straighten: 0 }))} />
            <b dir="ltr">{fa(state.straighten)}°</b>
          </label>
          <button type="button" className="ws-chip" onClick={() => rotate(90)}>۹۰° پادساعتگرد</button>
          <button type="button" className="ws-chip" onClick={() => rotate(-90)}>۹۰° ساعتگرد</button>
          <button type="button" className={chip(state.flipH)} onClick={() => hist.apply("قرینهٔ افقی", (s) => ({ ...s, flipH: !s.flipH }))}>قرینهٔ افقی</button>
          <button type="button" className={chip(state.flipV)} onClick={() => hist.apply("قرینهٔ عمودی", (s) => ({ ...s, flipV: !s.flipV }))}>قرینهٔ عمودی</button>
        </>
      )}
      {tool === "persp" && (
        <>
          <label className="pro-opt">
            <span>عمودی</span>
            <input type="range" min={-100} max={100} step={1} value={perspSlider(state.persp, "v")} aria-label="اصلاحِ عمودی"
              onChange={(e) => hist.live((s) => ({ ...s, persp: quadFromSliders(Number(e.target.value), perspSlider(s.persp, "h")) }))} onPointerUp={() => hist.end("پرسپکتیوِ عمودی")} data-testid="persp-v" />
          </label>
          <label className="pro-opt">
            <span>افقی</span>
            <input type="range" min={-100} max={100} step={1} value={perspSlider(state.persp, "h")} aria-label="اصلاحِ افقی"
              onChange={(e) => hist.live((s) => ({ ...s, persp: quadFromSliders(perspSlider(s.persp, "v"), Number(e.target.value)) }))} onPointerUp={() => hist.end("پرسپکتیوِ افقی")} data-testid="persp-h" />
          </label>
          <button type="button" className="ws-link" onClick={() => hist.apply("بازنشانیِ پرسپکتیو", (s) => ({ ...s, persp: null }))}>بازنشانی</button>
        </>
      )}
      {tool === "spot" && (
        <>
          <label className="pro-opt">
            <span>اندازه</span>
            <input type="range" min={0.005} max={0.1} step={0.005} value={opts.spotR} onChange={(e) => setOpts({ spotR: Number(e.target.value) })} aria-label="اندازهٔ لکه" />
          </label>
          <span data-testid="spot-count" className="ws-muted">{fa(state.spots.length)} لکه</span>
          {state.spots.length > 0 && <button type="button" className="ws-link" onClick={() => hist.apply("پاک کردنِ لکه‌ها", (s) => ({ ...s, spots: [] }))}>پاک کردنِ همه</button>}
        </>
      )}
      {(tool === "move" || tool === "hand" || tool === "text" || tool === "wb") && <span className="ws-muted">{info.hint}</span>}
      {(tool === "marquee" || tool === "ellipse" || tool === "lasso") && selection.active && <span className="ws-muted" data-testid="sel-active">انتخاب فعال است</span>}
      <span className="ws-spacer" />
      <select className="pro-grid-sel" value={opts.grid} onChange={(e) => setOpts({ grid: e.target.value as ToolOpts["grid"] })} aria-label="شبکهٔ راهنما" data-testid="grid-select">
        <option value="off">بی‌شبکه</option>
        <option value="thirds">ثلث‌ها</option>
        <option value="golden">طلایی</option>
        <option value="diag">قطری</option>
      </select>
    </div>
  );

  // ───────────────────────── زبانه‌ها
  const editTab = (
    <div className="ws-sections" data-testid="edit-sections">
      <FrameCard state={state} hist={H} tool={tools.crop_format} spec={frameSpec} photoSize={[asset.width, asset.height]} />
      <div className="mb-2 flex flex-wrap gap-1">
        <button type="button" className="ws-chip" onClick={quickAuto} data-testid="auto-browser" title="از روی هیستوگرام نوردهی و کنتراست را می‌چیند">خودکار (مرورگر)</button>
        <button type="button" className={chip(state.kitAuto)} onClick={() => hist.apply("بهبودِ خودکارِ کیت", (s) => ({ ...s, kitAuto: !s.kitAuto }))} title="کیت روی سرورِ پردازش خودش نور و رنگ را درست می‌کند (در پیش‌نمایشِ دقیق دیده می‌شود)">
          بهبودِ خودکارِ کیت {state.kitAuto ? "✓" : ""}
        </button>
        <button type="button" className={chip(!!state.tools.auto_tone)} onClick={() => setTools("نور و رنگِ خودکارِ سبک", "auto_tone", state.tools.auto_tone ? null : defaultsOf(tools.auto_tone))} title="نسخهٔ سبکِ سرورِ سایت؛ بی سرورِ پردازش">
          خودکارِ سبک (سرور) {state.tools.auto_tone ? "✓" : ""}
        </button>
        <button type="button" className={chip(tool === "wb")} onClick={() => setTool("wb")} title="I">قطره‌چکانِ تعادلِ سفیدی</button>
      </div>
      {EXTRA_KEYS.some((k) => state.tools[k]) && (
        <div className="ws-card" data-testid="carried-steps">
          <div className="ws-card-title">مرحله‌های آمده از حالتِ خودکار / پیشنهادی</div>
          <p className="ws-hint">هر کدام را خاموش یا اصلاح کنید؛ با «ساخت» اعمال می‌شوند.</p>
          {EXTRA_KEYS.filter((k) => state.tools[k] && tools[k]).map((k) => (
            <div key={k} className="mb-2" data-carried={k}>
              <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text)" }}>
                <b>{tools[k].title}</b>
                <Badge tone={tools[k].where === "node" ? (nodeOn ? "info" : "warn") : "neutral"}>{tools[k].where === "node" ? "سرورِ پردازش" : "سرورِ سایت"}</Badge>
                <span className="ws-spacer" />
                <button type="button" className="ws-link" onClick={() => setTools(`برداشتنِ ${tools[k].title}`, k, null)}>برداشتن</button>
              </div>
              <div onPointerUp={() => hist.end(tools[k].title)} onKeyUp={() => hist.end(tools[k].title)} onBlur={() => hist.end(tools[k].title)}>
                <OperationForm tool={tools[k]} params={state.tools[k]} kit={kit} spotImage={null} onChange={(p) => liveTools(k, p)} />
              </div>
            </div>
          ))}
        </div>
      )}
      {SECTIONS.map((sec) => (
        <div key={sec.key} className="ws-acc" data-section={sec.key}>
          <button type="button" className="ws-acc-head" onClick={() => setOpen((o) => ({ ...o, [sec.key]: !o[sec.key] }))} aria-expanded={!!open[sec.key]}>
            <span>{sec.title}</span>
            {sec.groups.some((g) => kit.params.some((p) => p.group === g && p.key in state.adjust)) && <i className="ws-dot" />}
            {sec.key === "curves" && (state.curve.rgb || state.curve.red || state.curve.green || state.curve.blue) && <i className="ws-dot" />}
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

  const smartTab = (
    <div data-testid="smart-tab">
      <p className="ws-hint">این ابزارها روی سرورِ پردازش (کیتِ PersianAiKit.Photo) اجرا می‌شوند و فقط هنگامِ «ساخت» اعمال می‌شوند. قابِ مربع و اندازهٔ شبکه‌ها در زبانهٔ «تنظیم» ⇐ «قاب» است.</p>
      {KIT_TOOLS.map(({ key, title }) => {
        const t = tools[key];
        if (!t) return null;
        return (
          <div className="ws-card" key={key} data-kit={key}>
            <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text)" }}>
              <input type="checkbox" checked={!!state.tools[key]} onChange={(e) => setTools(e.target.checked ? title : `برداشتنِ ${title}`, key, e.target.checked ? defaultsOf(t) : null)} />
              <b>{title}</b>
              <Badge tone={nodeOn ? "info" : "warn"}>{nodeOn ? "سرورِ پردازش" : "خاموش"}</Badge>
            </label>
            <p className="ws-hint">{t.help}</p>
            {state.tools[key] && (
              <div onPointerUp={() => hist.end(title)} onKeyUp={() => hist.end(title)} onBlur={() => hist.end(title)}>
                <OperationForm tool={t} params={state.tools[key]} kit={kit} spotImage={null} onChange={(p) => liveTools(key, p)} />
              </div>
            )}
          </div>
        );
      })}
      <div className="flex flex-wrap gap-1">
        <button type="button" className="ws-chip" onClick={() => hist.apply("عکسِ فروشگاهی", (s) => {
          const t: Record<string, Params> = { ...s.tools };
          if (tools.kit_background) t.kit_background = { ...defaultsOf(tools.kit_background), bg: "white", shadow: 25 };
          t.crop_format = STORE_FRAME;
          return { ...s, tools: t };
        })} data-testid="smart-store">عکسِ فروشگاهی (سفید + مربع)</button>
        <button type="button" className="ws-chip" onClick={() => hist.apply("کالا بی‌پس‌زمینه", (s) => {
          const t: Record<string, Params> = { ...s.tools };
          if (tools.kit_background) t.kit_background = { ...defaultsOf(tools.kit_background), bg: "transparent", shadow: 0 };
          const cf = effectiveCropFormat(t);
          // قابِ «جا دادن» دورِ کالا را شفاف می‌کند تا PNG بی‌پس‌زمینه بماند
          if (cf && cf.fit === "contain") t.crop_format = cropFormatOpParams({ ...cf, fill: "transparent", window: [] });
          return { ...s, tools: t, out: { ...s.out, format: "png" } };
        })}>کالا بی‌پس‌زمینه (PNG)</button>
      </div>
    </div>
  );

  const layersTab = (
    <div data-testid="layers-tab">
      <div className="mb-2 flex flex-wrap gap-1">
        <button type="button" className="ws-chip" onClick={localBrush} data-testid="local-brush-2">قلمِ تنظیمِ موضعی</button>
        <button type="button" className="ws-chip" onClick={() => localGradient("linear")} data-testid="local-linear">شیبِ خطی</button>
        <button type="button" className="ws-chip" onClick={() => localGradient("radial")} data-testid="local-radial">شیبِ شعاعی</button>
      </div>
      <LayersPanel
        state={state} hist={H} activeId={activeId} setActiveId={setActiveId} actions={actions} assets={allAssets} storeLogo={props.storeLogo ?? null}
        fonts={fonts} kit={kit} layerBox={(id) => { const l = state.layers.find((x) => x.id === id); return l && stage ? stage.layerSize(l) : null; }}
      />
      <LayerInspector
        state={state} hist={H} layer={activeLayer} actions={actions} fonts={fonts} kit={kit} assets={allAssets} storeLogo={props.storeLogo ?? null}
        layerBox={(id) => { const l = state.layers.find((x) => x.id === id); return l && stage ? stage.layerSize(l) : null; }}
        canvasAspect={frameSpec.Hf / frameSpec.Wf}
      />
    </div>
  );

  const historyTab = (
    <div data-testid="history-tab">
      <div className="mb-2 flex gap-2">
        <Button size="sm" variant="secondary" disabled={!hist.canUndo} onClick={hist.undo}>برگشت (Ctrl+Z)</Button>
        <Button size="sm" variant="secondary" disabled={!hist.canRedo} onClick={hist.redo}>جلو (Ctrl+Shift+Z)</Button>
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
          <Select value={state.out.format} onChange={(e) => hist.apply("قالبِ خروجی", (s) => ({ ...s, out: { ...s.out, format: e.target.value as ProState["out"]["format"] } }))}>
            <option value="jpeg">JPEG</option>
            <option value="png">PNG (شفاف)</option>
            <option value="webp">WebP</option>
          </Select>
        </label>
        <ParamSlider
          p={{ key: "quality", group: "", title: "کیفیت", help: "", min: 40, max: 100, default: 92, step: 1, unit: "" }}
          value={state.out.quality}
          onLive={(v) => hist.live((s) => ({ ...s, out: { ...s.out, quality: v } }))} onEnd={() => hist.end("کیفیت")} onReset={() => hist.apply("کیفیت", (s) => ({ ...s, out: { ...s.out, quality: 92 } }))}
        />
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

      <div className="ws-card" data-testid="frame-summary">
        <div className="ws-card-title">قاب</div>
        <p className="ws-hint">
          {state.tools.crop_format
            ? <>خروجی در قابِ <b dir="ltr">{fa(frameSpec.Wf)}×{fa(frameSpec.Hf)}</b> پیکسل ساخته می‌شود؛ لایه‌ها نسبت به همین قاب چیده شده‌اند.</>
            : <>قابِ شبکه‌ها انتخاب نشده؛ خروجی هم‌اندازهٔ عکس (پس از برش) است: <b dir="ltr">{fa(frameSpec.Wf)}×{fa(frameSpec.Hf)}</b> پیکسل.</>}
        </p>
        <button type="button" className="ws-chip" onClick={() => setTab("edit")} data-testid="frame-open">تنظیمِ قاب (اندازهٔ شبکه‌ها، مربعِ فروشگاه)</button>
      </div>

      <div className="ws-card" data-testid="build-card">
        <div className="ws-card-title">ساخت (خروجیِ کامل و دقیق)</div>
        {nodeOps.length > 0 && (
          <div className="mb-2">
            <Alert tone={nodeOn ? "info" : "warn"}>
              {nodeOn
                ? `کارهای کیت (${nodeOps.map((o) => tools[o.tool]?.title).join("، ")}) روی ${props.nodeNames.join("، ")} انجام می‌شود؛ بعد لایه‌ها روی سرورِ سایت ترکیب می‌شوند.`
                : `سرورِ پردازش الان خاموش است: ${fa(nodeOps.length)} کار (${nodeOps.map((o) => tools[o.tool]?.title).join("، ")}) در صف می‌ماند. «ساختِ سریع» همین حالا با لغزنده‌های کاملِ کیت (نسخهٔ سرورِ سایت) و لایه‌ها نتیجه می‌دهد.`}
            </Alert>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void build(false)} disabled={props.busy} data-testid="build">
            {nodeOps.length && !nodeOn ? "ساخت (در صفِ سرورِ پردازش)" : "ساخت و ذخیره"}
          </Button>
          <Button variant="secondary" onClick={() => void build(true)} disabled={props.busy} data-testid="build-quick" title="لغزنده‌ها + لایه‌ها روی سرورِ سایت، بی‌انتظارِ سرورِ پردازش">
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
                <img src={props.lastEdit.urls.preview} alt="نتیجه" className="ws-result" data-testid="last-result" />
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

  const exactChip = exactStatus === "ready"
    ? <Badge tone="ok">دقیق (سرورِ پردازش)</Badge>
    : exactStatus === "pending"
      ? <Badge tone="info">فوری · در حال ساختِ دقیق…</Badge>
      : exactStatus === "offline"
        ? <Badge tone="warn" >فوری · سرورِ پردازش خاموش</Badge>
        : exactStatus === "error"
          ? <Badge tone="warn">فوری · پیش‌نمایشِ دقیق ناموفق</Badge>
          : <Badge tone="neutral">فوری</Badge>;

  return (
    <Workspace
      testId="photo-workspace"
      title="فضای کارِ حرفه‌ایِ عکس"
      actions={
        <>
          <Badge tone={nodeOn ? "ok" : "warn"}>{nodeOn ? "سرورِ پردازش آنلاین" : "سرورِ پردازش خاموش"}</Badge>
          <span className="ws-muted" data-testid="modified">{fa(modified)} تغییر</span>
        </>
      }
    >
      <div className="pw-grid pro-grid" dir="ltr" data-pro="1">
        <div className="pw-top" dir="rtl">
          <Select value={asset.id} onChange={(e) => props.onPick(Number(e.target.value))} aria-label="عکس" className="!w-44">
            {props.assets.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
          </Select>
          <button type="button" className="ws-btn" disabled={!hist.canUndo} onClick={hist.undo} title="برگشت (Ctrl+Z)" data-testid="undo">↶ برگشت</button>
          <button type="button" className="ws-btn" disabled={!hist.canRedo} onClick={hist.redo} title="جلو (Ctrl+Shift+Z)" data-testid="redo">↷ جلو</button>
          <span className="ws-sep" />
          <button type="button" className={`ws-btn ${compare === "before" ? "is-on" : ""}`} onClick={() => setCompare((c) => (c === "before" ? "off" : "before"))} title="نمایشِ «قبل» ( \ )" data-testid="compare-before">قبل</button>
          <button type="button" className={`ws-btn ${compare === "split" ? "is-on" : ""}`} onClick={() => setCompare((c) => (c === "split" ? "off" : "split"))} data-testid="compare-split">قبل | بعد</button>
          <span className="ws-sep" />
          {zoomBtn("out", "−", "کوچک‌نمایی")}
          <span className="ws-muted" dir="ltr" data-testid="zoom-pct">{fa(zoomPct)}%</span>
          {zoomBtn("in", "+", "بزرگ‌نمایی")}
          {zoomBtn("fit", "جا شدن", "جا شدن در قاب (0)")}
          {zoomBtn("100", "۱۰۰٪", "اندازهٔ واقعی (1)")}
          <span className="ws-sep" />
          <span data-testid="exact-chip" data-exact={exactStatus}>{exactChip}</span>
          <span className="ws-muted" data-testid="save-msg">{saveMsg}</span>
          {busyOp && <span className="ws-muted"><Spinner size={13} /> {busyOp}</span>}
          <span className="ws-spacer" />
          <button type="button" className="ws-btn primary" onClick={() => void build(false)} disabled={props.busy} data-testid="build-top">ساخت</button>
          <button type="button" className="ws-btn pw-panel-toggle" onClick={() => setPanelOpen((v) => !v)}>پنل</button>
          {optionsBar}
        </div>

        <div className="pw-tools" dir="rtl" role="toolbar" aria-label="ابزارها" data-testid="toolbar">
          {TOOLS.map((t) => (
            <span key={t.id} style={{ display: "contents" }}>
              {t.sep && <i className="pro-tool-sep" />}
              <button type="button" className={`ws-tool ${tool === t.id ? "is-on" : ""}`} onClick={() => setTool(t.id)} title={`${t.title} (${t.key})`} aria-label={t.title} aria-pressed={tool === t.id} data-tool={t.id}>
                <ToolIcon t={t} />
              </button>
            </span>
          ))}
        </div>

        <div className="pw-canvas">
          <Stage
            src={src} origW={asset.width} origH={asset.height} hasAlpha={!!asset.has_alpha} state={state} hist={H} tool={tool} opts={opts} setOpts={setOpts}
            activeId={activeId} setActiveId={setActiveId} masks={masks} selection={selection} assets={allAssets} storeLogo={props.storeLogo ?? null}
            compare={compare} exact={exactImg} zoomCmd={zoomCmd} aspect={aspectRatio}
            onZoom={setZoomPct} onStatus={setStatus} onReady={(api) => { setStage(api); (window as unknown as { __photoPro?: StageApi }).__photoPro = api; }} onHistogram={setHdata}
            onSelectionChange={bumpSel} pen={pen} onPenChange={bumpPen} liquify={liquify} onMaskEdited={() => undefined} onWb={onWb} onSubject={() => void pickSubject()}
            onNeedTextFocus={() => window.setTimeout(() => actions.focusText(), 80)} onToolChange={setTool}
            onError={(m) => setNotice({ tone: "bad", text: m })} onImageSizes={() => stage?.redraw()}
          />
          {notice && (
            <div className={`pw-overlay-msg ${notice.tone === "bad" ? "bad" : ""}`} data-testid="notice" onClick={() => setNotice(null)}>{notice.text}</div>
          )}
        </div>

        <div className={`pw-panel ${panelOpen ? "" : "is-closed"}`} dir="rtl" data-testid="right-panel">
          <Histogram data={hdata} />
          <div className="ws-tabs pro-tabs" role="tablist">
            {([["edit", "تنظیم"], ["layers", "لایه‌ها"], ["presets", "فیلتر"], ["smart", "هوشمند"], ["history", "تاریخچه"], ["export", "خروجی"]] as [Tab, string][]).map(([k, t]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "is-on" : ""} onClick={() => setTab(k)} data-tab={k}>{t}</button>
            ))}
          </div>
          <div className="pw-panel-scroll">
            {/* همیشه سوار می‌ماند (پرسیدنِ کار با عوض‌کردنِ ابزار قطع نشود)؛ فقط وقتی لازم است دیده می‌شود */}
            <div className="ws-card" data-testid="genfill-card" style={gfOpen || tool === "genfill" || gfBusy ? undefined : { display: "none" }}>
              {gfOpen && tool !== "genfill" && !gfBusy && (
                <button type="button" className="ws-link" onClick={() => setGfOpen(false)} data-testid="genfill-close">بستنِ پنل</button>
              )}
              <GenFillPanel
                storeId={storeId} assetId={asset.id} getImage={gfGetImage} getMask={gfGetMask} onResult={gfDone}
                onJobChange={gfJob} resumeJob={gfResume} onBusyChange={setGfBusy}
              />
            </div>
            {tab === "edit" && editTab}
            {tab === "layers" && layersTab}
            {tab === "presets" && (
              <PresetsPanel
                storeId={storeId} state={state} hist={H} kit={kit} assets={allAssets} currentAssetId={asset.id} makeThumb={makeThumb}
                thumbVersion={thumbVersion} nodeOn={nodeOn} applyKitPreset={applyKitPreset}
                onBatch={(r) => setNotice({ tone: "info", text: `${fa(r.count)} نسخه ساخته شد؛ در بخش «نسخه‌ها»ی همین صفحه دیده می‌شوند.` })}
              />
            )}
            {tab === "smart" && smartTab}
            {tab === "history" && historyTab}
            {tab === "export" && exportTab}
          </div>
        </div>

        <div className="pw-status" dir="rtl">
          <span data-testid="status-size" dir="ltr">{fa(asset.width)}×{fa(asset.height)} → {fa(frameSpec.Wf)}×{fa(frameSpec.Hf)}</span>
          <span data-testid="status-text">{status}</span>
          <span className="ws-spacer" />
          <span>V جابه‌جایی · C برش · T متن · B قلم · G شیب · S مهر · M/E/L/W انتخاب · I تعادلِ سفیدی · R قرمزیِ چشم · P قلم · Q مایع‌سازی · F پرکردنِ هوشمند · Ctrl+Z · Ctrl+J · Ctrl+G گروه · [ ] اندازهٔ قلم</span>
        </div>
      </div>
    </Workspace>
  );
}

// ───────────────────────── پرسپکتیو با دو لغزنده (مثلِ Transform ِ لایت‌روم)
function perspSlider(q: Quad | null, axis: "v" | "h"): number {
  if (!q) return 0;
  if (axis === "v") return Math.round(((q.tl[0] > 0 ? q.tl[0] : -q.bl[0]) / 0.25) * 100);
  return Math.round(((q.tl[1] > 0 ? q.tl[1] : -q.tr[1]) / 0.25) * 100);
}
function quadFromSliders(v: number, h: number): Quad | null {
  if (!v && !h) return null;
  const a = (v / 100) * 0.25;
  const b = (h / 100) * 0.25;
  const pa = Math.max(a, 0);
  const na = Math.max(-a, 0);
  const pb = Math.max(b, 0);
  const nb = Math.max(-b, 0);
  return { tl: [pa, pb], tr: [1 - pa, nb], br: [1 - na, 1 - nb], bl: [na, 1 - pb] };
}
