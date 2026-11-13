// The in-panel live preview. Served by the site at /api/v1/motion/player/ and shown in a sandboxed <iframe> (no same-origin, no network:
// the page has a strict Content-Security-Policy). The panel talks to it with postMessage:
//
//   panel -> player   {type:"nm-template", spec}              preview a template/AI composition (spec with data: URI assets)
//                     {type:"nm-code", code}                  compile (sucrase) + preview the user's TSX
//                     {type:"nm-seek", frame} {type:"nm-play"} {type:"nm-pause"}
//   player -> panel   {type:"nm-ready"} {type:"nm-meta", width,height,fps,durationInFrames} {type:"nm-error", message, line?}
//                     {type:"nm-frame", frame}
import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Player } from "@remotion/player";
import type { PlayerRef } from "@remotion/player";
import { transform } from "sucrase";
import { Template, calcMetadata } from "../Template";
import { compileInto, normalizeConfig, userFonts } from "../user";
import { useFonts } from "../ctx";
import type { Spec } from "../types";

type View =
  | { kind: "template"; spec: Spec }
  | { kind: "code"; Component: React.ComponentType<any>; config: { [k: string]: any } }
  | null;

const post = (m: any) => {
  try {
    window.parent.postMessage(m, "*");
  } catch {
    /* no parent */
  }
};

class Boundary extends React.Component<{ children: React.ReactNode; resetKey: any }, { err: string | null }> {
  state = { err: null as string | null };
  static getDerivedStateFromError(e: any) {
    return { err: String(e && e.message ? e.message : e) };
  }
  componentDidCatch(e: any) {
    post({ type: "nm-error", message: String(e && e.message ? e.message : e) });
  }
  componentDidUpdate(prev: any) {
    if (prev.resetKey !== this.props.resetKey && this.state.err) this.setState({ err: null });
  }
  render() {
    if (this.state.err) return <div style={{ padding: 16, color: "#ff8a8a", fontFamily: "monospace", direction: "ltr", fontSize: 14, whiteSpace: "pre-wrap" }}>{this.state.err}</div>;
    return this.props.children;
  }
}

const UserWrap: React.FC<{ Component: React.ComponentType<any>; config: { [k: string]: any } }> = ({ Component, config }) => {
  useFonts(userFonts(config));
  return <Component {...(config.defaultProps || {})} />;
};
const TemplateWrap: React.FC<{ spec: Spec }> = ({ spec }) => <Template spec={spec} />;

function compileUser(code: string) {
  let js: string;
  try {
    js = transform(code, { transforms: ["typescript", "jsx", "imports"], jsxRuntime: "automatic", production: true }).code;
  } catch (e: any) {
    const m = String(e && e.message ? e.message : e);
    const line = (m.match(/\((\d+):(\d+)\)/) || [])[1];
    throw Object.assign(new Error(m), { line: line ? Number(line) : undefined });
  }
  // an inline script (allowed by the page's CSP) defines the factory; no eval / new Function needed
  const g = window as any;
  g.__NM_PLAYER_FACTORY = undefined;
  const el = document.createElement("script");
  el.text = `window.__NM_PLAYER_FACTORY=function(require,exports,module){"use strict";\n${js}\n};`;
  document.head.appendChild(el);
  el.remove();
  if (typeof g.__NM_PLAYER_FACTORY !== "function") throw new Error("compile failed");
  return compileInto(g.__NM_PLAYER_FACTORY);
}

const App: React.FC = () => {
  const [view, setView] = useState<View>(null);
  const [n, setN] = useState(0);
  const ref = useRef<PlayerRef>(null);

  useEffect(() => {
    const onMsg = (ev: MessageEvent) => {
      const m = ev.data;
      if (!m || typeof m !== "object" || typeof m.type !== "string") return;
      try {
        if (m.type === "nm-template") {
          const meta = calcMetadata(m.spec);
          setView({ kind: "template", spec: m.spec });
          setN((x) => x + 1);
          post({ type: "nm-meta", ...meta });
        } else if (m.type === "nm-code") {
          const mod = compileUser(String(m.code || ""));
          const cfg = normalizeConfig(mod.config, 60);
          setView({ kind: "code", Component: mod.Component, config: mod.config });
          setN((x) => x + 1);
          post({ type: "nm-meta", ...cfg });
        } else if (m.type === "nm-seek") {
          ref.current?.seekTo(Math.max(0, Number(m.frame) || 0));
        } else if (m.type === "nm-play") {
          ref.current?.play();
        } else if (m.type === "nm-pause") {
          ref.current?.pause();
        }
      } catch (e: any) {
        post({ type: "nm-error", message: String(e && e.message ? e.message : e), line: e && e.line });
      }
    };
    window.addEventListener("message", onMsg);
    post({ type: "nm-ready" });
    return () => window.removeEventListener("message", onMsg);
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      const f = ref.current?.getCurrentFrame();
      if (typeof f === "number") post({ type: "nm-frame", frame: f });
    }, 250);
    return () => window.clearInterval(id);
  }, []);

  if (!view) return <div style={{ color: "#94a3b8", font: "14px sans-serif", display: "flex", height: "100%", alignItems: "center", justifyContent: "center" }}>…</div>;
  let meta: { width: number; height: number; fps: number; durationInFrames: number };
  let comp: React.ComponentType<any>;
  let props: any;
  if (view.kind === "template") {
    meta = calcMetadata(view.spec);
    comp = TemplateWrap;
    props = { spec: view.spec };
  } else {
    meta = normalizeConfig(view.config, 60);
    comp = UserWrap;
    props = { Component: view.Component, config: view.config };
  }
  return (
    <Boundary resetKey={n}>
      <Player
        key={n}
        ref={ref}
        component={comp as any}
        inputProps={props}
        durationInFrames={meta.durationInFrames}
        compositionWidth={meta.width}
        compositionHeight={meta.height}
        fps={meta.fps}
        controls
        loop
        autoPlay
        clickToPlay
        spaceKeyToPlayOrPause={false}
        numberOfSharedAudioTags={0}
        acknowledgeRemotionLicense
        style={{ width: "100%", height: "100%", background: "#000" }}
      />
    </Boundary>
  );
};

createRoot(document.getElementById("root")!).render(<App />);
