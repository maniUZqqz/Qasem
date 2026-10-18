"use client";

import { useEffect, useRef, useState } from "react";

/**
 * هاله‌ی متحرک پشت بخش قهرمان — WebGL وقتی دستگاه می‌کِشد، CSS وقتی نه.
 *
 * چرا three.js نیاورده‌ایم: کاری که اینجا می‌کنیم یک مستطیل تمام‌صفحه است
 * با یک فرگمنت‌شیدر رویش. three.js برای همین کار ۶۰۰ کیلوبایت جاوااسکریپت
 * می‌آورد که ۹۹ درصدش — صحنه، دوربین، مش، متریال، لودر — اینجا مصرفی
 * ندارد. این فایل چند کیلوبایت است و همان نتیجه را می‌دهد.
 *
 * و چرا اصلاً شرطی است: مخاطب این سایت بیشتر با موبایل ایرانی می‌آید.
 * یک صحنه‌ی سه‌بعدی که روی اندروید میان‌رده دو ثانیه رندر را عقب بیندازد،
 * دقیقاً همان بازدیدکننده‌ای را می‌پراند که قرار بود جذب کند. پس:
 *
 *   • تا بعد از هیدریشن و در زمان بیکاری مرورگر اصلاً ساخته نمی‌شود —
 *     هیچ‌وقت جلوی LCP نمی‌ایستد.
 *   • saveData، هسته‌ی کم، یا نبود WebGL → کلاً بی‌خیال می‌شود.
 *   • prefers-reduced-motion → بی‌خیال می‌شود (نسخه‌ی CSS ساکن است).
 *   • بیرون از دید یا تبِ پنهان → حلقه می‌ایستد، نه اینکه در پس‌زمینه
 *     باتری بسوزاند.
 *
 * در هر حالتی که رد شود، `.mesh::before` در globals.css سر جایش است و
 * همان هاله را ساکن نشان می‌دهد. یعنی این کامپوننت هیچ‌وقت «نبودِ
 * پس‌زمینه» تولید نمی‌کند — فقط نسخه‌ی زنده‌اش را اضافه می‌کند.
 */

const VERT = `
attribute vec2 p;
void main() { gl_Position = vec4(p, 0.0, 1.0); }
`;

/* fbm سه‌اکتاوی روی نویز ساده. سه اکتاو کافی است: اکتاو چهارم روی این
   مقیاس دیده نمی‌شود ولی هزینه‌اش را می‌گیرد. */
const FRAG = `
precision mediump float;
uniform vec2  u_res;
uniform float u_t;
uniform vec3  u_c1;
uniform vec3  u_c2;
uniform vec3  u_c3;
uniform float u_alpha;

vec2 hash(vec2 p) {
  p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
  return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(dot(hash(i + vec2(0.0, 0.0)), f - vec2(0.0, 0.0)),
                 dot(hash(i + vec2(1.0, 0.0)), f - vec2(1.0, 0.0)), u.x),
             mix(dot(hash(i + vec2(0.0, 1.0)), f - vec2(0.0, 1.0)),
                 dot(hash(i + vec2(1.0, 1.0)), f - vec2(1.0, 1.0)), u.x), u.y);
}

float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 3; i++) { v += a * noise(p); p *= 2.02; a *= 0.5; }
  return v;
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_res;

  // نسبت تصویر: فاصله را در فضای هم‌مقیاس حساب می‌کنیم تا هاله‌ها روی
  // نمایشگر عریض بیضی نشوند. ولی *مرکز* هاله‌ها هم باید با همین ضریب
  // پخش شود، وگرنه هر سه در ناحیه‌ی ۰ تا ۱ می‌مانند — یعنی روی مانیتور
  // ۱۴۴۰ پیکسلی، همه‌شان در یک‌سومِ سمت چپ جمع می‌شوند.
  float ar = u_res.x / u_res.y;
  vec2 q = vec2(uv.x * ar, uv.y);
  vec2 c1 = vec2(0.22 * ar, 0.74);
  vec2 c2 = vec2(0.78 * ar, 0.30);
  vec2 c3 = vec2(0.52 * ar, 0.05);

  float t = u_t * 0.05;
  float n1 = fbm(q * 1.4 + vec2(t, t * 0.6));
  float n2 = fbm(q * 1.9 + vec2(-t * 0.8, t * 0.4) + n1);

  // شعاع با عرض صحنه بزرگ می‌شود، وگرنه روی صفحه‌ی پهن سه لکه‌ی جدا
  // دیده می‌شود به‌جای یک هاله‌ی پیوسته.
  float r = 0.42 * ar;
  float b1 = smoothstep(r,        0.0, distance(q + n1 * 0.34, c1));
  float b2 = smoothstep(r * 1.1,  0.0, distance(q + n2 * 0.32, c2));
  float b3 = smoothstep(r * 0.85, 0.0, distance(q + n1 * 0.28, c3));

  float sum = b1 + b2 + b3;
  vec3 col = (u_c1 * b1 + u_c2 * b2 + u_c3 * b3) / max(sum, 0.001);

  // محو به هر دو لبه: بالا تا روی هدر نیفتد، پایین تا به متن نچسبد.
  float fade = smoothstep(0.0, 0.35, uv.y) * smoothstep(1.0, 0.72, uv.y);
  float a = clamp(sum * u_alpha * fade, 0.0, 1.0);

  gl_FragColor = vec4(col, a);
}
`;

/** «#7c5cff» یا «rgb(124 92 255)» → [r, g, b] در بازه‌ی ۰ تا ۱. */
function toRgb(value: string, fallback: [number, number, number]): [number, number, number] {
  const hex = value.trim().match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const n = parseInt(hex[1], 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  const nums = value.match(/[\d.]+/g);
  if (nums && nums.length >= 3) {
    return [Number(nums[0]) / 255, Number(nums[1]) / 255, Number(nums[2]) / 255];
  }
  return fallback;
}

/** آیا این دستگاه و این کاربر، این افکت را می‌خواهند و می‌توانند؟ */
function shouldRender(): boolean {
  if (typeof window === "undefined") return false;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;

  const conn = (navigator as { connection?: { saveData?: boolean; effectiveType?: string } })
    .connection;
  if (conn?.saveData) return false;
  if (conn?.effectiveType && /(^|-)2g$/.test(conn.effectiveType)) return false;

  // hardwareConcurrency روی دستگاه‌های ضعیف کم است و روی بعضی مرورگرها
  // اصلاً گزارش نمی‌شود؛ نبودش را «نمی‌دانم» می‌گیریم نه «ضعیف».
  const cores = navigator.hardwareConcurrency;
  if (typeof cores === "number" && cores < 4) return false;

  if ((navigator as { deviceMemory?: number }).deviceMemory! < 4) return false;

  return true;
}

export default function AuroraCanvas() {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const [on, setOn] = useState(false);

  // تصمیم بعد از هیدریشن گرفته می‌شود تا رندر سمت سرور و سمت کلاینت
  // یکی باشند و هیچ چیزی جلوی اولین رنگ‌آمیزی را نگیرد.
  useEffect(() => {
    const idle =
      window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 300));
    const handle = idle(() => setOn(shouldRender()));
    return () => {
      if (window.cancelIdleCallback && typeof handle === "number") {
        window.cancelIdleCallback(handle);
      }
    };
  }, []);

  useEffect(() => {
    const canvas = ref.current;
    if (!on || !canvas) return;

    const gl = canvas.getContext("webgl", {
      alpha: true,
      antialias: false,
      depth: false,
      stencil: false,
      powerPreference: "low-power",
      failIfMajorPerformanceCaveat: true,
    });
    // نبودِ کانتکست یعنی همین: رد شو. نسخه‌ی CSS زیرش هست.
    if (!gl) return;

    const compile = (type: number, src: string) => {
      const sh = gl.createShader(type)!;
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      return gl.getShaderParameter(sh, gl.COMPILE_STATUS) ? sh : null;
    };

    const vs = compile(gl.VERTEX_SHADER, VERT);
    const fs = compile(gl.FRAGMENT_SHADER, FRAG);
    if (!vs || !fs) return;

    const prog = gl.createProgram()!;
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]), // یک مثلث بزرگ‌تر از صفحه
      gl.STATIC_DRAW,
    );
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(prog, "u_res");
    const uT = gl.getUniformLocation(prog, "u_t");
    const uAlpha = gl.getUniformLocation(prog, "u_alpha");

    // رنگ‌ها از همان توکن‌های CSS می‌آیند، پس تم روشن و تیره خود‌به‌خود
    // درست‌اند و اگر رنگ برند عوض شود اینجا چیزی دستی نمی‌ماند.
    const css = getComputedStyle(document.documentElement);
    gl.uniform3fv(
      gl.getUniformLocation(prog, "u_c1"),
      toRgb(css.getPropertyValue("--aurora-1"), [0.486, 0.361, 1]),
    );
    gl.uniform3fv(
      gl.getUniformLocation(prog, "u_c2"),
      toRgb(css.getPropertyValue("--aurora-2"), [0.133, 0.827, 0.933]),
    );
    gl.uniform3fv(
      gl.getUniformLocation(prog, "u_c3"),
      toRgb(css.getPropertyValue("--aurora-3"), [0.957, 0.443, 0.71]),
    );
    gl.uniform1f(uAlpha, Number(css.getPropertyValue("--aurora-alpha")) || 0.5);

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    // DPR سقف ۱.۵: بالاتر از این، روی رتینا چهار برابر پیکسل رنگ می‌شود
    // بدون اینکه هاله‌ی محو‌شده ذره‌ای بهتر دیده شود.
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const resize = () => {
      const w = Math.floor(canvas.clientWidth * dpr);
      const h = Math.floor(canvas.clientHeight * dpr);
      if (canvas.width === w && canvas.height === h) return;
      canvas.width = w;
      canvas.height = h;
      gl.viewport(0, 0, w, h);
      gl.uniform1f(uT, 0);
      gl.uniform2f(uRes, w, h);
    };
    resize();

    let raf = 0;
    let running = true;
    let t0 = performance.now();
    let elapsed = 0;

    const frame = (now: number) => {
      if (!running) return;
      elapsed += (now - t0) / 1000;
      t0 = now;
      resize();
      gl.uniform1f(uT, elapsed);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      raf = requestAnimationFrame(frame);
    };

    const start = () => {
      if (running) return;
      running = true;
      t0 = performance.now();
      raf = requestAnimationFrame(frame);
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(raf);
    };

    raf = requestAnimationFrame(frame);

    // بیرون از دید یا تب پنهان → نرندر. یک حلقه‌ی rAF که کسی نمی‌بیندش،
    // فقط باتری می‌خورد.
    const io = new IntersectionObserver(
      ([e]) => (e.isIntersecting && !document.hidden ? start() : stop()),
      { rootMargin: "120px" },
    );
    io.observe(canvas);

    const onVisibility = () => (document.hidden ? stop() : start());
    document.addEventListener("visibilitychange", onVisibility);

    const onResize = () => resize();
    window.addEventListener("resize", onResize, { passive: true });

    return () => {
      stop();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", onResize);
      gl.deleteProgram(prog);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      gl.deleteBuffer(buf);
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }, [on]);

  if (!on) return null;

  return (
    <canvas
      ref={ref}
      className="aurora-canvas"
      aria-hidden="true"
      // تزئینی محض: نه محتوایی دارد نه تعاملی.
    />
  );
}
