import type { ComponentType } from "react";

import type { Bin, MediaItem } from "../api";
import type { InspectorTab } from "../manual/Inspector";
import type { AnyClip, Project, Track } from "../manual/model";
import type { Tool } from "../manual/TimelineView";

/**
 * «ثبتِ ویژگی‌ها» (feature registry): یک فهرستِ واحد از همهٔ کارهایی که ادیتور می‌تواند، که هم منوی کامل، هم جستجوی ابزار (Ctrl+K)
 * و هم ویرایشگرِ میان‌برها را می‌سازد. هر ویژگیِ تازه فقط یک ورودی اینجا می‌خواهد و خودکار همه‌جا دیده می‌شود.
 *
 * قاعده: فقط ویژگی‌ای ثبت شود که واقعاً کار می‌کند. «به‌زودی» و دکمهٔ مرده ممنوع است (آزمونِ خودکار هر `run` را اجرا می‌کند).
 */

export type MenuId = "file" | "edit" | "clip" | "sequence" | "marker" | "graphics" | "color" | "audio" | "view" | "window" | "help";

/** منوها به ترتیبِ نمایش */
export const MENUS: { id: MenuId; title: string }[] = [
  { id: "file", title: "پرونده" },
  { id: "edit", title: "ویرایش" },
  { id: "clip", title: "کلیپ" },
  { id: "sequence", title: "سکانس" },
  { id: "marker", title: "نشانگر" },
  { id: "graphics", title: "گرافیک" },
  { id: "color", title: "رنگ" },
  { id: "audio", title: "صدا" },
  { id: "view", title: "نما" },
  { id: "window", title: "پنجره" },
  { id: "help", title: "راهنما" },
];

/** کلیدهای روشن/خاموشِ نما */
export type FlagName = "snap" | "scopes" | "volLine" | "autoRipple" | "crop" | "menubar";

/** آنچه ویژگی‌ها از فضای کار می‌خواهند. VideoWorkspace همین را می‌سازد؛ پنل‌ها هم همین را می‌گیرند. */
export type WorkspaceApi = {
  // ───────── خواندنی (عکسِ لحظه‌ای)
  storeId: string;
  /** نمای فعلی (اگر توالیِ تودرتو باز باشد همان توالی) */
  project: Project;
  /** ریشهٔ پروژه */
  root: Project;
  /** توالی‌های بازشده از ریشه */
  path: string[];
  selection: string[];
  selected: { track: Track; clip: AnyClip } | null;
  time: number;
  playing: boolean;
  fps: number;
  projectId: number | null;
  media: Record<string, MediaItem>;
  bin: Bin | null;
  tool: Tool;
  flags: Record<FlagName, boolean>;
  canUndo: boolean;
  canRedo: boolean;
  history: { entries: { label: string }[]; index: number };
  /** آیا پروژه قطعه‌ای دارد */
  hasClips: boolean;

  // ───────── ویرایش (همه با گامِ برگشت)
  /** یک کارِ یک‌باره = یک گامِ برگشت */
  apply: (label: string, fn: (p: Project) => Project) => void;
  /** مثلِ apply ولی روی ریشه (مستر، ردیاب‌ها…) */
  applyRoot: (label: string, fn: (p: Project) => Project) => void;
  /** هنگامِ کشیدن؛ فقط پیش‌نمایش، تا `end` */
  live: (fn: (p: Project) => Project) => void;
  end: (label: string) => void;
  select: (ids: string[]) => void;
  undo: () => void;
  redo: () => void;
  /** پرش به یک گام از تاریخچه */
  jumpHistory: (index: number) => void;

  // ───────── پخش و نما
  seek: (t: number) => void;
  togglePlay: () => void;
  /** n فریم جلو (منفی = عقب) */
  step: (frames: number) => void;
  setRate: (rate: number) => void;
  setTool: (t: Tool) => void;
  toggle: (flag: FlagName) => void;
  /** ضریبِ بزرگ‌نمایی، یا "fit" = جا شدنِ کلِ پروژه */
  zoom: (factor: number | "fit") => void;

  // ───────── رابط
  setTab: (tab: InspectorTab) => void;
  /** تب را باز می‌کند و (اگر داده شود) یک بخشِ تاشو را در آن باز می‌کند */
  reveal: (tab: InspectorTab, section?: string) => void;
  /** یک دکمهٔ موجود (با data-testid) را می‌زند؛ اگر `tab` بدهید اول آن تب باز می‌شود و تا ۲ ثانیه منتظر می‌ماند */
  click: (testId: string, tab?: InspectorTab) => void;
  notice: (message: string) => void;
  openPanel: (id: string, props?: Record<string, unknown>) => void;
  closePanel: () => void;
  activePanel: string | null;
  openSearch: () => void;

  // ───────── کارهای نام‌دارِ فضای کار (حالتِ پیش‌فرض‌هایی که وضعیتِ React می‌خواهند)
  op: {
    /** تقسیم در سرِ پخش؛ روی انتخاب‌ها یا (بی‌انتخاب) همهٔ ترک‌ها */
    split: () => void;
    remove: (ripple: boolean) => void;
    /** جابه‌جاییِ قطعه‌های انتخاب‌شده n فریم */
    nudge: (frames: number) => void;
    trimToPlayhead: (side: "l" | "r") => void;
    copy: () => void;
    paste: () => void;
    jl: (kind: "J" | "L") => void;
    newText: () => void;
    render: (quality: "draft" | "final") => void;
    openProject: (id: number | null) => void;
    exactPreview: () => void;
    deleteProject: () => void;
    beats: () => void;
    nest: () => void;
    closeSequence: () => void;
    uploadVideo: () => void;
    /** کپی/چسباندنِ ویژگی‌ها (رنگ، افکت، صدا…) میانِ قطعه‌ها */
    copyAttrs: () => void;
    pasteAttrs: () => void;
    /** ساختِ پیش‌نمایشِ سبک (پروکسی) برای قطعهٔ انتخاب‌شده */
    proxy: () => void;
    /** سرِ پخش به لبه/نشانگرِ قبلی (-1) یا بعدی (+1) می‌پرد */
    gotoEdit: (dir: -1 | 1) => void;
    /** چینشِ کار: نمایشِ تب و اسکوپ و خطِ بلندی برای یک کارِ خاص */
    workspace: (name: "edit" | "color" | "audio" | "graphics" | "export") => void;
  };
  /** رفتن به حالتِ «نیمه‌خودکار» (کارگردان)؛ null = از این صفحه ممکن نیست */
  goDirector: (() => void) | null;
};

export type FeatureDef = {
  /** شناسهٔ پایدار («clip.split»)؛ ذخیرهٔ میان‌بر و «اخیراً» با همین است */
  id: string;
  menu: MenuId;
  /** زیرگروهِ فارسی در منو؛ ورودی‌های هم‌گروه کنار هم و با خطِ جداکننده می‌آیند */
  group: string;
  /** نامِ فارسی */
  title: string;
  /** نامِ انگلیسی (برای جستجو؛ در رابط نشان داده نمی‌شود) */
  en?: string;
  /** مترادف‌ها (فارسی و انگلیسی) برای جستجو */
  words?: string[];
  /** راهنمای کوتاهِ فارسی (tooltip)؛ یک جمله */
  tip: string;
  /** میان‌برِ پیش‌فرض: «Ctrl+Z»، «S»، «Shift+Delete»، «,» … */
  keys?: string;
  /** این میان‌برِ پیش‌فرض را خودِ فضای کار از قبل جواب می‌دهد (کدِ قدیمی)؛ ثبت فقط برای نمایش و تغییرِ میان‌بر است */
  legacy?: boolean;
  /** میان‌بر حتی وقتی نشانگر در یک کادرِ نوشتن است کار کند (مثلاً Ctrl+K) */
  inInputs?: boolean;
  /** null = در دسترس؛ وگرنه دلیلِ فارسیِ غیرفعال‌بودن */
  when?: (a: WorkspaceApi) => string | null;
  /** برای کلیدهای روشن/خاموش: وضعیتِ فعلی (✓ در منو) */
  on?: (a: WorkspaceApi) => boolean;
  run: (a: WorkspaceApi) => void | Promise<void>;
};

export type PanelProps = { api: WorkspaceApi; props?: Record<string, unknown>; onClose: () => void };

/** پنجرهٔ شناورِ ناقفل (مثلِ مانیتورِ منبع، نشانگرها، تاریخچه) که یک ویژگی با `api.openPanel(id)` باز می‌کند */
export type PanelDef = {
  id: string;
  title: string;
  size?: "sm" | "md" | "lg";
  Component: ComponentType<PanelProps>;
};

// ───────── کمک‌های کوچک برای شرط‌های رایج
export const needClip = (a: WorkspaceApi): string | null => (a.selected ? null : "اول یک قطعه را روی تایم‌لاین انتخاب کنید");
export const needMedia = (a: WorkspaceApi): string | null =>
  a.selected && a.selected.clip.type === "media" ? null : "اول یک ویدیو، عکس یا صدا را روی تایم‌لاین انتخاب کنید";
export const needVisual = (a: WorkspaceApi): string | null =>
  a.selected && a.selected.clip.type === "media" && a.selected.track.kind === "video" ? null : "اول یک ویدیو یا عکس را روی تایم‌لاین انتخاب کنید";
export const needVideo = (a: WorkspaceApi): string | null =>
  a.selected && a.selected.clip.type === "media" && a.selected.clip.kind === "video" ? null : "اول یک ویدیو را روی تایم‌لاین انتخاب کنید";
export const needText = (a: WorkspaceApi): string | null =>
  a.selected && a.selected.clip.type === "text" ? null : "اول یک متن را روی تایم‌لاین انتخاب کنید";
export const needSelection = (a: WorkspaceApi): string | null => (a.selection.length ? null : "اول چیزی را روی تایم‌لاین انتخاب کنید");
export const needClips = (a: WorkspaceApi): string | null => (a.hasClips ? null : "پروژه هنوز قطعه‌ای ندارد");
