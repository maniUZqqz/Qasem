/**
 * فضای کارِ ویدیو: با اسکوپِ باز، قابِ پیش‌نمایش نباید زیرِ اسکوپ و نوارِ پخش له شود (۱۴۰۵/۰۸/۲۴؛ روی ۷۶۸ پیکسل قاب ۱۶ پیکسل بود).
 * خودِ چیدمان در مرورگر اندازه‌گیری شد؛ این آزمون فقط نگه می‌دارد که قاعده‌ها در workspace.css باقی بمانند.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/editor-scopes-layout.test.ts --bundle --platform=node --format=esm --outfile=/tmp/editor-scopes-layout.test.mjs
 *   node /tmp/editor-scopes-layout.test.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(process.cwd(), "src/features/content/video/manual/workspace.css"), "utf-8");

// the scopes panel shrinks with the screen height
assert.match(css, /\.vw-scopes\s*\{[^}]*max-height:\s*clamp\(\s*88px,\s*17vh,\s*230px\s*\)/);
// the monitor frame keeps a minimum height and the column can scroll
assert.match(css, /\.vw-stage\s*\{\s*min-height:\s*140px/);
assert.match(css, /\.vw-monitor\s*\{\s*overflow-y:\s*auto/);
// the timeline is capped while the scopes are open, and not on a phone
assert.match(css, /\.vw-grid:has\(\.vw-scopes\)\s+\.vw-timeline\s*\{\s*max-height:\s*34vh/);
assert.match(css, /max-width:\s*1000px\)\s*\{\s*\.vw-grid:has\(\.vw-scopes\)\s+\.vw-timeline\s*\{\s*max-height:\s*none/);

console.log("editor-scopes-layout: ok");
