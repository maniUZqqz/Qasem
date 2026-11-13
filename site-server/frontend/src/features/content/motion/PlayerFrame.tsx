import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react";

import { Spinner } from "../../../components/ui";
import { PLAYER_URL } from "./api";

export type PlayerMeta = { width: number; height: number; fps: number; durationInFrames: number };
export type PlayerMessage =
  | { type: "template"; spec: unknown }
  | { type: "code"; code: string };

export type PlayerHandle = { send: (m: PlayerMessage) => void };

/**
 * پیش‌نمایشِ زندهٔ ویدیو (Remotion Player) داخلِ یک iframe ِ سندباکس: بدونِ دسترسی به کوکی/حافظه/شبکه
 * (sandbox="allow-scripts" و CSP ِ سخت‌گیرانه از سمتِ سایت). با postMessage حرف می‌زنیم؛
 * کدِ کاربر هم همان‌جا کامپایل و اجرا می‌شود — هرگز در صفحهٔ پنل.
 */
const PlayerFrame = forwardRef<
  PlayerHandle,
  { onMeta?: (m: PlayerMeta) => void; onError?: (message: string, line?: number) => void; aspect?: number; maxHeight?: number }
>(function PlayerFrame({ onMeta, onError, aspect = 9 / 16, maxHeight = 640 }, ref) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const pending = useRef<PlayerMessage | null>(null);
  const [meta, setMeta] = useState<PlayerMeta | null>(null);

  const post = (m: PlayerMessage) => {
    const w = frame.current?.contentWindow;
    if (!w) return;
    w.postMessage(m.type === "template" ? { type: "nm-template", spec: m.spec } : { type: "nm-code", code: m.code }, "*");
  };

  useImperativeHandle(ref, () => ({
    send: (m) => {
      if (ready) post(m);
      else pending.current = m;
    },
  }));

  useEffect(() => {
    const onMsg = (ev: MessageEvent) => {
      if (ev.source !== frame.current?.contentWindow) return;
      const d = ev.data as { type?: string; [k: string]: unknown };
      if (!d || typeof d.type !== "string") return;
      if (d.type === "nm-ready") {
        setReady(true);
        if (pending.current) {
          post(pending.current);
          pending.current = null;
        }
      } else if (d.type === "nm-meta") {
        const m = d as unknown as PlayerMeta;
        setMeta(m);
        onMeta?.(m);
      } else if (d.type === "nm-error") {
        onError?.(String(d.message || ""), typeof d.line === "number" ? d.line : undefined);
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onMeta, onError]);

  const ratio = meta ? meta.width / meta.height : aspect;
  return (
    <div className="relative mx-auto overflow-hidden rounded-xl" style={{ background: "#000", aspectRatio: String(ratio), maxHeight, maxWidth: "100%", width: maxHeight * ratio, border: "1px solid var(--line)" }}>
      {!ready && (
        <div className="absolute inset-0 flex items-center justify-center" style={{ color: "var(--text-3)" }}>
          <Spinner />
        </div>
      )}
      <iframe
        ref={frame}
        title="پیش‌نمایشِ ویدیو"
        src={PLAYER_URL}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        className="absolute inset-0 h-full w-full border-0"
        style={{ direction: "ltr" }}
      />
    </div>
  );
});

export default PlayerFrame;
