# deploy/c21 — React/Tailwind component converter (server side)

Turns a public React/Tailwind component (21st.dev catalogue, open licence only) into a static, sanitised, RTL-ready block of the site builder.
Full description (Persian): `docs/c21-crawler.md`.

| file | what |
|---|---|
| `convert.mjs` | esbuild (bundle) + react-dom/server (render) + Tailwind v4 compile API (only the used utilities, shadcn colours mapped to the site theme) + postcss (scope under `.nbc21-<key>`, unwrap `@layer`, rename keyframes, drop anything that loads files, physical -> logical properties for RTL) |
| `shims.mjs` | safe stand-ins for `next/*`, `framer-motion` (-> static elements), `cn`, and the shadcn/ui primitives (MIT) built on the Radix packages |
| `extras.css` | the animations library components usually add to `tailwind.config.js` (marquee, fade-up, accordion, ...) |
| `rtl_check.py` | Chromium check at 390 and 1280 px with `dir=rtl` (sideways scroll, escaping elements); used by `apps/projects/builder/c21_rtl.py` |
| `install.sh` | installs everything into `/opt/nm-c21` (idempotent, outside the panel's `node_modules`), then converts a one-line component as a smoke test |
| `package.json` | pinned versions (Tailwind 4.1.14, esbuild 0.25.10, React 18.3.1, lucide-react, Radix, ...) |

    bash deploy/c21/install.sh                 # Node 20+, npm registry
    cd backend && ../venv/bin/python manage.py c21_pipeline --only dillionverma/magic-ui    # convert one library by hand

The browser used by `rtl_check.py` is whatever `NM_C21_PLAYWRIGHT_PY` points at (default `/opt/up3d-uitest/venv/bin/python`, with `PLAYWRIGHT_BROWSERS_PATH`);
without it the RTL check says "skipped" and conversion goes on.

Licences: shadcn/ui primitives (MIT), Radix UI (MIT), lucide-react (ISC), Tailwind CSS (MIT), esbuild (MIT), React (MIT), postcss (MIT), tailwind-merge (MIT), class-variance-authority (Apache-2.0), clsx (MIT).
Converted components keep the licence and copyright of their upstream repository in their record (`source.license`, `source.copyright`).
