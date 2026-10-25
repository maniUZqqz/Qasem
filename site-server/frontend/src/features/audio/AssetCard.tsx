import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { Badge, Button, Meter, Spinner, fa } from "../../components/ui";
import { AudioAsset, assetFile, deleteAsset, getAsset, isFinal, patchAsset, seconds } from "./api";
import { useAuthAudio } from "./useAuthAudio";

/** Keeps a generated sound up to date while a processing node works on it (every 3 s, until it is final). */
export function useLiveAsset(storeId: string | number, initial: AudioAsset, onChange?: (a: AudioAsset) => void) {
  const [asset, setAsset] = useState(initial);
  const changed = useRef(onChange);
  changed.current = onChange;
  useEffect(() => setAsset(initial), [initial]);
  const pending = !isFinal(asset);
  useEffect(() => {
    if (!pending) return;
    const id = window.setInterval(async () => {
      try {
        const fresh = await getAsset(storeId, asset.id);
        setAsset(fresh);
        if (isFinal(fresh)) changed.current?.(fresh);
      } catch {
        // a missed poll is retried on the next tick
      }
    }, 3000);
    return () => window.clearInterval(id);
  }, [storeId, asset.id, pending]);
  return [asset, setAsset] as const;
}

const KIND_ICON = { SPEECH: "mic", SFX: "cloud", MUSIC: "music" } as const;

/**
 * One sound of the shop: status (with the node's progress while it is made), player, download, keep in the
 * library, delete. The same card in every generator, the library and the video studio.
 */
export default function AssetCard({
  storeId,
  asset: initial,
  onChange,
  onDeleted,
  setError,
  compact = false,
  extra,
}: {
  storeId: string | number;
  asset: AudioAsset;
  onChange?: (a: AudioAsset) => void;
  onDeleted?: (id: number) => void;
  setError?: (m: string | null) => void;
  compact?: boolean;
  extra?: React.ReactNode;
}) {
  const [asset, setAsset] = useLiveAsset(storeId, initial, onChange);
  const [src, setSrc] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const audio = useAuthAudio();
  const fail = (err: unknown) => setError?.(errorMessage(err));

  const listen = async () => {
    try {
      setSrc(await audio.load(assetFile(storeId, asset.id)));
    } catch (err) {
      fail(err);
    }
  };

  const toggleSaved = async () => {
    setBusy(true);
    try {
      const fresh = await patchAsset(storeId, asset.id, { saved: !asset.saved });
      setAsset(fresh);
      onChange?.(fresh);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`«${asset.title || asset.kind_label}» پاک شود؟`)) return;
    try {
      await deleteAsset(storeId, asset.id);
      onDeleted?.(asset.id);
    } catch (err) {
      fail(err);
    }
  };

  const extension = asset.engine === "edge" ? ".mp3" : ".wav";

  return (
    <div
      className="flex flex-col gap-2 rounded-xl p-3"
      style={{ border: "1px solid var(--line)", background: "var(--surface)" }}
      data-testid="asset-card"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Icon name={KIND_ICON[asset.kind]} size={15} />
        <b className="text-sm" style={{ color: "var(--text)" }}>
          {asset.title || asset.kind_label}
        </b>
        <Badge tone={asset.status === "READY" ? "ok" : asset.status === "FAILED" ? "bad" : "info"}>
          {asset.status_label}
        </Badge>
        <Badge tone={asset.commercial ? "ok" : "warn"}>
          {asset.commercial ? `تجاری مجاز · ${asset.license}` : `فقط غیرتجاری · ${asset.license}`}
        </Badge>
        {asset.duration > 0 && (
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            {seconds(asset.duration)}
          </span>
        )}
        {asset.voice_label && (
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            صدا: {asset.voice_label}
          </span>
        )}
        {asset.used_in.length > 0 && <Badge tone="brand">در {fa(asset.used_in.length)} ویدیو</Badge>}
      </div>

      {!isFinal(asset) && (
        <div className="flex flex-col gap-1 text-xs" style={{ color: "var(--text-3)" }}>
          <div className="flex items-center gap-2">
            <Spinner size={14} />
            {asset.job?.message || asset.job?.label || "در صفِ سرورِ پردازش"}
            {asset.job?.node && <span dir="ltr">{asset.job.node}</span>}
          </div>
          <Meter used={Math.round((asset.job?.progress ?? 0) * 100)} total={100} />
        </div>
      )}
      {asset.status === "FAILED" && (
        <div className="text-sm" style={{ color: "var(--bad)" }}>
          {asset.error}
        </div>
      )}
      {!compact && asset.text && asset.kind === "SPEECH" && (
        <p className="text-sm" style={{ color: "var(--text-2)" }}>
          {asset.text}
        </p>
      )}
      {!compact && asset.kind !== "SPEECH" && asset.prompt && (
        <p className="text-xs" dir="ltr" style={{ color: "var(--text-3)" }}>
          {asset.prompt}
        </p>
      )}

      {asset.status === "READY" && (
        <div className="flex flex-wrap items-center gap-2">
          {src ? (
            <audio key={src} controls autoPlay src={src} className="h-9 min-w-[14rem] flex-1" />
          ) : (
            <Button size="sm" variant="secondary" onClick={() => void listen()}>
              <Icon name="play" size={13} />
              پخش
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void audio.download(assetFile(storeId, asset.id, true), `${asset.title || "audio"}${extension}`).catch(fail)}
          >
            <Icon name="download" size={13} />
            دانلود
          </Button>
          <Button size="sm" variant={asset.saved ? "ghost" : "primary"} onClick={() => void toggleSaved()} disabled={busy}>
            <Icon name={asset.saved ? "check" : "plus"} size={13} />
            {asset.saved ? "در کتابخانه" : "ذخیره در کتابخانه"}
          </Button>
          {extra}
          <Button size="sm" variant="ghost" onClick={() => void remove()} title="پاک کردن">
            <Icon name="trash" size={13} />
          </Button>
        </div>
      )}
      {asset.status === "FAILED" && (
        <div>
          <Button size="sm" variant="ghost" onClick={() => void remove()}>
            <Icon name="trash" size={13} />
            حذف
          </Button>
        </div>
      )}
    </div>
  );
}
