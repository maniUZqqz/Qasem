/**
 * آزمونِ ضبط با میکروفون: روشن/خاموش‌شدن بر پایهٔ https، قالبِ فایل، نامِ فایل و پیام‌های خطا.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r4-mic.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r4-mic.test.mjs
 *   node /tmp/video-r4-mic.test.mjs
 */
import assert from "node:assert/strict";

import {
  MAX_RECORD_SECONDS, MIC_NEEDS_HTTPS, MIC_NO_BROWSER, micErrorText, micSupport, pickMime, recordingFileName,
} from "../src/features/content/video/manual/micRecorder";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

const good = { isSecureContext: true, navigator: { mediaDevices: { getUserMedia: () => null } }, MediaRecorder: class {} };

check("on an http address the button is off and says what it waits for", () => {
  const r = micSupport({ ...good, isSecureContext: false });
  assert.equal(r.ok, false);
  assert.equal(r.reason, MIC_NEEDS_HTTPS);
  assert.ok(r.reason.includes("وقتی دامنه و https وصل شد فعال می‌شود"), r.reason);
});

check("secure page + microphone API + MediaRecorder = on", () => {
  assert.deepEqual(micSupport(good), { ok: true, reason: "" });
});

check("secure page but an old browser = off with a different reason", () => {
  assert.equal(micSupport({ ...good, MediaRecorder: undefined }).reason, MIC_NO_BROWSER);
  assert.equal(micSupport({ ...good, navigator: {} }).reason, MIC_NO_BROWSER);
  assert.equal(micSupport({ isSecureContext: true }).ok, false);
});

check("https is checked first (an insecure page with the API still stays off)", () => {
  assert.equal(micSupport({ ...good, isSecureContext: undefined }).reason, MIC_NEEDS_HTTPS);
});

check("mime choice follows what the browser supports (Chrome webm, Safari mp4)", () => {
  assert.equal(pickMime((t) => t.startsWith("audio/webm")), "audio/webm;codecs=opus");
  assert.equal(pickMime((t) => t === "audio/mp4"), "audio/mp4");
  assert.equal(pickMime((t) => t.startsWith("audio/ogg")), "audio/ogg;codecs=opus");
  assert.equal(pickMime(() => false), "");
  assert.equal(pickMime(() => { throw new Error("x"); }), "");
});

check("file name carries a timestamp and the right extension", () => {
  const d = new Date(2026, 10, 5, 9, 8, 7);
  assert.equal(recordingFileName("audio/webm;codecs=opus", d), "voice-20261105-090807.webm");
  assert.equal(recordingFileName("audio/mp4", d), "voice-20261105-090807.m4a");
  assert.equal(recordingFileName("audio/ogg", d), "voice-20261105-090807.ogg");
});

check("browser errors become Persian sentences a person can act on", () => {
  assert.ok(micErrorText({ name: "NotAllowedError" }).includes("مجاز"));
  assert.ok(micErrorText({ name: "NotFoundError" }).includes("میکروفونی پیدا نشد"));
  assert.ok(micErrorText({ name: "NotReadableError" }).includes("در دسترس نیست"));
  assert.ok(micErrorText(new Error("weird")).includes("دوباره"));
  assert.ok(micErrorText(null).length > 10);
});

check("a recording is capped", () => {
  assert.equal(MAX_RECORD_SECONDS, 300);
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
