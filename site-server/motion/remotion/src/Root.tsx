import React from "react";
import { Composition } from "remotion";
import { Template, calcMetadata } from "./Template";
import { UserLoader, userMetadata } from "./user";
import type { Spec } from "./types";

const DEFAULT_SPEC: Spec = {
  style: "flat-vector", aspect: "9:16", fps: 30, lang: "fa",
  scenes: [{ type: "title", duration: 3, title: "سلام", subtitle: "استودیوی موشن" }],
};

export const Root: React.FC = () => (
  <>
    <Composition
      id="Template"
      component={Template as any}
      durationInFrames={90}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{ spec: DEFAULT_SPEC }}
      calculateMetadata={({ props }: any) => calcMetadata(props.spec as Spec)}
    />
    <Composition
      id="User"
      component={UserLoader as any}
      durationInFrames={150}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{ props: {} }}
      calculateMetadata={() => userMetadata(Number((globalThis as any).__NM_MAX_SECONDS) || 60)}
    />
  </>
);
