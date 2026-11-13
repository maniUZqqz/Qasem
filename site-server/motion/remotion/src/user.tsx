// Code mode: the user's composition (compiled to CommonJS by the site / the panel) is loaded here and run inside the page.
import React from "react";
import { DEPS } from "./deps";
import { useFonts } from "./ctx";

type UserMod = { Component: React.ComponentType<any>; config: { [k: string]: any } };
let CACHED: UserMod | null = null;

/** The user's code runs in a page that may talk to nothing but its own origin. Called once, before the user's code. */
export function lockdown(): void {
  const g = globalThis as any;
  if (g.__NM_LOCKED) return;
  g.__NM_LOCKED = true;
  const origin = String(g.location?.origin || "");
  const same = (u: string) => {
    try {
      const url = new URL(u, g.location?.href);
      return url.origin === origin || url.protocol === "data:" || url.protocol === "blob:";
    } catch {
      return false;
    }
  };
  const nope = (what: string) => () => {
    throw new Error(`nm-motion: ${what} is not allowed in code mode`);
  };
  if (typeof g.fetch === "function") {
    const orig = g.fetch.bind(g);
    g.fetch = (input: any, init?: any) => {
      const url = typeof input === "string" ? input : input?.url ?? String(input);
      if (!same(url)) return Promise.reject(new Error("nm-motion: network access is not allowed in code mode"));
      return orig(input, init);
    };
  }
  if (g.XMLHttpRequest) {
    const open = g.XMLHttpRequest.prototype.open;
    g.XMLHttpRequest.prototype.open = function (m: string, url: string, ...rest: any[]) {
      if (!same(String(url))) throw new Error("nm-motion: network access is not allowed in code mode");
      return open.call(this, m, url, ...rest);
    };
  }
  for (const k of ["WebSocket", "EventSource", "Worker", "SharedWorker", "RTCPeerConnection"]) {
    try { g[k] = nope(k); } catch { /* read-only: the CSP still blocks it */ }
  }
  try { g.navigator.sendBeacon = nope("sendBeacon"); } catch { /* ignore */ }
  try { g.open = nope("window.open"); } catch { /* ignore */ }
  try { g.importScripts = nope("importScripts"); } catch { /* ignore */ }
}

export function compileInto(factory: any): UserMod {
  lockdown();
  const mod: { exports: any } = { exports: {} };
  const req = (name: string) => {
    if (!(name in DEPS)) throw new Error(`nm-motion: module "${name}" is not allowed (allowed: ${Object.keys(DEPS).join(", ")})`);
    return DEPS[name];
  };
  factory(req, mod.exports, mod);
  const ex = mod.exports;
  const Component = ex.default ?? ex.Video ?? ex.Composition ?? ex.MyVideo;
  if (typeof Component !== "function") throw new Error("nm-motion: the code must `export default` a React component");
  return { Component, config: ex.config ?? ex.compositionConfig ?? {} };
}

export function loadUser(): UserMod {
  if (CACHED) return CACHED;
  const factory = (globalThis as any).__NM_USER_FACTORY;
  if (typeof factory !== "function") throw new Error("nm-motion: no user code was loaded into this page");
  CACHED = compileInto(factory);
  return CACHED;
}

const clampN = (v: any, a: number, b: number, d: number): number => {
  const n = Math.round(Number(v));
  return Number.isFinite(n) ? Math.max(a, Math.min(b, n)) : d;
};

export function normalizeConfig(config: { [k: string]: any }, maxSeconds = 60) {
  const fps = clampN(config.fps, 10, 60, 30);
  return {
    width: clampN(config.width, 128, 3840, 1080),
    height: clampN(config.height, 128, 3840, 1920),
    fps,
    durationInFrames: clampN(config.durationInFrames, 1, maxSeconds * fps, 5 * fps),
  };
}

export function userMetadata(maxSeconds = 60) {
  return normalizeConfig(loadUser().config, maxSeconds);
}

export const userFonts = (config: { [k: string]: any }): string[] => {
  const keys = Array.isArray(config.fonts) ? config.fonts.filter((k: any) => typeof k === "string").slice(0, 8) : [];
  return Array.from(new Set(["vazirmatn", ...keys]));
};

export const UserLoader: React.FC<{ props?: any }> = ({ props }) => {
  const { Component, config } = loadUser();
  useFonts(userFonts(config));
  return <Component {...(config.defaultProps || {})} {...(props || {})} />;
};
