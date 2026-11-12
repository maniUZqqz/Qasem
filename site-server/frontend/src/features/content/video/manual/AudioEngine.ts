import { duckGainAt } from "./keyframes";
import { AnyClip, ClipAudio, DEFAULT_DUCKING, MediaClip, Project, Track, clipEnd, clipLength, propAt } from "./model";

/**
 * میکسِ صدای پیش‌نمایش با WebAudio — آینهٔ backend/services/editing/audiofx.py:
 *
 *   element ─► بلندیِ قطعه (volume × کلیدفریم × محوشدن × فرو رفتنِ نیمهٔ گذار)
 *           ─► EQ (biquad ها = EQ_CHAINS) ─► کمپرسور ─► [پن (balance)]
 *           ─► ترک (gain_db، پن، mute/solo) ─► باسِ نقش (گفتار / موسیقی / بقیه)
 *           ─► موسیقی: کم‌شدنِ خودکار زیرِ گفتار (duckGainAt) ─► مستر (gain_db) ─► لیمیتر ─► میتر ─► خروجی
 *
 * موتور فقط «بلندی و مسیر» را می‌گرداند؛ play/pause/seek و playbackRate با مانیتور است.
 * عنصری که ثبت شد باید volume=1 و muted=false بماند (موتور خودش آن‌ها را همین‌طور می‌گذارد).
 *
 * تفاوت‌هایی که پیش‌نمایش ندارد و فقط در خروجی/«پیش‌نمایشِ دقیق» شنیده می‌شود: حذفِ نویز (afftdn)، یکسان‌سازیِ بلندی
 * (loudnorm)، وارونگیِ صدا (areverse) و مبدلِ زمانِ باکیفیت (atempo)؛ کمپرسور و EQ نزدیک‌اند نه یکسان.
 */

type EqBand = { type: "highpass" | "lowpass" | "peaking"; f: number; q: number; g: number };

/** همان EQ_CHAINS سرور. `equalizer=...:t=q:w=W` ⇒ peaking با Q=W؛ highpass/lowpass پیش‌فرضِ ffmpeg = باترورث (Q=0.707) */
export const EQ_BANDS: Record<string, EqBand[]> = {
  voice: [
    { type: "highpass", f: 80, q: 0.707, g: 0 }, { type: "peaking", f: 200, q: 1, g: -2 }, { type: "peaking", f: 3000, q: 1, g: 3 },
    { type: "peaking", f: 6000, q: 1.5, g: 1.5 },
  ],
  bright: [{ type: "highpass", f: 60, q: 0.707, g: 0 }, { type: "peaking", f: 9000, q: 1, g: 4 }],
  warm: [{ type: "peaking", f: 150, q: 1, g: 3 }, { type: "peaking", f: 6500, q: 1, g: -3 }],
  phone: [{ type: "highpass", f: 300, q: 0.707, g: 0 }, { type: "lowpass", f: 3400, q: 0.707, g: 0 }],
  bass_cut: [{ type: "highpass", f: 120, q: 0.707, g: 0 }],
  bass_boost: [{ type: "peaking", f: 90, q: 1, g: 6 }],
  deess: [{ type: "peaking", f: 7000, q: 2, g: -5 }],
};

const BUTTERWORTH_DB = 20 * Math.log10(Math.SQRT1_2); // در WebAudio، Q ِ highpass/lowpass بر حسبِ dB است

const dbToLin = (db: number) => Math.pow(10, db / 20);
const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
const EPS = 1e-3;

/** پن به شیوهٔ سرور: سمتِ غالب ۱، سمتِ دیگر کم می‌شود (pan_gains) */
export function panGains(pan: number): [number, number] {
  return [pan <= 0 ? 1 : 1 - pan, pan >= 0 ? 1 : 1 + pan];
}

/** مرحلهٔ balance: ورودی استریو ⇒ دو گین ⇒ خروجی. `setPan` همان pan_gains */
class Balance {
  readonly input: GainNode;
  readonly output: ChannelMergerNode;
  private readonly gl: GainNode;
  private readonly gr: GainNode;
  private last = NaN;

  constructor(ctx: AudioContext) {
    this.input = ctx.createGain();
    this.input.channelCount = 2;
    this.input.channelCountMode = "explicit";
    this.input.channelInterpretation = "speakers";
    const split = ctx.createChannelSplitter(2);
    this.gl = ctx.createGain();
    this.gr = ctx.createGain();
    this.output = ctx.createChannelMerger(2);
    this.input.connect(split);
    split.connect(this.gl, 0);
    split.connect(this.gr, 1);
    this.gl.connect(this.output, 0, 0);
    this.gr.connect(this.output, 0, 1);
  }

  setPan(pan: number): void {
    if (Math.abs(pan - this.last) < EPS) return;
    this.last = pan;
    const [l, r] = panGains(pan);
    this.gl.gain.value = l;
    this.gr.gain.value = r;
  }

  disconnect(): void {
    this.input.disconnect();
    this.gl.disconnect();
    this.gr.disconnect();
    this.output.disconnect();
  }
}

type ChainSpec = { key: string; bands: EqBand[]; comp: { threshold: number; ratio: number; attack: number; release: number } | null; pan: boolean };

/** سازهٔ زنجیرِ یک قطعه از روی بلوکِ `audio` (fx_chain سرور) */
function chainSpec(audio: ClipAudio | undefined): ChainSpec {
  const a = audio ?? {};
  const bands: EqBand[] = [];
  let comp: ChainSpec["comp"] = null;
  if (a.enhance) {
    bands.push(...EQ_BANDS.voice);
    comp = { threshold: 20 * Math.log10(0.125), ratio: 3, attack: 0.015, release: 0.2 };
  } else if (a.eq && EQ_BANDS[a.eq]) {
    bands.push(...EQ_BANDS[a.eq]);
  }
  const amount = a.comp ?? 0;
  if (amount > 0.01 && !comp) {
    comp = { threshold: 20 * Math.log10(0.25 - 0.2 * amount), ratio: 2 + 6 * amount, attack: 0.02, release: 0.25 };
  }
  const pan = Math.abs(a.pan ?? 0) > 0.01;
  const key = JSON.stringify([bands.map((b) => [b.type, b.f, b.q, b.g]), comp, pan]);
  return { key, bands, comp, pan };
}

type ClipNodes = {
  el: HTMLMediaElement;
  source: MediaElementAudioSourceNode;
  gain: GainNode;
  chain: AudioNode[];       // گره‌های ساخته‌شده (filter، کمپرسور، balance) برای قطع کردن
  tail: AudioNode;          // آخرین گرهٔ زنجیر
  balance: Balance | null;
  spec: string;
  trackId: string | null;
  lastGain: number;
};

type TrackNodes = {
  input: GainNode;
  gain: GainNode;
  balance: Balance;
  analyser: AnalyserNode;
  role: "speech" | "music" | "other";
  lastGain: number;
  buf: Float32Array;
  level: number;
  tail: AudioNode;
};

export type Levels = { l: number; r: number; peakL: number; peakR: number };

type Derived = {
  project: Project;
  byClip: Map<string, { track: Track; clip: MediaClip }>;
  halfIn: Map<string, number>;
  halfOut: Map<string, number>;
  soloing: boolean;
};

/** نیمهٔ گذارها: audiofx.plan_transitions (فقط ترک‌های تصویرِ دیده‌شونده، قطعه‌های چسبیده) */
function transitionHalves(project: Project): { halfIn: Map<string, number>; halfOut: Map<string, number> } {
  const halfIn = new Map<string, number>();
  const halfOut = new Map<string, number>();
  for (const track of project.tracks) {
    if (track.kind !== "video" || track.hidden) continue;
    const ordered = track.clips.filter((c): c is MediaClip => c.type === "media" && c.kind !== "audio").sort((a, b) => a.at - b.at);
    for (let i = 1; i < ordered.length; i++) {
      const earlier = ordered[i - 1];
      const later = ordered[i];
      const tr = later.transition;
      if (!tr || Math.abs(later.at - clipEnd(earlier)) > 0.15) continue;
      const d = Math.max(0.1, Math.min(tr.duration ?? 0.5, 2.0, 0.9 * Math.min(clipLength(earlier), clipLength(later))));
      const half = d / 2;
      halfOut.set(earlier.id, Math.max(halfOut.get(earlier.id) ?? 0, half));
      halfIn.set(later.id, Math.max(halfIn.get(later.id) ?? 0, half));
    }
  }
  return { halfIn, halfOut };
}

function derive(project: Project): Derived {
  const byClip = new Map<string, { track: Track; clip: MediaClip }>();
  for (const track of project.tracks) {
    if (track.kind === "text") continue;
    for (const c of track.clips as AnyClip[]) if (c.type === "media") byClip.set(c.id, { track, clip: c });
  }
  const { halfIn, halfOut } = transitionHalves(project);
  return { project, byClip, halfIn, halfOut, soloing: project.tracks.some((t) => t.kind !== "text" && t.solo) };
}

type AudioContextCtor = typeof AudioContext;

export class AudioEngine {
  /** false ⇒ مرورگر WebAudio ندارد؛ register() هیچ‌چیز را مسیریابی نمی‌کند و مانیتور باید خودش volume/muted را بگردانَد */
  readonly available: boolean;
  private ctx: AudioContext | null = null;
  private clips = new Map<string, ClipNodes>();
  private tracks = new Map<string, TrackNodes>();
  private sources = new WeakMap<HTMLMediaElement, MediaElementAudioSourceNode>();
  private buses!: { speech: GainNode; music: GainNode; other: GainNode };
  private duck!: GainNode;
  private master!: GainNode;
  private limiter!: DynamicsCompressorNode;
  private ceiling!: WaveShaperNode;
  private mute!: GainNode;
  private anL!: AnalyserNode;
  private anR!: AnalyserNode;
  private bufL = new Float32Array(1024);
  private bufR = new Float32Array(1024);
  private derived: Derived | null = null;
  private lastMaster = NaN;
  private lastDuck = NaN;
  private lastLimiter: boolean | null = null;
  private meter = { l: 0, r: 0, peakL: 0, peakR: 0, holdL: 0, holdR: 0, at: 0 };

  constructor() {
    const Ctor: AudioContextCtor | undefined =
      typeof window === "undefined" ? undefined : window.AudioContext ?? (window as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
    if (!Ctor) {
      this.available = false;
      return;
    }
    try {
      this.ctx = new Ctor({ latencyHint: "interactive" });
    } catch {
      this.available = false;
      return;
    }
    this.available = true;
    const ctx = this.ctx;
    this.buses = { speech: ctx.createGain(), music: ctx.createGain(), other: ctx.createGain() };
    this.duck = ctx.createGain();
    this.master = ctx.createGain();
    this.limiter = ctx.createDynamicsCompressor();
    this.limiter.knee.value = 0;
    this.limiter.attack.value = 0.003;
    this.limiter.release.value = 0.1;
    // سقفِ سخت: alimiter=limit=0.95 — کمپرسورِ WebAudio دیوارِ آجری نیست، پس بعدش قیچی می‌کنیم (فقط وقتی لیمیتر روشن است)
    this.ceiling = ctx.createWaveShaper();
    this.mute = ctx.createGain();
    this.buses.music.connect(this.duck);
    this.duck.connect(this.master);
    this.buses.speech.connect(this.master);
    this.buses.other.connect(this.master);
    this.master.connect(this.limiter);
    this.limiter.connect(this.ceiling);
    this.ceiling.connect(this.mute);
    this.mute.connect(ctx.destination);
    const split = ctx.createChannelSplitter(2);
    this.anL = ctx.createAnalyser();
    this.anR = ctx.createAnalyser();
    this.anL.fftSize = this.anR.fftSize = 1024;
    this.mute.connect(split);
    split.connect(this.anL, 0);
    split.connect(this.anR, 1);
  }

  /** از داخلِ کلیکِ «پخش» صدا بزنید (سیاستِ autoplay). بی‌خطا. */
  async resume(): Promise<void> {
    if (!this.ctx) return;
    try {
      if (this.ctx.state !== "running") await this.ctx.resume();
    } catch {
      /* بدونِ اشاره‌ی کاربر باز نمی‌شود؛ بار بعد */
    }
  }

  get state(): AudioContextState | "unavailable" {
    return this.ctx ? this.ctx.state : "unavailable";
  }

  /** عنصرِ پخشِ یک قطعه را به میکس وصل می‌کند. true = مسیریابی شد (دیگر volume/muted را خودتان نگردانید). */
  register(clipId: string, el: HTMLMediaElement): boolean {
    const ctx = this.ctx;
    if (!ctx) return false;
    const old = this.clips.get(clipId);
    if (old && old.el === el) return true;
    if (old) this.unregister(clipId);
    let source = this.sources.get(el);
    if (!source) {
      try {
        source = ctx.createMediaElementSource(el);
      } catch {
        return false; // این عنصر قبلاً به زمینهٔ دیگری وصل شده
      }
      this.sources.set(el, source);
    }
    el.volume = 1;
    el.muted = false;
    const gain = ctx.createGain();
    gain.gain.value = 0;
    gain.channelCount = 2;
    gain.channelCountMode = "explicit";
    gain.channelInterpretation = "speakers";
    source.connect(gain);
    this.clips.set(clipId, { el, source, gain, chain: [], tail: gain, balance: null, spec: "", trackId: null, lastGain: 0 });
    void this.resume();
    return true;
  }

  unregister(clipId: string): void {
    const n = this.clips.get(clipId);
    if (!n) return;
    this.clips.delete(clipId);
    this.teardown(n);
    try {
      n.source.disconnect();
      n.gain.disconnect();
    } catch {
      /* قبلاً قطع بود */
    }
  }

  private teardown(n: ClipNodes): void {
    for (const node of n.chain) {
      try {
        node.disconnect();
      } catch {
        /* ignore */
      }
    }
    n.balance?.disconnect();
    try {
      n.gain.disconnect();
    } catch {
      /* ignore */
    }
    n.chain = [];
    n.balance = null;
    n.tail = n.gain;
    n.trackId = null;
    n.spec = "";
  }

  private ensureTrack(track: Track): TrackNodes | null {
    const ctx = this.ctx;
    if (!ctx) return null;
    const role = track.role === "speech" || track.role === "music" ? track.role : "other";
    let t = this.tracks.get(track.id);
    if (t && t.role !== role) {
      this.dropTrack(track.id);
      t = undefined;
    }
    if (!t) {
      const input = ctx.createGain();
      input.channelCount = 2;
      input.channelCountMode = "explicit";
      input.channelInterpretation = "speakers";
      const gain = ctx.createGain();
      const balance = new Balance(ctx);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      input.connect(gain);
      gain.connect(balance.input);
      balance.output.connect(this.buses[role]);
      balance.output.connect(analyser);
      t = { input, gain, balance, analyser, role, lastGain: NaN, buf: new Float32Array(512), level: 0, tail: balance.output };
      this.tracks.set(track.id, t);
    }
    return t;
  }

  private dropTrack(id: string): void {
    const t = this.tracks.get(id);
    if (!t) return;
    this.tracks.delete(id);
    for (const [, c] of this.clips) {
      if (c.trackId === id) this.teardown(c);
    }
    try {
      t.input.disconnect();
      t.gain.disconnect();
      t.balance.disconnect();
      t.analyser.disconnect();
    } catch {
      /* ignore */
    }
  }

  /** (دوباره) زنجیرِ یک قطعه را می‌سازد اگر مشخصاتش عوض شده یا ترکش عوض شده */
  private ensureChain(n: ClipNodes, clip: MediaClip, track: Track, tn: TrackNodes): void {
    const ctx = this.ctx;
    if (!ctx) return;
    const spec = chainSpec(clip.audio);
    if (n.spec === spec.key && n.trackId === track.id) return;
    this.teardown(n);
    n.source.connect(n.gain);
    let tail: AudioNode = n.gain;
    for (const band of spec.bands) {
      const f = ctx.createBiquadFilter();
      f.type = band.type;
      f.frequency.value = band.f;
      if (band.type === "peaking") {
        f.Q.value = band.q;
        f.gain.value = band.g;
      } else {
        f.Q.value = BUTTERWORTH_DB;
      }
      tail.connect(f);
      n.chain.push(f);
      tail = f;
    }
    if (spec.comp) {
      const c = ctx.createDynamicsCompressor();
      c.threshold.value = spec.comp.threshold;
      c.ratio.value = spec.comp.ratio;
      c.attack.value = spec.comp.attack;
      c.release.value = spec.comp.release;
      c.knee.value = 9; // knee=2.828 (خطی) پیش‌فرضِ acompressor ≈ ۹ دسی‌بل
      tail.connect(c);
      n.chain.push(c);
      tail = c;
    }
    if (spec.pan) {
      n.balance = new Balance(ctx);
      tail.connect(n.balance.input);
      tail = n.balance.output;
    }
    tail.connect(tn.input);
    n.tail = tail;
    n.spec = spec.key;
    n.trackId = track.id;
  }

  private setGain(param: AudioParam, last: number, value: number, now: number): number {
    if (Math.abs(value - last) < 5e-4 && Number.isFinite(last)) return last;
    param.cancelScheduledValues(now);
    param.setTargetAtTime(value, now, 0.015);
    return value;
  }

  /** هر فریمِ انیمیشن از مانیتور صدا زده می‌شود */
  sync(project: Project, time: number, _playing: boolean, duckSpans: [number, number][]): void {
    const ctx = this.ctx;
    if (!ctx) return;
    const now = ctx.currentTime;
    if (!this.derived || this.derived.project !== project) {
      this.derived = derive(project);
      const live = new Set(project.tracks.filter((t) => t.kind !== "text").map((t) => t.id));
      for (const id of [...this.tracks.keys()]) if (!live.has(id)) this.dropTrack(id);
    }
    const d = this.derived;

    // ترک‌ها
    for (const track of project.tracks) {
      if (track.kind === "text") continue;
      const tn = this.ensureTrack(track);
      if (!tn) continue;
      const silent = track.muted || (d.soloing && !track.solo);
      const g = silent ? 0 : Math.abs(track.gain_db ?? 0) > 0.01 ? dbToLin(track.gain_db ?? 0) : 1;
      tn.lastGain = this.setGain(tn.gain.gain, tn.lastGain, g, now);
      tn.balance.setPan(Math.abs(track.pan ?? 0) > 0.01 ? track.pan ?? 0 : 0);
    }

    // قطعه‌ها
    for (const [id, n] of this.clips) {
      const info = d.byClip.get(id);
      const tn = info ? this.tracks.get(info.track.id) : undefined;
      if (!info || !tn) {
        n.lastGain = this.setGain(n.gain.gain, n.lastGain, 0, now);
        continue;
      }
      const { clip, track } = info;
      this.ensureChain(n, clip, track, tn);
      n.balance?.setPan(clamp(clip.audio?.pan ?? 0, -1, 1));
      const len = clipLength(clip);
      const lt = time - clip.at;
      let g = 0;
      const carries = track.kind === "audio" || (clip.kind === "video" && clip.has_audio && clip.audio_on && !clip.freeze);
      if (carries && lt >= 0 && lt < len) {
        const base = track.kind === "audio" ? clip.opacity : 1; // «شفافیتِ» قطعهٔ صدا = سطحِ آن (معنای قدیمی)
        g = propAt(clip, "volume", time) * base;
        const fin = Math.max(clip.fade_in, d.halfIn.get(id) ?? 0);
        const fout = Math.max(clip.fade_out, d.halfOut.get(id) ?? 0);
        if (fin > 0) g *= clamp(lt / fin, 0, 1);
        if (fout > 0) g *= clamp((len - lt) / fout, 0, 1);
      }
      n.lastGain = this.setGain(n.gain.gain, n.lastGain, g, now);
    }

    // کم‌شدنِ موسیقی زیرِ گفتار
    const duck = project.ducking ?? DEFAULT_DUCKING;   // ۱۴۰۵/۰۸/۲۲: پیش‌فرض روشن ⇒ موسیقی زیرِ گفتار کم شود و صدا قاطی نشود
    const dg = duck?.on && duckSpans.length > 0 ? duckGainAt(duckSpans, duck.amount_db, duck.attack_ms / 1000, duck.release_ms / 1000, time) : 1;
    this.lastDuck = this.setGain(this.duck.gain, this.lastDuck, dg, now);

    // مستر
    const m = project.master;
    const mg = m && Math.abs(m.gain_db) > 0.01 ? dbToLin(m.gain_db) : 1;
    this.lastMaster = this.setGain(this.master.gain, this.lastMaster, mg, now);
    const limiterOn = m ? m.limiter : true;
    if (limiterOn !== this.lastLimiter) {
      this.lastLimiter = limiterOn;
      // alimiter=limit=0.95 ≈ -0.45 dBFS؛ خاموش = نسبتِ ۱ (شفاف)
      this.limiter.threshold.value = limiterOn ? -1 : 0;
      this.limiter.ratio.value = limiterOn ? 20 : 1;
      this.ceiling.curve = limiterOn ? AudioEngine.ceilingCurve() : null;
    }
  }

  private static ceilingCurve(): Float32Array {
    const n = 2049;
    const c = new Float32Array(n);
    for (let i = 0; i < n; i++) c[i] = clamp((i / (n - 1)) * 2 - 1, -0.95, 0.95);
    return c;
  }

  setMuted(muted: boolean): void {
    if (!this.ctx) return;
    this.mute.gain.setTargetAtTime(muted ? 0 : 1, this.ctx.currentTime, 0.01);
  }

  private static peak(buf: Float32Array): number {
    let p = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = Math.abs(buf[i]);
      if (v > p) p = v;
    }
    return p;
  }

  /** سطحِ مستر (دامنهٔ خطی): l/r = اوجِ نرم‌شده (حملهٔ سریع، افتِ آهسته)، peakL/peakR = نگه‌دارِ اوج (~۱٫۲ ثانیه) */
  levels(): Levels {
    if (!this.ctx) return { l: 0, r: 0, peakL: 0, peakR: 0 };
    const t = performance.now();
    const dt = this.meter.at ? Math.min(0.25, (t - this.meter.at) / 1000) : 0.016;
    this.meter.at = t;
    this.anL.getFloatTimeDomainData(this.bufL);
    this.anR.getFloatTimeDomainData(this.bufR);
    const fall = Math.pow(0.0005, dt); // ≈ −66 dB در ثانیه
    const m = this.meter;
    const pl = AudioEngine.peak(this.bufL);
    const pr = AudioEngine.peak(this.bufR);
    m.l = Math.max(pl, m.l * fall);
    m.r = Math.max(pr, m.r * fall);
    if (pl >= m.peakL) {
      m.peakL = pl;
      m.holdL = 1.2;
    } else if ((m.holdL -= dt) <= 0) m.peakL = Math.max(pl, m.peakL * Math.pow(0.05, dt));
    if (pr >= m.peakR) {
      m.peakR = pr;
      m.holdR = 1.2;
    } else if ((m.holdR -= dt) <= 0) m.peakR = Math.max(pr, m.peakR * Math.pow(0.05, dt));
    return { l: m.l, r: m.r, peakL: m.peakL, peakR: m.peakR };
  }

  /** سطحِ یک ترک (دامنهٔ خطی، افتِ نرم) — برای میترِ نوارِ میکسر. هر بار که صدا بزنید یک نمونه می‌خواند. */
  trackLevel(trackId: string): number {
    const t = this.tracks.get(trackId);
    if (!t) return 0;
    t.analyser.getFloatTimeDomainData(t.buf);
    t.level = Math.max(AudioEngine.peak(t.buf), t.level * 0.9);
    return t.level;
  }

  dispose(): void {
    for (const id of [...this.clips.keys()]) this.unregister(id);
    for (const id of [...this.tracks.keys()]) this.dropTrack(id);
    const ctx = this.ctx;
    this.ctx = null;
    this.derived = null;
    if (ctx) {
      try {
        this.mute.disconnect();
        this.master.disconnect();
        void ctx.close();
      } catch {
        /* ignore */
      }
    }
  }
}
