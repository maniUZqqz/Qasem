// The timeline of a plan: frames of every scene, the overlaps of the transitions (one per JOIN), the start of every scene and the total.
// PURE (no React / Remotion imports) so the backend test can run it in plain node and compare it with backend/apps/motion/timeline.py.
import type { Spec, StyleDef } from "./types";

export type Timeline = { frames: number[]; starts: number[]; tfs: number[]; kinds: string[]; total: number; kind: string; tf: number };

export function computeTimeline(spec: Spec, style: { trans: { kind: string; frames: number } }, fps: number): Timeline {
  const scenes = spec.scenes || [];
  const frames = scenes.map((s) => Math.max(fps, Math.round(Math.max(1, Math.min(60, Number(s.duration) || 4)) * fps)));
  const tfs: number[] = [];
  const kinds: string[] = [];
  for (let j = 0; j < frames.length - 1; j++) {
    const kind = (scenes[j].transition as string) || spec.transition || style.trans.kind;
    const cap = Math.floor(Math.min(frames[j], frames[j + 1]) * 0.45);
    tfs.push(kind === "cut" ? 0 : Math.max(0, Math.min(style.trans.frames, cap)));
    kinds.push(kind);
  }
  const starts: number[] = [];
  let at = 0;
  frames.forEach((f, i) => {
    starts.push(at);
    at += f - (i < frames.length - 1 ? tfs[i] : 0);
  });
  return { frames, starts, tfs, kinds, total: Math.max(1, at), kind: spec.transition || style.trans.kind, tf: tfs.length ? Math.max(...tfs) : 0 };
}

export type { StyleDef };
