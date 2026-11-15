#!/usr/bin/env node
/**
 * Fails the build when the JavaScript that is sent to visitors contains a
 * loopback address.
 *
 * Why this exists: NEXT_PUBLIC_API_BASE=http://127.0.0.1:8040 used to be inlined
 * into the contact form and the analytics client. A visitor's browser then
 * posted to *its own* localhost: not one lead was ever stored (0 rows), and
 * nothing on the server showed an error. See lib/publicApi.ts.
 *
 * Usage:  node scripts/check-static-no-localhost.mjs [dir ...]
 * Default directories: .next/static (what the browser downloads).
 * Runs automatically after `npm run build` (the `postbuild` script).
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const dirs = process.argv.slice(2);
if (dirs.length === 0) dirs.push(".next/static");

// A URL whose host is the machine itself. (Bare "localhost" words in library
// code are not URLs and are not flagged.)
const LOOPBACK = /https?:\/\/(?:127\.0\.0\.1|localhost|0\.0\.0\.0|\[::1\])(?::\d+)?/g;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const info = statSync(full);
    if (info.isDirectory()) yield* walk(full);
    else if (/\.(?:js|mjs|css|html|json|map)$/.test(name)) yield full;
  }
}

let bad = 0;
let scanned = 0;
for (const dir of dirs) {
  if (!existsSync(dir)) {
    console.error(`check-static-no-localhost: ${dir} does not exist (build first)`);
    process.exit(2);
  }
  for (const file of walk(dir)) {
    scanned += 1;
    const text = readFileSync(file, "utf8");
    const hits = [...new Set(text.match(LOOPBACK) ?? [])];
    if (hits.length) {
      bad += hits.length;
      console.error(`  ${file}: ${hits.join(", ")}`);
    }
  }
}

if (bad) {
  console.error(
    `\nFAILED: ${bad} loopback address(es) in the browser bundle. NEXT_PUBLIC_API_BASE must be empty\n` +
      `(same-origin) or a real public origin; the server-side address belongs in INTERNAL_API_BASE.`,
  );
  process.exit(1);
}
console.log(`check-static-no-localhost: ok (${scanned} files, no loopback address in the browser bundle)`);
