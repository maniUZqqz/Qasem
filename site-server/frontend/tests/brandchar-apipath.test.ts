/**
 * «شخصیتِ برند»: نشانیِ دانلودی که سرور می‌دهد (/api/v1/stores/...) باید پیش از رفتن به کلاینتِ پنل (که خودش baseURL=/api/v1 دارد) بریده شود؛
 * وگرنه /api/v1/api/v1/... و ۴۰۴ می‌شد (ایرادِ بازبینیِ ۱۱/۱۷: SVG، PNG، PDF و گالری دانلود نمی‌شدند).
 *
 *   cd frontend && node_modules/.bin/esbuild tests/brandchar-apipath.test.ts --bundle --platform=node --format=cjs --outfile=/tmp/brandchar-apipath.test.cjs
 *   node /tmp/brandchar-apipath.test.cjs
 */
import assert from "node:assert/strict";

import { apiPath } from "../src/features/brandchar/api";

const dl = "/api/v1/stores/34/brand-character/characters/1/renders/31/download/";
assert.equal(apiPath(dl), "/stores/34/brand-character/characters/1/renders/31/download/");
assert.equal(apiPath("http://87.107.160.17:8040" + dl), "/stores/34/brand-character/characters/1/renders/31/download/");
assert.equal(apiPath("/stores/34/brand-character/export/"), "/stores/34/brand-character/export/", "نشانیِ بدونِ پیشوند دست نمی‌خورد");
assert.equal(apiPath("/api/v10/x/"), "/api/v10/x/", "فقط پیشوندِ دقیقِ /api/v1/ بریده می‌شود");
assert.equal(apiPath("/stores/1/api/v1/x/"), "/stores/1/api/v1/x/", "فقط از ابتدای نشانی");
assert.ok(!("/api/v1" + apiPath(dl)).includes("/api/v1/api/v1"));
console.log("brandchar apiPath: OK");
