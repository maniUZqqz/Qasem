import { NEW_PANELS } from "./new-panels";
import { CORE_PANELS } from "./panels";
import type { PanelDef } from "./types";

export { ALL_FEATURES, FEATURE_BY_ID } from "./features";
export { buildKeymap, comboOf, latinKey, normalizeCombo, prettyCombo, typingTarget } from "./keymap";
export type { Keymap } from "./keymap";
export { isKeyCapture, useKeymap } from "./keystore";
export { loadRecent, pushRecent, searchFeatures } from "./search";
export { MENUS } from "./types";
export type { FeatureDef, MenuId, PanelDef, WorkspaceApi } from "./types";

export const ALL_PANELS: PanelDef[] = [...CORE_PANELS, ...NEW_PANELS];
