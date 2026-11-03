import type { Effect, Measurements } from "../../../components/BeforeAfter";
import type { Finding, PlanOp } from "./api";

export type EditOutcome = {
  mode?: string;
  instruction?: string;
  kept?: boolean;
  improved?: boolean;
  note?: string;
  rounds?: number;
  summary?: string;
  operations?: PlanOp[];
  refusals?: string[];
  before?: Measurements;
  after?: Measurements;
  effects?: Effect[];
  /** Which noise remover ran, and what it measured. */
  denoise?: {
    engine: string;
    before: { snr_db?: number; noise_floor_db?: number };
    after: { snr_db?: number; noise_floor_db?: number };
    improvement_db: number | null;
    notes: string[];
  } | null;
};

export type Video = {
  id: number;
  title: string;
  state: string;
  duration: number;
  has_audio: boolean;
  facts: Record<string, number | boolean | string>;
  findings: Finding[];
  video_url: string | null;
  edited_url: string | null;
  /** The last edit: plan, before/after measurements, per-tool verdicts. */
  edit_outcome?: EditOutcome | null;
  error: string;
};

export type Mode = { key: string; title: string };
