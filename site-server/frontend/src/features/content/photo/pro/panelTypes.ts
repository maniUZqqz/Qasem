import type { Asset, FontInfo, Kit, NodeStatus, Preset } from "../api";
import type { Layer, MaskSpec, ProState } from "./types";

/** تاریخچهٔ ادیتور (همان useHistory<ProState>) */
export type Hist = {
  apply: (label: string, fn: (s: ProState) => ProState) => void;
  live: (fn: (s: ProState) => ProState) => void;
  end: (label: string) => void;
};

export type MaskKind = "reveal" | "hide" | "linear" | "radial";

/** کارهایی که فضای کار (ProWorkspace) انجام می‌دهد و پنل‌ها فقط صدایشان می‌زنند */
export type ProActions = {
  addText: () => void;
  addShape: (shape: "rect" | "ellipse" | "line") => void;
  addImageFromAsset: (assetId: number) => void;
  addLogo: () => void;
  uploadImage: (file: File) => Promise<void>;
  addAdjust: () => void;
  addRetouch: () => void;
  addWatermark: () => void;
  duplicate: (id: string) => void;
  remove: (id: string) => void;
  /** تلفیقِ لایه با لایهٔ زیرین (فقط تصویر/متن/شکل) — غیرهمزمان چون تصویر ساخته و بارگذاری می‌شود */
  mergeDown: (id: string) => Promise<string | null>;
  /** جابه‌جایی در پشته: index = جایگاهِ تازه در آرایهٔ layers (۰ = پایین‌ترین) */
  reorder: (id: string, index: number) => void;
  /** ساختنِ ماسک: reveal = سفیدِ کامل (همه دیده می‌شود)، hide = سیاهِ کامل (با قلم باز می‌شود)، linear/radial = شیب */
  addMask: (id: string, kind: MaskKind) => void;
  removeMask: (id: string) => void;
  /** ماسک ⇐ انتخاب (selection) و برعکس */
  maskFromSelection: (id: string) => void;
  /** رفتن به ابزارِ قلم برای نقاشی روی ماسکِ این لایه */
  paintMask: (id: string) => void;
  /** شروعِ ویرایشِ متن روی بوم (فوکوس روی textarea بازرس) */
  focusText: () => void;
  // ── گروه‌ها و برش (درخت: `parent` + فهرستِ تخت؛ نگاه کنید به tree.ts)
  /** گروهِ خالیِ تازه، بالای لایهٔ فعال و هم‌سطحش */
  newGroup: () => void;
  /** لایه را در یک گروهِ تازه می‌پیچد (گروه جای لایه را می‌گیرد) ⇒ شناسهٔ گروه یا null */
  group: (id: string) => string | null;
  /** گروه را باز می‌کند: فرزندان به والدِ گروه می‌روند و خودِ گروه (با ماسکش) برداشته می‌شود */
  ungroup: (id: string) => void;
  /** انتقالِ لایه به والدِ تازه (null = سطحِ بالا)؛ index = جایگاه میانِ هم‌خواهرها (پایین = ۰، پس از برداشتنِ خودش) */
  moveLayer: (id: string, parent: string | null, index: number) => void;
  /** یک پله بالاتر (+۱) یا پایین‌تر (−۱) میانِ هم‌خواهرها */
  moveSibling: (id: string, dir: 1 | -1) => void;
  /** «برش به لایهٔ زیرین» روشن/خاموش */
  toggleClip: (id: string) => void;
  /** بسته/بازِ پوشه (فقط نما؛ در تاریخچه نمی‌رود) */
  setCollapsed: (id: string, v: boolean) => void;
};

export type LayersPanelProps = {
  state: ProState;
  hist: Hist;
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  actions: ProActions;
  assets: Asset[];
  storeLogo: string | null;
  fonts: FontInfo[];
  kit: Kit;
  /** ابعادِ واقعیِ لایه روی بوم به‌صورتِ کسری از پهنا (برای نمایش)؛ ممکن است null باشد */
  layerBox?: (id: string) => { w: number; h: number } | null;
};

export type PresetsPanelProps = {
  storeId: string;
  state: ProState;
  hist: Hist;
  kit: Kit;
  assets: Asset[];
  currentAssetId: number;
  /** کوچک‌نمای عکسِ فعلی با تنظیم‌های داده‌شده (data URL)، یا null اگر هنوز آماده نیست. `thumbVersion` با آماده‌شدنِ موتور عوض می‌شود. */
  makeThumb: (recipe: { adjust: Record<string, number>; curve: Record<string, [number, number][]> }, size: number) => string | null;
  thumbVersion: number;
  nodeOn: boolean;
  /** پس از «اعمال روی چند عکس» */
  onBatch: (res: { batch: string; count: number }) => void;
  /** فیلترِ کیت را روی حالت اعمال کن (همان applyPreset ِ ویرایشگر) */
  applyKitPreset: (key: string) => void;
};

export type { Asset, FontInfo, Kit, Layer, MaskSpec, NodeStatus, Preset, ProState };
