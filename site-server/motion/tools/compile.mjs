// Turns the user's TSX into a plain script (CommonJS wrapped in a factory) with sucrase.
//
//   node compile.mjs < code.tsx   ->  {"ok":true,"js":"window.__NM_USER_FACTORY=function(require,exports,module){...}"}
//                                  |  {"ok":false,"error":"...","line":N}
//
// The factory is later run by the page with its own `require` that serves only the allowed modules (react, remotion, ...).
import { transform } from "sucrase";

let src = "";
for await (const chunk of process.stdin) src += chunk;
try {
  const res = transform(src, { transforms: ["typescript", "jsx", "imports"], jsxRuntime: "automatic", production: true, disableESTransforms: false });
  const js = `window.__NM_USER_FACTORY=function(require,exports,module){"use strict";\n${res.code}\n};`;
  process.stdout.write(JSON.stringify({ ok: true, js }));
} catch (e) {
  const m = String(e && e.message ? e.message : e);
  const line = (m.match(/\((\d+):(\d+)\)/) || [])[1];
  process.stdout.write(JSON.stringify({ ok: false, error: m.slice(0, 600), line: line ? Number(line) : null }));
}
