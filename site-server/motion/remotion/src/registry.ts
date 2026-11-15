// The component registry: the 9 classic scene types + the component library. A test (backend/apps/motion/tests_lib.py) keeps this list identical to
// backend/apps/motion/components.py - one id on one side and not the other fails the build.
import type React from "react";
import { DATA_COMPONENTS } from "./comp-data";
import { OVERLAY_BODIES, TEXT_COMPONENTS } from "./comp-text";
import { SCENES } from "./scenes";
import type { Scene } from "./types";

export type SceneComponent = React.FC<{ sc: Scene }>;

export const COMPONENTS: { [id: string]: SceneComponent } = {
  ...SCENES,
  ...DATA_COMPONENTS,
  ...TEXT_COMPONENTS,
};

/** components that can also be laid over another scene (placed by anchor inside the safe area) */
export const OVERLAYS: { [id: string]: SceneComponent } = OVERLAY_BODIES;
