// The small public API that code-mode compositions can import:  import { StyleProvider, T, Card, Background, getStyle } from "nm-motion";
import React from "react";
import { useVideoConfig } from "remotion";
import { Background } from "./bg";
import { Decor } from "./decor";
import { CtxC, buildCtx, fontKeysOf, useCtx, useFonts } from "./ctx";
import { Card, SvgDefs, T } from "./text";
import { Textures } from "./tex";
import { STYLES, getStyle } from "./Template";
import { col, mix, rgba, shade } from "./util";

/** wrap a composition in one of the catalog styles: fonts, palette, filters; children can use T / Card / Background */
export const StyleProvider: React.FC<{ style: string; lang?: "fa" | "en"; children?: React.ReactNode }> = ({ style, lang = "fa", children }) => {
  const { width, height, fps, durationInFrames } = useVideoConfig();
  const st = getStyle(style);
  useFonts(fontKeysOf(st));
  const base = buildCtx(st, { style: st.id, aspect: "9:16", scenes: [], lang }, width, height, fps);
  const ctx = { ...base, scene: { index: 0, frames: durationInFrames, count: 1 } };
  return (
    <CtxC.Provider value={ctx}>
      <SvgDefs />
      {children}
    </CtxC.Provider>
  );
};

/** background + decoration of a style, ready to sit behind your own content */
export const StyleBackdrop: React.FC<{ variant?: number }> = ({ variant = 0 }) => {
  const { style } = useCtx();
  return (
    <>
      <Background spec={variant % 2 && style.bg2 ? style.bg2 : style.bg} variant={variant} />
      <Decor layers={style.decor} />
    </>
  );
};

export const StyleTextures: React.FC = () => <Textures layers={useCtx().style.tex} />;

export { Background, Card, T, STYLES, getStyle, useCtx, col, mix, rgba, shade };
