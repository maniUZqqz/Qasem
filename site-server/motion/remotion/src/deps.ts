// What a code-mode composition may `import`. Anything else is refused (by the site's scanner and again here at run time).
import * as React from "react";
import * as ReactJSX from "react/jsx-runtime";
import * as Remotion from "remotion";
import * as Shapes from "@remotion/shapes";
import * as Paths from "@remotion/paths";
import * as Noise from "@remotion/noise";
import * as NM from "./nm-api";

export const DEPS: { [k: string]: any } = {
  react: React,
  "react/jsx-runtime": ReactJSX,
  remotion: Remotion,
  "@remotion/shapes": Shapes,
  "@remotion/paths": Paths,
  "@remotion/noise": Noise,
  "nm-motion": NM,
};

export function allowedImports(): string[] {
  return Object.keys(DEPS);
}
