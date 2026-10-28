import type { CSSProperties } from "react";

import type { Overlay, Shot } from "./api";
import { fa } from "./api";

/**
 * نقشهٔ مرجعِ هر زاویه/نما + «تمرینِ کوتاه» (انیمیشن) + فلش‌های روی دوربینِ زنده.
 *
 * نمای بالا: محصول وسط، گوشی روی دایره‌ای دورش (پایینِ نقشه = روبه‌روی محصول، راستِ نقشه = راستِ تو).
 * نمای کنار: گوشی روی کمانی از هم‌سطح تا بالای سر. انیمیشن همان حرکتی است که باید انجام دهی.
 */

const CSS = `
@keyframes sg-orbit-r { 0%,12% { transform: rotate(0deg) } 70%,100% { transform: rotate(var(--sg-deg)) } }
@keyframes sg-push { 0%,10% { transform: translateY(0) } 75%,100% { transform: translateY(var(--sg-push)) } }
@keyframes sg-pan { 0%,100% { transform: rotate(-22deg) } 50% { transform: rotate(22deg) } }
@keyframes sg-tilt { 0%,100% { transform: rotate(18deg) } 50% { transform: rotate(-18deg) } }
@keyframes sg-reveal { 0%,20% { transform: translateX(0); opacity: 1 } 80%,100% { transform: translateX(46px); opacity: .25 } }
@keyframes sg-hand { 0%,100% { transform: translate(0,0) rotate(0) } 50% { transform: translate(6px,-6px) rotate(20deg) } }
@keyframes sg-rise { 0%,12% { transform: rotate(0deg) } 70%,100% { transform: rotate(var(--sg-pitch)) } }
@keyframes sg-blink { 0%,100% { opacity: .35 } 50% { opacity: 1 } }
@keyframes sg-arrow { 0%,100% { transform: translate(0,0) } 50% { transform: translate(var(--sg-dx), var(--sg-dy)) } }
.sg-anim { transform-box: view-box; }
`;

let injected = false;
function useCss() {
  if (!injected && typeof document !== "undefined") {
    const el = document.createElement("style");
    el.textContent = CSS;
    document.head.appendChild(el);
    injected = true;
  }
}

const R = { close: 34, medium: 50, far: 64 } as const;

function Phone({ x, y, rot }: { x: number; y: number; rot: number }) {
  return (
    <g transform={`translate(${x} ${y}) rotate(${rot})`}>
      <rect x={-6} y={-10} width={12} height={20} rx={2.5} fill="var(--brand)" />
      <circle cx={0} cy={-6} r={1.6} fill="#fff" />
    </g>
  );
}

/** نمای بالا + نمای کنار، با تمرینِ متحرک وقتی `animate`. */
export function ShotDiagram({ shot, animate = true, size = 300 }: { shot: Shot; animate?: boolean; size?: number }) {
  useCss();
  const o: Overlay = shot.overlay;
  const r = R[o.distance] ?? 50;
  const cx = 75;
  const cy = 78;
  const isVideo = shot.kind === "video";
  const move = isVideo ? shot.move : "";
  // جای گوشی در نمای بالا (درجه، ۰ = روبه‌رو/پایین، مثبت = راست)
  const yaw = isVideo ? 0 : o.yaw;
  const rad = (yaw * Math.PI) / 180;
  const px = cx + r * Math.sin(rad);
  const py = cy + r * Math.cos(rad);
  const facing = -yaw; // رو به محصول
  const orbitDeg = isVideo && move === "orbit" ? (shot.direction === "left" ? 1 : -1) * (shot.degrees ?? 90) : 0;
  const photoDeg = !isVideo && yaw ? -yaw : 0;
  const groupStyle: CSSProperties | undefined = !animate
    ? undefined
    : move === "orbit" || (!isVideo && photoDeg)
      ? ({
          transformOrigin: `${cx}px ${cy}px`,
          animation: `sg-orbit-r ${isVideo ? Math.max(2.5, shot.duration) : 2.6}s ease-in-out infinite`,
          ["--sg-deg" as string]: `${move === "orbit" ? orbitDeg : photoDeg}deg`,
        } as CSSProperties)
      : move === "push_in" || move === "pull_out" || o.arrow === "in" || o.arrow === "out"
        ? ({
            animation: `sg-push ${isVideo ? Math.max(2.5, shot.duration) : 2.4}s ease-in-out infinite`,
            ["--sg-push" as string]: `${move === "pull_out" || o.arrow === "out" ? 20 : -22}px`,
          } as CSSProperties)
        : undefined;
  // در حالتِ تمرینِ عکسِ زاویه‌دار، گوشی از روبه‌رو شروع می‌کند و به زاویه می‌رسد
  const startX = !isVideo && photoDeg && animate ? cx : px;
  const startY = !isVideo && photoDeg && animate ? cy + r : py;
  const startRot = !isVideo && photoDeg && animate ? 0 : facing;

  // نمای کنار
  const sx = 225;
  const sy = 112;
  const pitch = isVideo ? 0 : o.pitch;
  const pr = 52;
  const prad = (pitch * Math.PI) / 180;
  const phx = sx - pr * Math.cos(prad);
  const phy = sy - 14 - pr * Math.sin(prad);
  const sideStyle: CSSProperties | undefined =
    animate && !isVideo && pitch >= 45
      ? ({
          transformOrigin: `${sx}px ${sy - 14}px`,
          animation: "sg-rise 2.6s ease-in-out infinite",
          ["--sg-pitch" as string]: `${pitch}deg`,
        } as CSSProperties)
      : undefined;
  const sideStartX = sideStyle ? sx - pr : phx;
  const sideStartY = sideStyle ? sy - 14 : phy;
  const sideRot = sideStyle ? 90 : 90 + pitch;

  return (
    <svg viewBox="0 0 300 170" width="100%" style={{ maxWidth: size }} role="img" aria-label={`نقشهٔ ${shot.title}`}>
      <rect x={0} y={0} width={300} height={170} rx={14} fill="var(--surface-2)" />
      <text x={75} y={16} textAnchor="middle" fontSize={10} fill="var(--text-3)">
        از بالا
      </text>
      <text x={225} y={16} textAnchor="middle" fontSize={10} fill="var(--text-3)">
        از کنار
      </text>
      <line x1={150} y1={24} x2={150} y2={156} stroke="var(--line)" />
      {/* نمای بالا */}
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--line-strong)" strokeDasharray="3 4" />
      <rect x={cx - 11} y={cy - 11} width={22} height={22} rx={5} fill="var(--text-2)" />
      <text x={cx} y={cy + r + 18} textAnchor="middle" fontSize={8.5} fill="var(--text-3)">
        روبه‌رو
      </text>
      {isVideo && move === "orbit" && (
        <path
          d={arcPath(cx, cy, r, 0, -orbitDeg)}
          fill="none"
          stroke="var(--brand)"
          strokeWidth={2.5}
          strokeLinecap="round"
          markerEnd="url(#sg-head)"
          opacity={0.7}
        />
      )}
      {!isVideo && yaw !== 0 && (
        <path d={arcPath(cx, cy, r, 0, yaw)} fill="none" stroke="var(--brand)" strokeWidth={2.5} opacity={0.6} />
      )}
      <defs>
        <marker id="sg-head" viewBox="0 0 10 10" refX={5} refY={5} markerWidth={5} markerHeight={5} orient="auto-start-reverse">
          <path d="M0 0 10 5 0 10z" fill="var(--brand)" />
        </marker>
      </defs>
      <g className="sg-anim" style={groupStyle}>
        <g
          className="sg-anim"
          style={
            animate && move === "pan"
              ? { transformOrigin: `${startX}px ${startY}px`, animation: "sg-pan 2.8s ease-in-out infinite" }
              : undefined
          }
        >
          <Phone x={startX} y={startY} rot={startRot} />
        </g>
      </g>
      {isVideo && move === "reveal" && (
        <rect
          x={cx - 18}
          y={cy + r - 30}
          width={36}
          height={8}
          rx={3}
          fill="var(--warn)"
          className="sg-anim"
          style={animate ? { animation: `sg-reveal ${Math.max(2.5, shot.duration)}s ease-in-out infinite` } : undefined}
        />
      )}
      {isVideo && move === "hand" && (
        <g className="sg-anim" style={animate ? { animation: "sg-hand 1.6s ease-in-out infinite" } : undefined}>
          <circle cx={cx + 20} cy={cy - 6} r={7} fill="var(--warn)" opacity={0.85} />
        </g>
      )}
      {/* نمای کنار */}
      <line x1={160} y1={sy} x2={292} y2={sy} stroke="var(--line-strong)" />
      <rect x={sx - 9} y={sy - 28} width={18} height={28} rx={4} fill="var(--text-2)" />
      <path d={`M ${sx - pr} ${sy - 14} A ${pr} ${pr} 0 0 1 ${sx} ${sy - 14 - pr}`} fill="none" stroke="var(--line-strong)" strokeDasharray="3 4" />
      <g className="sg-anim" style={sideStyle}>
        <g
          className="sg-anim"
          style={
            animate && move === "tilt"
              ? { transformOrigin: `${sideStartX}px ${sideStartY}px`, animation: "sg-tilt 2.8s ease-in-out infinite" }
              : undefined
          }
        >
          <Phone x={sideStartX} y={sideStartY} rot={sideRot} />
        </g>
      </g>
      <text x={sx - pr - 4} y={sy + 16} textAnchor="middle" fontSize={8.5} fill="var(--text-3)">
        هم‌سطح
      </text>
      <text x={sx} y={sy - 14 - pr - 6} textAnchor="middle" fontSize={8.5} fill="var(--text-3)">
        بالای سر
      </text>
      {isVideo && (
        <text x={150} y={166} textAnchor="middle" fontSize={9} fill="var(--text-2)">
          {fa(shot.duration)} ثانیه
          {shot.move === "orbit" ? ` — ${fa(shot.degrees ?? 90)} درجه` : ""}
        </text>
      )}
    </svg>
  );
}

function arcPath(cx: number, cy: number, r: number, fromDeg: number, toDeg: number): string {
  // ۰ درجه = پایین (روبه‌رو)، مثبت = راست
  const p = (d: number) => {
    const a = (d * Math.PI) / 180;
    return [cx + r * Math.sin(a), cy + r * Math.cos(a)];
  };
  const [x1, y1] = p(fromDeg);
  const [x2, y2] = p(toDeg);
  const span = Math.abs(toDeg - fromDeg);
  if (span >= 359) return `M ${x1} ${y1} A ${r} ${r} 0 1 0 ${x1 - 0.01} ${y1}`;
  const large = span > 180 ? 1 : 0;
  const sweep = toDeg > fromDeg ? 0 : 1;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} ${sweep} ${x2} ${y2}`;
}

/** فلش و کادرِ روی تصویرِ دوربینِ زنده (viewBox ۱۰۰×۱۰۰ روی کلِ کادر). */
export function LiveOverlay({ shot, turned }: { shot: Shot; turned: number | null }) {
  useCss();
  const o = shot.overlay;
  const box = o.distance === "close" ? 86 : o.distance === "far" ? 46 : 64;
  const half = box / 2;
  const arrow = o.arrow;
  const dir: Record<string, [number, number, number]> = {
    right: [1, 0, 0],
    left: [-1, 0, 180],
    up: [0, -1, -90],
    down: [0, 1, 90],
    orbit_right: [1, 0, 0],
    orbit_left: [-1, 0, 180],
  };
  const d = dir[arrow];
  const target = shot.kind === "video" && shot.move === "orbit" ? shot.degrees ?? 90 : shot.kind === "photo" ? Math.abs(o.yaw) : 0;
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
      <rect
        x={50 - half * 0.75}
        y={50 - half}
        width={half * 1.5}
        height={box}
        fill="none"
        stroke="#fff"
        strokeOpacity={0.85}
        strokeWidth={0.5}
        strokeDasharray="2 1.5"
        vectorEffect="non-scaling-stroke"
      />
      <line x1={48} y1={50} x2={52} y2={50} stroke="#fff" strokeWidth={0.4} />
      <line x1={50} y1={48} x2={50} y2={52} stroke="#fff" strokeWidth={0.4} />
      {d && (
        <g
          className="sg-anim"
          style={{ animation: "sg-arrow 1.2s ease-in-out infinite", ["--sg-dx" as string]: `${d[0] * 4}px`, ["--sg-dy" as string]: `${d[1] * 4}px` } as CSSProperties}
        >
          <g transform={`translate(${50 + d[0] * 30} ${50 + d[1] * 30}) rotate(${d[2]})`}>
            <path d="M-7 -3 H2 V-7 L9 0 L2 7 V3 H-7 Z" fill="#fde047" stroke="#000" strokeWidth={0.4} opacity={0.95} />
          </g>
        </g>
      )}
      {(arrow === "in" || arrow === "out") &&
        [
          [-1, -1],
          [1, -1],
          [-1, 1],
          [1, 1],
        ].map(([sx, sy], i) => (
          <g key={i} transform={`translate(${50 + sx * 38} ${50 + sy * 38}) rotate(${Math.atan2(sy, sx) * (180 / Math.PI) + (arrow === "in" ? 180 : 0)})`}>
            <path d="M-4 -1.5 H1 V-4 L5 0 L1 4 V1.5 H-4 Z" fill="#fde047" stroke="#000" strokeWidth={0.3} style={{ animation: "sg-blink 1s infinite" }} />
          </g>
        ))}
      {turned !== null && target > 0 && (
        <g>
          <rect x={30} y={4} width={40} height={7} rx={3.5} fill="rgba(0,0,0,.55)" />
          <rect x={30} y={4} width={Math.min(40, (40 * Math.abs(turned)) / target)} height={7} rx={3.5} fill="#22c55e" />
          <text x={50} y={9.4} textAnchor="middle" fontSize={4} fill="#fff">
            {fa(Math.round(Math.abs(turned)))}° از {fa(target)}°
          </text>
        </g>
      )}
    </svg>
  );
}
