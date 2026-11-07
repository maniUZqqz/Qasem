import { useEffect, useMemo, useRef, useState } from "react";

import { CHANNELS, ChannelId, channelCanvas } from "../channels";
import "./effects.css";

/** «کانال‌ها»: پنج نمای خاکستری از ترکیبِ فعلی؛ هرکدام را می‌شود به‌عنوانِ انتخاب بارگذاری کرد (نوبت ۷). */
export default function ChannelsDialog({ getSource, onLoad, onClose }: {
  getSource: () => Promise<{ data: Uint8ClampedArray; w: number; h: number }>;
  onLoad: (ch: ChannelId, invert: boolean, mode: "new" | "add" | "sub", src: { data: Uint8ClampedArray; w: number; h: number }) => void;
  onClose: () => void;
}) {
  const [src, setSrc] = useState<{ data: Uint8ClampedArray; w: number; h: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pick, setPick] = useState<ChannelId>("l");
  const [invert, setInvert] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let live = true;
    getSource().then((s) => live && setSrc(s)).catch((e) => live && setErr(e instanceof Error ? e.message : "تصویر آماده نشد."));
    root.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      live = false;
      window.removeEventListener("keydown", onKey, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const thumbs = useMemo(() => {
    if (!src) return null;
    const k = 150 / Math.max(src.w, src.h);
    const tw = Math.max(1, Math.round(src.w * k));
    const th = Math.max(1, Math.round(src.h * k));
    // کوچک‌سازیِ بی‌افت نیازی نیست؛ پیکسل‌ها را می‌خوانیم و کانال را روی بومِ کوچک می‌کشیم
    const small = document.createElement("canvas");
    small.width = tw;
    small.height = th;
    const full = document.createElement("canvas");
    full.width = src.w;
    full.height = src.h;
    full.getContext("2d")!.putImageData(new ImageData(new Uint8ClampedArray(src.data), src.w, src.h), 0, 0);
    const sx = small.getContext("2d", { willReadFrequently: true })!;
    sx.drawImage(full, 0, 0, tw, th);
    const d = sx.getImageData(0, 0, tw, th).data;
    return CHANNELS.map((c) => ({ ch: c, url: channelCanvas(d, tw, th, c.id, invert).toDataURL("image/png") }));
  }, [src, invert]);
  return (
    <div className="fx-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()} data-testid="channels-dialog">
      <div className="fx-dialog" style={{ width: "min(560px, 100%)", maxHeight: "none" }} role="dialog" aria-modal="true" aria-label="کانال‌ها" tabIndex={-1} ref={root} dir="rtl">
        <div className="fx-head"><b>کانال‌ها</b><button type="button" className="fx-x" onClick={onClose} aria-label="بستن">✕</button></div>
        <div className="fx-form" style={{ padding: 14 }}>
          <p className="fx-note">هر کانال را به‌صورتِ سیاه‌وسفید ببینید (روشن‌تر = بیشتر). یک کانال را انتخاب کنید و «بارگذاری به‌عنوان انتخاب» را بزنید؛ نقطه‌های روشن‌ترِ آن کانال انتخاب می‌شوند (نرم، با درجهٔ خاکستری).</p>
          {err && <p role="alert" className="fx-note">{err}</p>}
          {!src && !err && <p className="fx-note">در حالِ آماده‌سازی…</p>}
          {thumbs && (
            <div className="flex flex-wrap gap-2" data-testid="channel-thumbs" style={{ justifyContent: "center" }}>
              {thumbs.map(({ ch, url }) => (
                <button key={ch.id} type="button" onClick={() => setPick(ch.id)} aria-pressed={pick === ch.id} title={ch.tip} data-channel={ch.id}
                  style={{ border: pick === ch.id ? "2px solid var(--accent, #6366f1)" : "2px solid transparent", background: "none", padding: 2, borderRadius: 8, cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                  <img src={url} alt={ch.fa} style={{ maxWidth: 150, maxHeight: 110, borderRadius: 6, background: "#222" }} />
                  <span style={{ fontSize: 12 }}>{ch.fa}</span>
                </button>
              ))}
            </div>
          )}
          <label className="fx-row" style={{ marginTop: 8 }}>
            <input type="checkbox" checked={invert} onChange={(e) => setInvert(e.target.checked)} data-testid="channel-invert" />
            <span>معکوس (تاریک‌ترها انتخاب شوند)</span>
          </label>
        </div>
        <div className="fx-foot">
          <button type="button" className="ws-btn primary" disabled={!src} onClick={() => src && onLoad(pick, invert, "new", src)} data-testid="channel-load">بارگذاری به‌عنوان انتخاب</button>
          <button type="button" className="ws-btn" disabled={!src} onClick={() => src && onLoad(pick, invert, "add", src)} data-testid="channel-add" title="به انتخابِ فعلی اضافه می‌شود">افزودن به انتخاب</button>
          <button type="button" className="ws-btn" disabled={!src} onClick={() => src && onLoad(pick, invert, "sub", src)} data-testid="channel-sub" title="از انتخابِ فعلی کم می‌شود">کم‌کردن از انتخاب</button>
          <button type="button" className="ws-btn" onClick={onClose}>بستن</button>
        </div>
      </div>
    </div>
  );
}
