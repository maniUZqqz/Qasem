import EditorSettingsCard from "../director/EditorSettings";
import GotoPanel from "./r4-goto";
import KeyframeGraph from "./r4-graph";
import { ColorMatchPanel, HueVsPanel } from "./r5-color";
import { ClipFxPanel } from "./r5-fxpanel";
import { DefaultTransitionPanel, MediaMetaPanel, OfflinePanel, TextMotionPanel } from "./r6-panels";
import { OutputQueuePanel } from "./r5-queuepanel";
import { TranslatePanel } from "./r5-translatepanel";
import { MotionPathPanel, TranscriptPanel } from "./r5-panels";
import MarkersPanel from "./r4-markers";
import ReplacePanel from "./r4-replace";
import SourcePanel from "./r4-source";
import type { PanelDef, PanelProps } from "./types";

function SettingsPanel({ api }: PanelProps) {
  return <EditorSettingsCard storeId={api.storeId} onChange={() => window.dispatchEvent(new CustomEvent("nm-editor-settings-changed"))} />;
}

/** پنجره‌های شناورِ دورِ چهارم */
export const R4_PANELS: PanelDef[] = [
  { id: "editor-settings", title: "تنظیماتِ ویرایشگر", size: "md", Component: SettingsPanel },
  { id: "source", title: "مانیتورِ منبع", size: "md", Component: SourcePanel },
  { id: "markers", title: "نشانگرها", size: "md", Component: MarkersPanel },
  { id: "goto", title: "رفتن به زمانِ دقیق", size: "sm", Component: GotoPanel },
  { id: "graph", title: "گرافِ کلیدفریم", size: "md", Component: KeyframeGraph },
  { id: "replace", title: "جایگزینیِ فیلم", size: "sm", Component: ReplacePanel },
  { id: "color-match", title: "تطبیقِ رنگِ دو نما", size: "sm", Component: ColorMatchPanel },
  { id: "huevs", title: "منحنی‌های Hue-vs", size: "md", Component: HueVsPanel },
  { id: "transcript", title: "ویرایش با متنِ گفتار", size: "md", Component: TranscriptPanel },
  { id: "motionpath", title: "مسیرِ حرکت", size: "md", Component: MotionPathPanel },
  { id: "mediameta", title: "برچسب و یادداشتِ رسانه‌ها", size: "md", Component: MediaMetaPanel },
  { id: "offline", title: "رسانه‌های گم‌شده", size: "md", Component: OfflinePanel },
  { id: "deftrans", title: "گذارِ پیش‌فرض برای همهٔ برش‌ها", size: "sm", Component: DefaultTransitionPanel },
  { id: "textmotion", title: "حرکتِ متن (تیتراژ، نوارِ خبر، قوس، موج)", size: "sm", Component: TextMotionPanel },
  { id: "translate", title: "ترجمهٔ زیرنویس", size: "md", Component: TranslatePanel },
  { id: "outqueue", title: "چند خروجی یک‌جا (صفِ رندر)", size: "md", Component: OutputQueuePanel },
  { id: "clipfx", title: "کلیدِ روشنایی، لنز و نقطهٔ لنگر", size: "md", Component: ClipFxPanel },
];
