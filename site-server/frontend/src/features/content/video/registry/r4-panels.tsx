import EditorSettingsCard from "../director/EditorSettings";
import GotoPanel from "./r4-goto";
import KeyframeGraph from "./r4-graph";
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
];
