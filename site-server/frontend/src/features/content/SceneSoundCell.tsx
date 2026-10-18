import { useState } from "react";

import { api, errorMessage } from "../../api/client";
import { Badge, Button } from "../../components/ui";
import { SoundOption, VideoSceneInfo } from "../../types";

type EffectRow = { key: string; at: number };

/**
 * One scene's ambience and effects: what will play, and a way to change it.
 *
 * Three states per half, matching the backend: **automatic** (no key — the
 * planner reads the scene's words), **none** (an explicit decision), or a
 * sound picked by hand. The automatic choice is shown by name, so «خودکار»
 * never means "we'll see".
 */
export default function SceneSoundCell({
  scriptId,
  scene,
  catalogue,
  onSaved,
}: {
  scriptId: number;
  scene: VideoSceneInfo;
  catalogue: SoundOption[];
  onSaved: (scene: VideoSceneInfo) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [ambience, setAmbience] = useState<string>(scene.sound?.ambience ?? "");
  const [effectsAuto, setEffectsAuto] = useState(!Array.isArray(scene.sound?.effects));
  // Always two slots; an empty key is an unused slot.
  const [slots, setSlots] = useState<EffectRow[]>(() => {
    const saved = scene.sound?.effects ?? [];
    return [0, 1].map((i) => saved[i] ?? { key: "", at: 0.5 });
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const beds = catalogue.filter((s) => s.kind === "bed");
  const spots = catalogue.filter((s) => s.kind === "spot");
  const plan = scene.sound_plan;
  const sample = catalogue.find((s) => s.key === ambience)?.sample_url;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.patch<VideoSceneInfo>(
        `/video-scripts/${scriptId}/scenes/${scene.index}/sound/`,
        {
          ambience: ambience || null,
          effects: effectsAuto ? null : slots.filter((e) => e.key),
        },
      );
      onSaved(data);
      setEditing(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const label = (option: SoundOption) =>
    option.available
      ? option.recordings > 0
        ? option.label
        : `${option.label} (ساخت با کد)`
      : `${option.label} — فایلی ندارد`;

  if (!editing) {
    return (
      <div className="flex flex-col items-start gap-1 text-xs">
        {plan?.ambience_label ? (
          <Badge tone="neutral">🌧️ {plan.ambience_label}</Badge>
        ) : (
          <span style={{ color: "var(--text-3)" }}>بدون صدای محیط</span>
        )}
        {plan?.effects.map((effect) => (
          <Badge key={`${effect.key}-${effect.at}`} tone="brand">
            ✨ {effect.label}
          </Badge>
        ))}
        <span style={{ color: "var(--text-3)" }}>
          {scene.sound && Object.keys(scene.sound).length > 0 ? "انتخاب دستی" : "خودکار"}
        </span>
        <button
          type="button"
          className="text-violet-600 hover:underline"
          onClick={() => setEditing(true)}
          disabled={catalogue.length === 0}
        >
          تغییر صدا
        </button>
      </div>
    );
  }

  return (
    <div className="flex min-w-[220px] flex-col gap-2 text-xs">
      <label className="flex flex-col gap-1">
        <span style={{ color: "var(--text-2)" }}>صدای محیط</span>
        <select className="u-input" value={ambience} onChange={(e) => setAmbience(e.target.value)}>
          <option value="">خودکار{plan?.ambience_label && !scene.sound?.ambience ? ` (${plan.ambience_label})` : ""}</option>
          <option value="none">بدون صدای محیط</option>
          {beds.map((option) => (
            <option key={option.key} value={option.key} disabled={!option.available}>
              {label(option)}
            </option>
          ))}
        </select>
      </label>
      {sample && <audio controls preload="none" src={sample} className="h-8 w-full" />}

      <label className="flex items-center gap-1">
        <input
          type="checkbox"
          checked={effectsAuto}
          onChange={(e) => setEffectsAuto(e.target.checked)}
        />
        <span style={{ color: "var(--text-2)" }}>افکت‌ها خودکار (از روی متن صحنه)</span>
      </label>
      {!effectsAuto && (
        <div className="flex flex-col gap-1">
          {[0, 1].map((slot) => {
            const row = slots[slot];
            const update = (next: EffectRow) =>
              setSlots(slots.map((current, i) => (i === slot ? next : current)));
            return (
              <div key={slot} className="flex items-center gap-1">
                <select
                  className="u-input"
                  value={row.key}
                  onChange={(e) => update({ ...row, key: e.target.value })}
                >
                  <option value="">{slot === 0 ? "بدون افکت" : "افکت دوم: ندارد"}</option>
                  {spots.map((option) => (
                    <option key={option.key} value={option.key} disabled={!option.available}>
                      {label(option)}
                    </option>
                  ))}
                </select>
                {row.key && (
                  <input
                    type="number"
                    className="u-input w-20"
                    min={0}
                    max={Math.max(0, scene.duration - 0.3)}
                    step={0.1}
                    value={row.at}
                    title="ثانیه‌ی پخش از شروع صحنه"
                    onChange={(e) => update({ ...row, at: Number(e.target.value) })}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}

      {error && <span style={{ color: "var(--bad)" }}>{error}</span>}
      <div className="flex gap-1">
        <Button size="sm" onClick={() => void save()} disabled={busy}>
          {busy ? "…" : "ذخیره"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={busy}>
          انصراف
        </Button>
      </div>
    </div>
  );
}
