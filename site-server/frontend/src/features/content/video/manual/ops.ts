import {
  AnyClip, MediaClip, MulticamInfo, Project, Sequence, Track, addTrack, clipEnd, clipLength, findClip, isMedia, overlaps, projectLength, rollEdit, splitMany, uid, withLinked,
} from "./model";

/**
 * عملیاتِ سطحِ بالای ویرایشگر (بدونِ رابط): ریپلِ خودکار هنگامِ کندکردن، برشِ J/L، قطعِ خودکار روی ضرب‌ها، توالیِ تودرتو، مولتی‌کم.
 * همه توابعِ خالص‌اند (پروژهٔ تازه برمی‌گردانند) تا با تاریخچهٔ برگشت/جلو یک گام شوند.
 */
const EPS = 0.001;
const mapTracks = (p: Project, fn: (t: Track) => Track): Project => ({ ...p, tracks: p.tracks.map(fn) });
const sortClips = (cs: AnyClip[]): AnyClip[] => [...cs].sort((a, b) => a.at - b.at);
const allClips = (p: Project): AnyClip[] => p.tracks.flatMap((t) => t.clips);

function shiftIds(p: Project, ids: Set<string>, d: number): Project {
  return mapTracks(p, (t) => (t.clips.some((c) => ids.has(c.id)) ? { ...t, clips: sortClips(t.clips.map((c) => (ids.has(c.id) ? ({ ...c, at: Math.max(0, c.at + d) } as AnyClip) : c))) } : t));
}

// ───────────────────────────────────────────────────────── ریپلِ خودکار
const retimeSig = (c: MediaClip) => JSON.stringify([c.speed, c.ramp ?? null, !!c.reverse]);

/** سرعت/منحنی/وارونگیِ یک قطعه روی جفتِ پیوندی‌اش (همان منبع: صدایی که از آن جدا شده) هم می‌نشیند تا صدا و تصویر هم‌گام بمانند */
export function syncLinkedRetime(before: Project, after: Project): Project {
  const was = new Map<string, MediaClip>();
  for (const c of allClips(before)) if (isMedia(c)) was.set(c.id, c);
  const patches = new Map<string, Partial<MediaClip>>();
  for (const c of allClips(after)) {
    if (!isMedia(c) || !c.link) continue;
    const o = was.get(c.id);
    if (!o || retimeSig(o) === retimeSig(c)) continue;
    for (const q of allClips(after)) {
      if (isMedia(q) && q.id !== c.id && q.link === c.link && q.ref === c.ref && !q.freeze && q.kind !== "image" && retimeSig(q) !== retimeSig(c)) {
        patches.set(q.id, { speed: c.speed, ramp: c.ramp, reverse: c.reverse });
      }
    }
  }
  if (!patches.size) return after;
  return mapTracks(after, (t) => ({ ...t, clips: t.clips.map((c) => (patches.has(c.id) ? ({ ...c, ...patches.get(c.id) } as AnyClip) : c)) }));
}

function pushFollowers(p: Project, trackId: string, from: number, delta: number, skip: Set<string>): Project {
  const tr = p.tracks.find((t) => t.id === trackId);
  if (!tr) return p;
  const lead = tr.clips.filter((c) => !skip.has(c.id) && c.at >= from - 0.02).map((c) => c.id);
  if (!lead.length) return p;
  const moving = new Set(withLinked(p, lead).filter((id) => !skip.has(id)));
  let q = shiftIds(p, moving, delta);
  // یک جفتِ صدای جلورفته ممکن است به قطعه‌ای بی‌ربط روی ترکِ دیگر بخورد: آن‌ها هم (با جفت‌هایشان) کنار می‌روند
  for (let round = 0; round < 8; round++) {
    let again = false;
    for (const t of q.tracks) {
      const ordered = [...t.clips].sort((a, b) => a.at - b.at);
      for (let i = 0; i + 1 < ordered.length && !again; i++) {
        const a = ordered[i];
        const b = ordered[i + 1];
        if (moving.has(a.id) && !moving.has(b.id) && !skip.has(b.id) && b.at < clipEnd(a) - 0.002) {
          const need = clipEnd(a) - b.at;
          const group = new Set<string>(ordered.slice(i + 1).filter((x) => !moving.has(x.id) && !skip.has(x.id)).map((x) => x.id));
          for (const id of withLinked(q, [...group])) if (!skip.has(id)) group.add(id);
          q = shiftIds(q, group, need);
          group.forEach((id) => moving.add(id));
          again = true;
        }
      }
      if (again) break;
    }
    if (!again) break;
  }
  return q;
}

/**
 * «جابه‌جایی خودکارِ بعدی‌ها»: اگر در گذار از `before` به `after` طولِ یک قطعه فقط به‌خاطرِ تغییرِ سرعت (کندکردن، منحنی، کشیدنِ سرعت) بیشتر شده،
 * قطعه‌های بعدیِ همان ترک (و جفتِ صدا/تصویرِ پیوندی‌شان) به‌اندازهٔ افزایش جلو می‌روند — مثلِ ریپلِ پریمیر. کوتاه‌شدن هیچ‌چیز را عقب نمی‌کشد
 * (برای آن «حذفِ بی‌فاصله» هست). برشِ لبه (trim) ریپل نمی‌شود: آن همسایه را نمی‌گذراند.
 */
export function autoRipple(before: Project, after: Project): Project {
  if (after.auto_ripple === false) return after;
  const q0 = syncLinkedRetime(before, after);
  const was = new Map<string, MediaClip>();
  for (const c of allClips(before)) if (isMedia(c)) was.set(c.id, c);
  const pushes: { trackId: string; from: number; delta: number; skip: Set<string> }[] = [];
  for (const t of q0.tracks) {
    if (t.kind === "text") continue;
    for (const c of t.clips) {
      if (!isMedia(c) || c.freeze || c.kind === "image") continue;
      const o = was.get(c.id);
      if (!o || o.freeze || o.kind === "image") continue;
      if (Math.abs(c.at - o.at) > EPS || Math.abs(c.end - c.start - (o.end - o.start)) > EPS) continue;
      const delta = clipLength(c) - clipLength(o);
      if (delta > EPS) pushes.push({ trackId: t.id, from: o.at + clipLength(o), delta, skip: new Set(withLinked(q0, [c.id])) });
    }
  }
  let q = q0;
  for (const pu of pushes) q = pushFollowers(q, pu.trackId, pu.from, pu.delta, pu.skip);
  return q;
}

// ───────────────────────────────────────────────────────── برشِ J / L
export type JLResult = { ok: boolean; project: Project; message?: string; movedToTrack?: boolean };

const overlapLen = (a: AnyClip, b: AnyClip) => Math.max(0, Math.min(clipEnd(a), clipEnd(b)) - Math.max(a.at, b.at));

/** جفتِ (تصویر، صدا) که با هم پیوندی‌اند و از یک منبع‌اند — بیشترین هم‌پوشانی، نه «اولین صدایی که همان پیوند را دارد» (بعد از تقسیم چند جفت یک پیوند داشتند) */
export function avPair(p: Project, id: string): { video: MediaClip; audio: MediaClip } | null {
  const f = findClip(p, id);
  if (!f || f.clip.type !== "media" || !f.clip.link) return null;
  const sel = f.clip;
  const group = allClips(p).filter((c): c is MediaClip => isMedia(c) && c.link === sel.link && c.ref === sel.ref);
  const best = (pool: MediaClip[], ref: MediaClip) => [...pool].sort((a, b) => overlapLen(b, ref) - overlapLen(a, ref))[0];
  if (sel.kind === "audio") {
    const v = best(group.filter((c) => c.kind === "video"), sel);
    return v ? { video: v, audio: sel } : null;
  }
  const a = best(group.filter((c) => c.kind === "audio"), sel);
  return a ? { video: sel, audio: a } : null;
}

/** برشِ J (صدا زودتر از تصویر شروع شود) یا L (صدا بعد از تصویر ادامه یابد) به اندازهٔ `amount` ثانیه.
 *  اگر صدای درازشده به قطعهٔ دیگری روی همان ترکِ صدا بخورد (دو قطعه هم‌زمان = پروژه‌ای که سرور رندر نمی‌کند)، همان قطعه به ترکِ صدای خالی می‌رود. */
export function jlCut(p: Project, id: string, kind: "J" | "L", amount = 0.5): JLResult {
  const fail = (message: string): JLResult => ({ ok: false, project: p, message });
  const pair = avPair(p, id);
  if (!pair) return fail("برای J/L-cut اول صدا را از تصویر جدا کنید (و قطعه را انتخاب کنید).");
  const a = pair.audio;
  if ((a.ramp?.length ?? 0) >= 2 || a.reverse || a.freeze) return fail("برای صدایی که منحنیِ سرعت دارد یا وارونه است برشِ J/L ممکن نیست.");
  const sp = a.speed || 1;
  let patch: Partial<MediaClip>;
  let d: number;
  if (kind === "J") {
    d = Math.min(amount, a.at, a.start / sp);
    if (d < 0.04) return fail(a.at < 0.04 ? "صدا همین حالا به ابتدای تایم‌لاین رسیده است." : "صدا پیش از این نقطه چیزی در منبع ندارد؛ برای برش J قطعه باید از وسطِ منبع شروع شده باشد.");
    patch = { at: a.at - d, start: a.start - d * sp };
  } else {
    d = a.src ? Math.min(amount, (a.src - a.end) / sp) : amount;
    if (d < 0.04) return fail("منبع بعد از این نقطه صدایی ندارد؛ برای برش L قطعه باید پیش از پایانِ منبع تمام شده باشد.");
    patch = { end: a.end + d * sp };
  }
  const next = { ...a, ...patch } as MediaClip;
  const host = p.tracks.find((t) => t.clips.some((c) => c.id === a.id))!;
  let q = p;
  let dest = host;
  let moved = false;
  if (overlaps(host, next.at, clipLength(next), a.id)) {
    const free = p.tracks.find((t) => t.kind === "audio" && !t.locked && t.id !== host.id && !overlaps(t, next.at, clipLength(next)));
    if (free) dest = free;
    else {
      q = addTrack(q, "audio", host.role ?? "");
      dest = q.tracks.filter((t) => t.kind === "audio").slice(-1)[0];
    }
    moved = true;
  }
  q = mapTracks(q, (t) => {
    if (t.id === dest.id && dest.id === host.id) return { ...t, clips: sortClips(t.clips.map((c) => (c.id === a.id ? next : c))) };
    if (t.id === host.id) return { ...t, clips: t.clips.filter((c) => c.id !== a.id) };
    if (t.id === dest.id) return { ...t, clips: sortClips([...t.clips, next]) };
    return t;
  });
  return { ok: true, project: q, movedToTrack: moved };
}

// ───────────────────────────────────────────────────────── قطعِ خودکار روی ضرب‌ها (مثلِ CapCut)
export const beatTimes = (p: Project): number[] => (p.markers ?? []).filter((m) => m.kind === "beat").map((m) => m.t).sort((a, b) => a - b);
const everyNth = (beats: number[], every: number): number[] => beats.filter((_b, i) => i % Math.max(1, Math.round(every)) === 0);

/** قطعه‌ها (و جفتِ پیوندی‌شان) را روی هر n‌امین ضرب می‌شکافد */
export function beatSplit(p: Project, ids: string[], beats: number[], every = 1): { project: Project; cuts: number } {
  let q = p;
  let cuts = 0;
  const group = new Set(withLinked(p, ids));
  for (const t of everyNth(beats, every)) {
    const hit = [...group].filter((id) => {
      const f = findClip(q, id);
      return !!f && t > f.clip.at + 0.12 && t < clipEnd(f.clip) - 0.12;
    });
    if (!hit.length) continue;
    const had = new Set(allClips(q).map((c) => c.id));
    q = splitMany(q, hit, t);
    cuts++;
    for (const c of allClips(q)) if (!had.has(c.id)) group.add(c.id);
  }
  return { project: q, cuts };
}

/** مونتاژِ روی ضرب: قطعه‌های انتخاب‌شده (به ترتیب) روی بازه‌های بینِ ضرب‌ها چیده می‌شوند؛ هر قطعه از منبعِ خودش به اندازهٔ بازه می‌بُرد
 *  و اگر قطعه‌ها از بازه‌ها کمترند دور می‌زند (هر دور از ادامهٔ منبع). جای قطعه‌های اصلی را می‌گیرد. */
export function beatFit(p: Project, ids: string[], beats: number[], every = 1): { project: Project; made: number } {
  const picked = ids.map((id) => findClip(p, id)).filter((f): f is NonNullable<typeof f> => !!f && f.clip.type === "media" && f.clip.kind !== "audio");
  picked.sort((x, y) => x.clip.at - y.clip.at);
  const times = everyNth(beats, every);
  // the montage starts where the first clip started: the stretch before the first beat is the first shot (no black gap at the head)
  if (picked.length && times.length && times[0] - picked[0].clip.at > 0.2) times.unshift(picked[0].clip.at);
  if (!picked.length || times.length < 2) return { project: p, made: 0 };
  const host = picked[0].track;
  const gone = new Set(withLinked(p, picked.map((f) => f.clip.id)));
  const made: MediaClip[] = [];
  for (let j = 0; j + 1 < times.length; j++) {
    const base = picked[j % picked.length].clip as MediaClip;
    const a = times[j];
    const dur = times[j + 1] - a;
    if (dur < 0.2) continue;
    const need = base.kind === "image" ? dur : dur * (base.speed || 1);
    const cycle = Math.floor(j / picked.length);
    let start = base.kind === "image" ? 0 : base.start + cycle * need;
    let end = start + need;
    const limit = base.src || Infinity;
    if (base.kind !== "image" && end > limit) {
      start = Math.max(0, Math.min(base.start, limit - need));
      end = Math.min(limit, start + need);
    }
    if (end - start < 0.1) continue;
    made.push({ ...base, id: uid(), at: a, start, end, link: undefined, transition: null, fade_in: 0, fade_out: 0, kf: undefined });
  }
  if (!made.length) return { project: p, made: 0 };
  let q = mapTracks(p, (t) => ({ ...t, clips: t.clips.filter((c) => !gone.has(c.id)) }));
  const tgt = q.tracks.find((t) => t.id === host.id)!;
  const fit = made.filter((c) => !overlaps(tgt, c.at, clipLength(c)));
  q = mapTracks(q, (t) => (t.id === tgt.id ? { ...t, clips: sortClips([...t.clips, ...fit]) } : t));
  return { project: q, made: fit.length };
}

/** برش‌های موجود (جای چسبیدنِ دو قطعه) به نزدیک‌ترین ضرب در `tol` ثانیه می‌چسبند (رول: یکی دراز و آن‌یکی کوتاه) */
export function beatSnap(p: Project, beats: number[], tol = 0.25): { project: Project; snapped: number } {
  let q = p;
  let snapped = 0;
  for (const t0 of p.tracks) {
    if (t0.locked || t0.kind === "text") continue;
    const ids = [...t0.clips].sort((a, b) => a.at - b.at).map((c) => c.id);
    for (let i = 0; i + 1 < ids.length; i++) {
      const l = findClip(q, ids[i]);
      const r = findClip(q, ids[i + 1]);
      if (!l || !r || Math.abs(clipEnd(l.clip) - r.clip.at) > 0.06) continue;
      const cut = clipEnd(l.clip);
      const near = beats.reduce((best, b) => (Math.abs(b - cut) < Math.abs(best - cut) ? b : best), Infinity);
      if (!Number.isFinite(near) || Math.abs(near - cut) > tol || Math.abs(near - cut) < 0.02) continue;
      const next = rollEdit(q, ids[i], ids[i + 1], near);
      if (next !== q) { q = next; snapped++; }
    }
  }
  return { project: q, snapped };
}

// ───────────────────────────────────────────────────────── توالیِ تودرتو (Nested sequence)
export function seqLength(seq: Sequence): number {
  return Math.max(0, ...seq.tracks.flatMap((t) => t.clips.map(clipEnd)));
}
const seqHasAudio = (seq: Sequence): boolean =>
  seq.tracks.some((t) => !t.muted && t.kind !== "text" && t.clips.some((c) => isMedia(c) && (t.kind === "audio" || (c.kind === "video" && c.has_audio && c.audio_on && !c.freeze) || (isMedia(c) && c.ref.startsWith("seq:")))));

const isSeqRef = (ref: string) => ref.startsWith("seq:");
export const seqIdOf = (c: AnyClip | undefined | null): string | null => (c && isMedia(c) && isSeqRef(c.ref) ? c.ref.slice(4) : null);

/** قطعه‌های انتخاب‌شده (با جفت‌هایشان) را در یک توالیِ تازه می‌گذارد و یک قطعهٔ تودرتو جایشان می‌نشیند */
export function nestClips(p: Project, ids: string[], name = "توالیِ تودرتو"): { project: Project; seqId: string; clipId: string } | null {
  const pick = new Set(withLinked(p, ids));
  const found = p.tracks.flatMap((t) => t.clips.filter((c) => pick.has(c.id)).map((c) => ({ t, c })));
  if (!found.length) return null;
  const t0 = Math.min(...found.map((x) => x.c.at));
  const tracks: Track[] = [];
  for (const t of p.tracks) {
    const mine = t.clips.filter((c) => pick.has(c.id));
    if (!mine.length) continue;
    tracks.push({ id: uid("t"), kind: t.kind, name: t.name, muted: false, locked: false, role: t.role, caption: t.caption, gain_db: t.gain_db, pan: t.pan,
      clips: sortClips(mine.map((c) => ({ ...c, at: c.at - t0 }) as AnyClip)) });
  }
  if (!tracks.some((t) => t.kind === "video")) tracks.unshift({ id: uid("t"), kind: "video", name: "تصویر", muted: false, locked: false, clips: [] });
  const seq: Sequence = { name, tracks, format: { ...p.format } };
  const length = seqLength(seq);
  if (length < 0.1) return null;
  const seqId = uid("s");
  const stripped = mapTracks(p, (t) => ({ ...t, clips: t.clips.filter((c) => !pick.has(c.id)) }));
  const clipId = uid();
  const nested: MediaClip = {
    id: clipId, type: "media", ref: `seq:${seqId}`, label: name, kind: "video", at: t0, start: 0, end: length, src: length, opacity: 1, x: 0, y: 0, width: 1, height: 1,
    volume: 1, speed: 1, fit: "stretch", fade_in: 0, fade_out: 0, audio_on: true, has_audio: seqHasAudio(seq), effects: [], transition: null,
  };
  // روی پایین‌ترین ترکِ تصویرِ انتخاب‌شده؛ اگر جا نبود، ترکِ تصویرِ تازه
  let q: Project = { ...stripped, sequences: { ...(stripped.sequences ?? {}), [seqId]: seq } };
  let dest = q.tracks.find((t) => t.kind === "video" && !t.locked && found.some((x) => x.t.id === t.id) && !overlaps(t, t0, length));
  dest = dest ?? q.tracks.find((t) => t.kind === "video" && !t.locked && !overlaps(t, t0, length));
  if (!dest) {
    q = addTrack(q, "video");
    dest = q.tracks.filter((t) => t.kind === "video").slice(-1)[0];
  }
  const did = dest.id;
  q = mapTracks(q, (t) => (t.id === did ? { ...t, clips: sortClips([...t.clips, nested]) } : t));
  return { project: q, seqId, clipId };
}

/** نمایِ یک توالی به‌شکلِ «پروژه» (برای ویرایشِ درونِ آن با همین ابزارها). path خالی = خودِ پروژه. */
export function viewOf(root: Project, path: string[]): Project {
  let cur = root;
  for (const id of path) {
    const seq = cur.sequences?.[id] ?? root.sequences?.[id];
    if (!seq) return root;
    cur = { ...root, format: seq.format ?? root.format, tracks: seq.tracks, markers: [], inout: null, global_ops: [] };
  }
  return cur;
}

/** نتیجهٔ ویرایش در نما را برمی‌گرداند توی ریشه؛ طولِ توالی عوض شده باشد قطعه‌های تودرتوی آن (src و انتهای کامل) هم دنبالش می‌آیند */
export function writeView(root: Project, path: string[], view: Project): Project {
  if (!path.length) return view;
  const id = path[path.length - 1];
  const old = root.sequences?.[id];
  if (!old) return root;
  // قابِ توالی فقط وقتی ذخیره می‌شود که با قابِ پروژه فرق کند (یا قبلاً فرق داشته)؛ تنظیمِ خروجی همیشه مالِ ریشه است
  const sameFormat = JSON.stringify(view.format) === JSON.stringify(root.format);
  const seq: Sequence = { ...old, tracks: view.tracks, format: sameFormat && !old.format ? undefined : view.format };
  const oldLen = seqLength(old);
  const newLen = seqLength(seq);
  let q: Project = { ...root, export: view.export, sequences: { ...(view.sequences ?? root.sequences ?? {}), [id]: seq } };
  if (Math.abs(oldLen - newLen) > EPS) {
    const fixClip = (c: AnyClip): AnyClip => (isMedia(c) && c.ref === `seq:${id}` ? { ...c, src: newLen, end: Math.abs(c.end - oldLen) < 0.02 ? newLen : Math.min(c.end, newLen), has_audio: seqHasAudio(seq) } : c);
    q = mapTracks(q, (t) => ({ ...t, clips: t.clips.map(fixClip) }));
    const seqs: Record<string, Sequence> = {};
    for (const [sid, s] of Object.entries(q.sequences ?? {})) seqs[sid] = { ...s, tracks: s.tracks.map((t) => ({ ...t, clips: t.clips.map(fixClip) })) };
    q = { ...q, sequences: seqs };
  }
  return q;
}

/** بازکردنِ توالی داخلِ پروژه: قطعه‌های توالی با زمانِ درست روی ترک‌های تازه می‌نشینند (فقط وقتی قطعهٔ تودرتو دست‌نخورده است) */
export function unnestClip(p: Project, clipId: string): { project: Project; message?: string } {
  const f = findClip(p, clipId);
  const sid = seqIdOf(f?.clip);
  const seq = sid ? p.sequences?.[sid] : undefined;
  if (!f || !isMedia(f.clip) || !sid || !seq) return { project: p, message: "یک قطعهٔ تودرتو را انتخاب کنید." };
  const c = f.clip;
  const len = seqLength(seq);
  if (Math.abs(c.start) > EPS || Math.abs(c.end - len) > 0.05 || Math.abs((c.speed || 1) - 1) > EPS || (c.ramp?.length ?? 0) || c.reverse) {
    return { project: p, message: "این قطعهٔ تودرتو بریده یا کند/تند شده؛ برای بازکردن باید دست‌نخورده باشد." };
  }
  let q = mapTracks(p, (t) => (t.id === f.track.id ? { ...t, clips: t.clips.filter((x) => x.id !== c.id) } : t));
  const links = new Map<string, string>();
  for (const st of seq.tracks) {
    if (!st.clips.length) continue;
    q = addTrack(q, st.kind, st.role ?? "");
    const made = q.tracks.filter((t) => t.kind === st.kind).slice(-1)[0];
    const clips = st.clips.map((x) => {
      const copy = { ...x, id: uid(), at: x.at + c.at } as AnyClip;
      if (isMedia(copy) && copy.link) {
        if (!links.has(copy.link)) links.set(copy.link, uid("L"));
        copy.link = links.get(copy.link);
      }
      return copy;
    });
    q = mapTracks(q, (t) => (t.id === made.id ? { ...t, name: st.name || t.name, clips: sortClips(clips) } : t));
  }
  const { [sid]: _drop, ...rest } = q.sequences ?? {};
  void _drop;
  const stillUsed = Object.values(rest).some((s) => s.tracks.some((t) => t.clips.some((x) => seqIdOf(x) === sid))) || allClips(q).some((x) => seqIdOf(x) === sid);
  return { project: stillUsed ? q : { ...q, sequences: rest } };
}

// ───────────────────────────────────────────────────────── مولتی‌کم
export type AngleSource = { ref: string; label: string; duration: number; has_audio: boolean };

/** زاویه‌ای که در لحظهٔ t فیلم دارد و ترجیحاً `want` */
function coveringAngle(info: MulticamInfo, t: number, want?: number): number {
  const covers = (i: number) => t >= info.angles[i].offset - EPS && t < info.angles[i].offset + info.angles[i].duration - EPS;
  if (want !== undefined && want >= 0 && covers(want)) return want;
  const i = info.angles.findIndex((_a, k) => covers(k));
  return i >= 0 ? i : Math.max(0, want ?? 0);
}

export function multicamLength(info: MulticamInfo): number {
  return Math.max(0, ...info.angles.map((a) => a.offset + a.duration));
}

/** برش‌ها را مرتب و بی‌تکرار و روی زاویه‌هایی که فیلم دارند نگه می‌دارد؛ جایی که زاویهٔ فعلی تمام می‌شود خودش به زاویهٔ دیگر می‌پرد */
export function normalizeCuts(info: MulticamInfo): MulticamInfo["cuts"] {
  const total = multicamLength(info);
  const raw = [...info.cuts].filter((c) => c.t >= 0 && c.t < total && c.angle >= 0 && c.angle < info.angles.length).sort((a, b) => a.t - b.t);
  if (!raw.length || raw[0].t > EPS) raw.unshift({ t: 0, angle: raw[0]?.angle ?? 0 });
  const out: MulticamInfo["cuts"] = [];
  let cur = -1;
  for (let i = 0; i < raw.length; i++) {
    const seg0 = raw[i].t;
    const seg1 = i + 1 < raw.length ? raw[i + 1].t : total;
    let angle = coveringAngle(info, seg0, raw[i].angle);
    let t = seg0;
    while (t < seg1 - 0.05) {
      const a = info.angles[angle];
      const stop = Math.min(seg1, a.offset + a.duration);
      if (angle !== cur) { out.push({ t: Math.round(t * 1000) / 1000, angle }); cur = angle; }
      if (stop >= seg1 - 0.05) break;
      t = stop;
      angle = coveringAngle(info, t, undefined);
    }
  }
  return out;
}

/** ترکِ تصویر و صدای توالیِ مولتی‌کم را از روی برش‌ها دوباره می‌سازد */
export function rebuildMulticam(seq: Sequence): Sequence {
  const info = seq.multicam;
  if (!info) return seq;
  const cuts = normalizeCuts(info);
  const total = multicamLength(info);
  const video: AnyClip[] = [];
  cuts.forEach((cut, i) => {
    const t1 = i + 1 < cuts.length ? cuts[i + 1].t : total;
    const a = info.angles[cut.angle];
    const start = Math.max(0, cut.t - a.offset);
    const end = Math.min(a.duration, t1 - a.offset);
    if (end - start < 0.05) return;
    video.push({
      id: uid(), type: "media", ref: a.ref, label: a.label, kind: "video", at: cut.t, start, end, src: a.duration, opacity: 1, x: 0, y: 0, width: 1, height: 1,
      volume: 1, speed: 1, fit: "cover", fade_in: 0, fade_out: 0, audio_on: false, has_audio: a.has_audio, effects: [], transition: null,
    });
  });
  const audio: AnyClip[] = [];
  const src = info.audio >= 0 ? info.angles[info.audio] : null;
  if (src && src.has_audio) {
    audio.push({
      id: uid(), type: "media", ref: src.ref, label: `${src.label} (صدا)`, kind: "audio", at: src.offset, start: 0, end: src.duration, src: src.duration, opacity: 1,
      x: 0, y: 0, width: 1, height: 1, volume: 1, speed: 1, fit: "cover", fade_in: 0, fade_out: 0, audio_on: true, has_audio: true, effects: [], transition: null,
    });
  }
  const vt = seq.tracks.find((t) => t.kind === "video") ?? { id: uid("t"), kind: "video" as const, name: "زاویه‌ها", muted: false, locked: false, clips: [] };
  const at = seq.tracks.find((t) => t.kind === "audio") ?? { id: uid("t"), kind: "audio" as const, name: "صدا", muted: false, locked: false, role: "speech" as const, clips: [] };
  return { ...seq, multicam: { ...info, cuts }, tracks: [{ ...vt, clips: video }, { ...at, clips: audio }] };
}

/** دو یا چند ویدیو + آفستِ هم‌زمانی ⇒ یک توالیِ مولتی‌کم و یک قطعهٔ تودرتو در `at`. offsets به ثانیه نسبت به اولی (می‌تواند منفی باشد). */
export function createMulticam(p: Project, angles: AngleSource[], offsets: number[], at: number, audioAngle = 0): { project: Project; seqId: string; clipId: string } | null {
  if (angles.length < 2 || angles.length !== offsets.length) return null;
  const lo = Math.min(...offsets);
  const info: MulticamInfo = {
    angles: angles.map((a, i) => ({ ref: a.ref, label: a.label, offset: Math.round((offsets[i] - lo) * 1000) / 1000, duration: a.duration, has_audio: a.has_audio })),
    cuts: [{ t: 0, angle: 0 }], audio: angles[audioAngle]?.has_audio ? audioAngle : angles.findIndex((a) => a.has_audio),
  };
  const seq = rebuildMulticam({ name: "مولتی‌کم", tracks: [], format: { ...p.format }, multicam: info });
  const length = seqLength(seq);
  if (length < 0.1) return null;
  const seqId = uid("s");
  const clipId = uid();
  const nested: MediaClip = {
    id: clipId, type: "media", ref: `seq:${seqId}`, label: "مولتی‌کم", kind: "video", at, start: 0, end: length, src: length, opacity: 1, x: 0, y: 0, width: 1, height: 1,
    volume: 1, speed: 1, fit: "stretch", fade_in: 0, fade_out: 0, audio_on: true, has_audio: seqHasAudio(seq), effects: [], transition: null,
  };
  let q: Project = { ...p, sequences: { ...(p.sequences ?? {}), [seqId]: seq } };
  let dest = q.tracks.find((t) => t.kind === "video" && !t.locked && !overlaps(t, at, length));
  if (!dest) {
    q = addTrack(q, "video");
    dest = q.tracks.filter((t) => t.kind === "video").slice(-1)[0];
  }
  const did = dest.id;
  q = mapTracks(q, (t) => (t.id === did ? { ...t, clips: sortClips([...t.clips, nested]) } : t));
  return { project: q, seqId, clipId };
}

/** در لحظهٔ `t` (زمانِ خودِ توالی) به زاویهٔ `angle` برش بزن */
export function setAngleAt(p: Project, seqId: string, t: number, angle: number): { project: Project; message?: string } {
  const seq = p.sequences?.[seqId];
  const info = seq?.multicam;
  if (!seq || !info || angle < 0 || angle >= info.angles.length) return { project: p, message: "این توالی مولتی‌کم نیست." };
  const a = info.angles[angle];
  if (t < a.offset - EPS || t >= a.offset + a.duration - EPS) return { project: p, message: `«${a.label}» در این لحظه فیلم ندارد (از ${a.offset.toFixed(1)} تا ${(a.offset + a.duration).toFixed(1)} ثانیه).` };
  const cuts = info.cuts.filter((c) => Math.abs(c.t - t) > 0.05).concat({ t: Math.round(t * 1000) / 1000, angle });
  const next = rebuildMulticam({ ...seq, multicam: { ...info, cuts: cuts.sort((x, y) => x.t - y.t) } });
  return { project: { ...p, sequences: { ...p.sequences, [seqId]: next } } };
}

export function removeCutAt(p: Project, seqId: string, index: number): Project {
  const seq = p.sequences?.[seqId];
  if (!seq?.multicam || index <= 0) return p;
  const cuts = seq.multicam.cuts.filter((_c, i) => i !== index);
  return { ...p, sequences: { ...p.sequences, [seqId]: rebuildMulticam({ ...seq, multicam: { ...seq.multicam, cuts } }) } };
}

export function setMulticamAudio(p: Project, seqId: string, angle: number): Project {
  const seq = p.sequences?.[seqId];
  if (!seq?.multicam) return p;
  return { ...p, sequences: { ...p.sequences, [seqId]: rebuildMulticam({ ...seq, multicam: { ...seq.multicam, audio: angle } }) } };
}

// ───────────────────────────────────────────────────────── برای پیش‌نمایش: برگ‌های توالی‌های تودرتو روی خطِ زمانِ ریشه
/**
 * مونتاژگر خودش توالی‌ها را تو در تو می‌کشد؛ ولی element ِ ویدیو/صدای قطعه‌های درونِ آن‌ها باید با زمانِ ریشه هم‌گام شود و
 * موتورِ صدا فقط ترک‌های ریشه را می‌شناسد. این تابع نمونه‌ای از پروژه می‌سازد که برگ‌ها (با زمانِ ریشه، سرعتِ ترکیبی و بازهٔ پنجره) را
 * روی ترک‌های مجازی دارد. فقط برای قطعهٔ تودرتویی با سرعتِ ثابت و بدونِ وارونگی/ثابت‌کردن؛ بقیه بی‌صدا/بی‌همگام می‌مانند (پیش‌نمایشِ دقیق).
 */
const flatCache = new WeakMap<Project, Project>();

export function flattenForMedia(p: Project): Project {
  const hit = flatCache.get(p);
  if (hit) return hit;
  if (!p.sequences || !allClips(p).some((c) => seqIdOf(c))) {
    flatCache.set(p, p);
    return p;
  }
  const extra: Track[] = [];
  const lift = (n: MediaClip, k: number, b: number, depth: number, host: string) => {
    const seq = p.sequences?.[n.ref.slice(4)];
    if (!seq || depth > 3 || n.reverse || n.freeze || (n.ramp?.length ?? 0) >= 2) return;
    const sp = n.speed || 1;
    // زمانِ ریشه = b + k·(زمانِ پدر)،  زمانِ پدر = n.at + (محلی − n.start)/sp
    const k2 = k / sp;
    const b2 = b + k * (n.at - n.start / sp);
    for (const st of seq.tracks) {
      if (st.kind === "text") continue;
      const clips: AnyClip[] = [];
      for (const c of st.clips) {
        if (!isMedia(c)) continue;
        const lo = Math.max(c.at, n.start);
        const hi = Math.min(clipEnd(c), n.end);
        if (hi - lo < 0.02) continue;
        if (seqIdOf(c)) {
          lift(c, k2, b2, depth + 1, `${host}:${st.id}`);
          continue;
        }
        if (c.reverse || c.freeze || (c.ramp?.length ?? 0) >= 2) continue;
        const spC = c.speed || 1;
        const start = c.kind === "image" ? 0 : c.start + (lo - c.at) * spC;
        const end = c.kind === "image" ? (hi - lo) / k2 : start + (hi - lo) * spC;
        clips.push({ ...c, at: b2 + k2 * lo, start, end, speed: c.kind === "image" ? 1 : spC / k2, volume: c.volume * (n.volume ?? 1), fade_in: 0, fade_out: 0, transition: null, kf: undefined } as MediaClip);
      }
      if (clips.length) extra.push({ ...st, id: `${host}:${st.id}`, locked: false, clips });
    }
  };
  for (const t of p.tracks) for (const c of t.clips) if (isMedia(c) && seqIdOf(c)) lift(c, 1, 0, 1, `v${c.id}`);
  const out = extra.length ? { ...p, tracks: [...p.tracks, ...extra] } : p;
  flatCache.set(p, out);
  return out;
}

export const hasNested = (p: Project): boolean => allClips(p).some((c) => !!seqIdOf(c));
export { projectLength };
