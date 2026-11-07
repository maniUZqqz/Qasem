/**
 * آزمونِ آپلودِ ادامه‌پذیر (بدونِ مرورگر): یک «سرورِ ساختگی» که تکه‌ها را می‌گیرد و می‌شود قطع و خراب‌اش کرد.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r5-upload.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r5-upload.test.mjs
 *   node /tmp/video-r5-upload.test.mjs
 */
import assert from "node:assert/strict";

import {
  Env, HttpFail, MAX_ATTEMPTS, MIN_CHUNK, Transport, UploadCancelled, UploadFailed, UploadState, describeFailure, fileKey, fmtBytes, fmtEta, runUpload,
} from "../src/features/content/video/upload";

const results: { name: string; ok: boolean; err?: string }[] = [];
async function check(name: string, fn: () => Promise<void>) {
  try {
    await fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 4).join("\n")}` : String(e) });
  }
}

class FakeFile extends Blob {
  name = "فیلم.mp4";
  lastModified = 1700000000000;
  constructor(public n: number) {
    super([new Uint8Array(n)]);
  }
}

type Hooks = {
  /** called before each chunk attempt: return an error to throw, or "lose" to store the data but lose the answer */
  onChunk?: (n: number, offset: number, attempt: number) => HttpFail | "lose" | undefined;
  sessionAtStart?: number;
  startError?: HttpFail;
  finishError?: HttpFail;
};
function fake(hooks: Hooks = {}) {
  const log = { starts: 0, chunks: [] as { offset: number; size: number }[], statuses: 0, finishes: 0, cancelled: 0, stored: hooks.sessionAtStart ?? 0, attempts: 0 };
  let tick = 0;
  const transport: Transport<{ id: number }> = {
    start: async () => {
      log.starts++;
      if (hooks.startError) throw hooks.startError;
      return { upload_id: "u1", received: log.stored, chunk: 1024 * 1024, chunk_max: 4 * 1024 * 1024, resumed: log.stored > 0 };
    },
    chunk: async (_uid, offset, blob, signal, onBytes) => {
      if (signal.aborted) throw new UploadCancelled();
      log.attempts++;
      const verdict = hooks.onChunk?.(tick++, offset, log.attempts);
      log.chunks.push({ offset, size: blob.size });
      onBytes(blob.size / 2);
      if (verdict instanceof HttpFail) throw verdict;
      if (offset > log.stored) throw new HttpFail(409, "gap", "gap", log.stored);
      log.stored = Math.max(log.stored, offset + blob.size);
      if (verdict === "lose") throw new HttpFail(0, "");
      return { received: log.stored };
    },
    status: async () => {
      log.statuses++;
      return { received: log.stored };
    },
    finish: async () => {
      log.finishes++;
      if (hooks.finishError) throw hooks.finishError;
      return { video: { id: 7 }, job_id: 99 };
    },
    cancel: async () => {
      log.cancelled++;
    },
  };
  return { transport, log };
}

function env(over: Partial<Env> & { sleeps?: number[] } = {}) {
  let t = 0;
  const sleeps: number[] = over.sleeps ?? [];
  const e: Env = {
    sleep: async (ms) => {
      sleeps.push(ms);
    },
    online: () => true,
    waitOnline: async () => undefined,
    now: () => (t += 500),                                  // every chunk "takes" half a second
    ...over,
  };
  return { env: e, sleeps };
}

const run = (file: FakeFile, f: ReturnType<typeof fake>, e = env(), signal = new AbortController().signal) => {
  const states: UploadState[] = [];
  const p = runUpload(file as never, { transport: f.transport, env: e.env, signal, onState: (s) => states.push(s) });
  return { p, states };
};

await check("a file goes up in order, the last state is done, finish is called once", async () => {
  const f = fake();
  const { p, states } = run(new FakeFile(5 * 1024 * 1024 + 123), f);
  const r = await p;
  assert.deepEqual(r, { video: { id: 7 }, job_id: 99 });
  assert.equal(f.log.stored, 5 * 1024 * 1024 + 123);
  assert.equal(f.log.finishes, 1);
  assert.equal(states[states.length - 1].phase, "done");
  assert.ok(states.every((s, i) => i === 0 || s.sent >= states[i - 1].sent - 1), "progress never goes backwards by more than rounding");
  const offsets = f.log.chunks.map((c) => c.offset);
  assert.deepEqual(offsets, [...offsets].sort((a, b) => a - b));
});

await check("chunk size grows on a fast line (up to the server's maximum)", async () => {
  const f = fake();
  await run(new FakeFile(30 * 1024 * 1024), f).p;
  const sizes = f.log.chunks.map((c) => c.size);
  assert.ok(sizes[sizes.length - 2] > sizes[0], sizes.join(","));
  assert.ok(Math.max(...sizes) <= 4 * 1024 * 1024);
});

await check("a failed piece is retried with backoff, SMALLER, and the upload still completes", async () => {
  const f = fake({ onChunk: (_n, _o, attempt) => (attempt <= 3 ? new HttpFail(503, "") : undefined) });
  const e = env();
  const { p, states } = run(new FakeFile(3 * 1024 * 1024), f, e);
  await p;
  assert.equal(f.log.stored, 3 * 1024 * 1024);
  assert.deepEqual(e.sleeps.slice(0, 3), [1000, 2000, 4000]);
  const first = f.log.chunks.slice(0, 4).map((c) => c.size);
  assert.ok(first[3] < first[0], `piece shrank after failures: ${first}`);
  const retrying = states.find((s) => s.phase === "retrying")!;
  assert.match(retrying.message, /تلاشِ دوباره \([۰-۹]+ از ۱۰\)/);
});

await check("a lost ANSWER does not re-send what already landed (it asks the server first)", async () => {
  const f = fake({ onChunk: (n) => (n === 1 ? "lose" : undefined) });
  await run(new FakeFile(4 * 1024 * 1024), f).p;
  assert.equal(f.log.stored, 4 * 1024 * 1024);
  assert.ok(f.log.statuses >= 1);
  const offsets = f.log.chunks.map((c) => c.offset);
  assert.equal(new Set(offsets).size, offsets.length, `no offset was sent twice: ${offsets}`);
});

await check("when the line is down it waits and continues without spending attempts", async () => {
  let up = true;
  let waited = 0;
  const f = fake({ onChunk: (n) => { if (n === 1) up = false; return n === 1 ? new HttpFail(0, "") : undefined; } });
  const e = env({ online: () => up, waitOnline: async () => { waited++; up = true; } });
  const { p, states } = run(new FakeFile(3 * 1024 * 1024), f, e);
  await p;
  assert.equal(f.log.stored, 3 * 1024 * 1024);
  assert.ok(waited >= 1);
  const off = states.find((s) => s.phase === "offline")!;
  assert.match(off.message, /اینترنت قطع است.*خودکار ادامه/);
});

await check("a restart from a half-sent session reports the percentage it resumes from", async () => {
  const f = fake({ sessionAtStart: 2 * 1024 * 1024 });
  const { p, states } = run(new FakeFile(4 * 1024 * 1024), f);
  await p;
  assert.equal(f.log.chunks[0].offset, 2 * 1024 * 1024, "does not re-send what the server has");
  assert.equal(states.find((s) => s.resumedFrom !== null)!.resumedFrom, 50);
});

await check("a gap (409) makes it jump to the server's offset", async () => {
  let sent = 0;
  const f = fake({ onChunk: (n) => { sent++; return undefined; } });
  f.log.stored = 1024 * 1024;                              // the server has more than the first start said
  const orig = f.transport.start;
  f.transport.start = async (b) => ({ ...(await orig(b)), received: 0 });
  await run(new FakeFile(3 * 1024 * 1024), f).p;
  assert.equal(f.log.stored, 3 * 1024 * 1024);
  assert.ok(sent >= 2);
});

await check("an expired session (404) starts over once, then succeeds", async () => {
  let first = true;
  const f = fake();
  const origChunk = f.transport.chunk;
  f.transport.chunk = async (uid, offset, blob, signal, onBytes) => {
    if (first) { first = false; throw new HttpFail(404, "gone", "gone"); }
    return origChunk(uid, offset, blob, signal, onBytes);
  };
  await run(new FakeFile(2 * 1024 * 1024), f).p;
  assert.equal(f.log.starts, 2);
  assert.equal(f.log.stored, 2 * 1024 * 1024);
});

await check("a refusal with a Persian message is final and shown as it is", async () => {
  const f = fake({ onChunk: () => new HttpFail(400, "حجمِ فرستاده‌شده از اندازهٔ اعلام‌شدهٔ فایل بیشتر شد", "overflow") });
  await assert.rejects(run(new FakeFile(2 * 1024 * 1024), f).p, (e: unknown) => e instanceof UploadFailed && /بیشتر شد/.test(e.message) && e.code === "overflow");
  assert.equal(f.log.attempts, 1, "no pointless retries for a final refusal");
  const g = fake({ startError: new HttpFail(400, "این فرمت پذیرفته نمی‌شود.", "wrong_type") });
  await assert.rejects(run(new FakeFile(10), g).p, (e: unknown) => e instanceof UploadFailed && e.code === "wrong_type");
});

await check("after MAX_ATTEMPTS bad tries it gives up with advice, and nothing is deleted on the server", async () => {
  const f = fake({ onChunk: () => new HttpFail(502, "") });
  await assert.rejects(run(new FakeFile(2 * 1024 * 1024), f).p, (e: unknown) => e instanceof UploadFailed && e.code === "gave_up" && /دوباره انتخاب کنید/.test(e.message));
  assert.equal(f.log.attempts, MAX_ATTEMPTS);
  assert.equal(f.log.cancelled, 0);
});

await check("an nginx-style 413 shrinks the piece fast", async () => {
  const f = fake({ onChunk: (_n, _o, a) => (a === 1 ? new HttpFail(413, "") : undefined) });
  await run(new FakeFile(3 * 1024 * 1024), f).p;
  const s = f.log.chunks.map((c) => c.size);
  assert.ok(s[1] <= s[0] / 4 + 1, s.join(","));
});

await check("cancelling stops it and says so", async () => {
  const ctl = new AbortController();
  const f = fake({ onChunk: (n) => { if (n === 1) ctl.abort(); return undefined; } });
  await assert.rejects(run(new FakeFile(8 * 1024 * 1024), f, env(), ctl.signal).p, (e: unknown) => e instanceof UploadCancelled);
  assert.equal(f.log.finishes, 0);
});

await check("if finish says pieces are missing it goes round again and then finishes", async () => {
  let n = 0;
  const f = fake();
  const orig = f.transport.finish;
  f.transport.finish = async (u) => {
    if (n++ === 0) { f.log.stored = 1000; throw new HttpFail(409, "incomplete", "incomplete", 1000); }
    return orig(u);
  };
  const r = await run(new FakeFile(2 * 1024 * 1024), f).p;
  assert.equal(r.job_id, 99);
  assert.equal(f.log.stored, 2 * 1024 * 1024);
});

await check("a finish failure that is final (not a video) is reported in Persian", async () => {
  const f = fake({ finishError: new HttpFail(400, "این فایل ویدیوی سالم نیست (خراب یا ناقص است).", "not_video") });
  await assert.rejects(run(new FakeFile(1024), f).p, (e: unknown) => e instanceof UploadFailed && e.code === "not_video" && /سالم نیست/.test(e.message));
});

await check("helpers: failure wording, key, sizes, ETA", async () => {
  assert.equal(describeFailure(new HttpFail(0, "")).retry, true);
  assert.equal(describeFailure(new HttpFail(503, "")).retry, true);
  assert.equal(describeFailure(new HttpFail(403, "اجازه ندارید")).retry, false);
  assert.equal(describeFailure(new Error("x")).code, "network");
  assert.equal(fileKey({ name: "a.mp4", size: 5, lastModified: 9 }), "a.mp4:5:9");
  assert.equal(fmtBytes(10 * 1024 * 1024), "۱۰٫۰ مگابایت");
  assert.equal(fmtBytes(300 * 1024), "۳۰۰ کیلوبایت");
  assert.equal(fmtEta(3), "چند ثانیه");
  assert.equal(fmtEta(60), "۶۰ ثانیه");
  assert.equal(fmtEta(600), "۱۰ دقیقه");
  assert.equal(fmtEta(null), "");
  assert.ok(MIN_CHUNK >= 64 * 1024);
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err.replace(/\n/g, "\n     ")}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
