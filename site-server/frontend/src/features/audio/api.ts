import { api } from "../../api/client";

/** One GPU audio engine on the processing nodes (backend: services/audio/node_audio.py). */
export type EngineKey = "moss" | "sfx" | "music";

export type EngineState = {
  label: string;
  what: string;
  license: string;
  commercial: boolean;
  package: string;
  gb: number;
  ready: boolean;
  installed_on: string[];
  online_on: string[];
  /** Empty when ready; otherwise exactly what the owner has to do (Persian). */
  message: string;
};

export type VoiceOption = {
  id: string;
  engine: string;
  name: string;
  gender: string;
  note: string;
  license: string;
  commercial: boolean;
  where: "node" | "site";
  available: boolean;
  why: string;
  group: string;
  cloned?: boolean;
};

export type SfxPreset = { key: string; label: string; kind: string; prompt: string };
export type MusicStyle = { id: string; label: string; prompt: string; bpm: number };

export type AudioOverview = {
  status: { engines: Record<EngineKey, EngineState> };
  voices: VoiceOption[];
  sfx_presets: SfxPreset[];
  music_styles: MusicStyle[];
  limits: {
    speech_chars: number;
    sfx: [number, number];
    music: [number, number];
    speed: [number, number];
    daily_seconds: number;
    used_today: number;
  };
};

export type AssetKind = "SPEECH" | "SFX" | "MUSIC";

export type AudioAsset = {
  id: number;
  kind: AssetKind;
  kind_label: string;
  status: "PENDING" | "RUNNING" | "READY" | "FAILED";
  status_label: string;
  title: string;
  text: string;
  prompt: string;
  params: Record<string, unknown>;
  engine: string;
  voice_label: string;
  cloned_voice: number | null;
  license: string;
  commercial: boolean;
  duration: number;
  size: number;
  error: string;
  saved: boolean;
  used_in: { script: number; as: string; at: string }[];
  created_at: string;
  has_file: boolean;
  job: { state: string; label: string; progress: number; message: string; node: string | null } | null;
};

export const audioBase = (storeId: string | number) => `/stores/${storeId}/audio/`;

export async function loadOverview(storeId: string | number): Promise<AudioOverview> {
  const { data } = await api.get<AudioOverview>(audioBase(storeId));
  return data;
}

export async function listAssets(
  storeId: string | number,
  query: { kind?: AssetKind; saved?: boolean } = {},
): Promise<AudioAsset[]> {
  const params = new URLSearchParams();
  if (query.kind) params.set("kind", query.kind);
  if (query.saved) params.set("saved", "1");
  const { data } = await api.get<{ assets: AudioAsset[] }>(`${audioBase(storeId)}assets/?${params.toString()}`);
  return data.assets;
}

export async function createAsset(storeId: string | number, body: Record<string, unknown>): Promise<AudioAsset> {
  const { data } = await api.post<AudioAsset>(`${audioBase(storeId)}assets/`, body);
  return data;
}

export async function getAsset(storeId: string | number, id: number): Promise<AudioAsset> {
  const { data } = await api.get<AudioAsset>(`${audioBase(storeId)}assets/${id}/`);
  return data;
}

export async function patchAsset(storeId: string | number, id: number, body: Partial<AudioAsset>): Promise<AudioAsset> {
  const { data } = await api.patch<AudioAsset>(`${audioBase(storeId)}assets/${id}/`, body);
  return data;
}

export async function deleteAsset(storeId: string | number, id: number): Promise<void> {
  await api.delete(`${audioBase(storeId)}assets/${id}/`);
}

export const assetFile = (storeId: string | number, id: number, download = false) =>
  `${audioBase(storeId)}assets/${id}/file/${download ? "?download=1" : ""}`;

export const isFinal = (a: AudioAsset) => a.status === "READY" || a.status === "FAILED";

export function seconds(value: number): string {
  if (!value) return "—";
  const m = Math.floor(value / 60);
  const s = Math.round(value % 60);
  return m ? `${m}:${String(s).padStart(2, "0")}` : `${s} ث`;
}
