"""کدهای نمونهٔ حالتِ «کد (Remotion)». هر سه با اسکنرِ امنیتی و کامپایلر می‌گذرند و رندر می‌شوند (آزمون: tests_code.py)."""

HELLO = '''import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

// اندازه و مدت: عرض و ارتفاع به پیکسل، fps و تعدادِ فریم. fonts: فونت‌هایی که باید بارگذاری شوند (پیش‌فرض: vazirmatn).
export const config = { width: 1080, height: 1920, fps: 30, durationInFrames: 150, fonts: ["vazirmatn"] };

const Word = ({ text, delay, color }: { text: string; delay: number; color: string }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  // spring = حرکتِ فنری؛ p از ۰ شروع می‌شود، کمی از ۱ می‌گذرد و برمی‌گردد (overshoot)
  const p = spring({ frame: frame - delay, fps, config: { damping: 12, stiffness: 140 } });
  return (
    <div
      style={{
        transform: `translateY(${(1 - p) * 120}px) scale(${0.6 + 0.4 * p})`,
        opacity: Math.min(1, p * 2),
        color,
        fontSize: 150,
        fontWeight: 900,
        fontFamily: "Vazirmatn, sans-serif",
        margin: "0 18px",
      }}
    >
      {text}
    </div>
  );
};

export default function Video() {
  const frame = useCurrentFrame();
  const angle = interpolate(frame, [0, 150], [0, 360]);   // درون‌یابیِ خطی بینِ دو کلیدفریم
  return (
    <AbsoluteFill style={{ background: `linear-gradient(${angle}deg, #126F85, #163F75)`, justifyContent: "center", alignItems: "center", direction: "rtl" }}>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", width: 900 }}>
        <Word text="با" delay={6} color="#ffffff" />
        <Word text="موشن" delay={14} color="#ffe066" />
        <Word text="بساز" delay={22} color="#ffffff" />
      </div>
    </AbsoluteFill>
  );
}
'''

STYLED = '''import { AbsoluteFill } from "remotion";
import { Card, StyleBackdrop, StyleProvider, T } from "nm-motion";

// از همهٔ سبک‌های استودیو در کد هم می‌شود استفاده کرد: StyleProvider سبک را برقرار می‌کند، StyleBackdrop زمینه و تزئین را می‌گذارد،
// T و Card متن و کارتِ همان سبک‌اند. شناسهٔ سبک را از گالریِ سبک‌ها بردارید.
export const config = { width: 1080, height: 1350, fps: 30, durationInFrames: 120 };

export default function Video() {
  return (
    <StyleProvider style="cyberpunk" lang="fa">
      <AbsoluteFill>
        <StyleBackdrop />
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 40, padding: 80 }}>
          <T size={150}>سایبرپانک</T>
          <Card delay={14} pad={34}>
            <T noAnim role="body" size={52}>همهٔ سبک‌ها در حالتِ کد هم هستند</T>
          </Card>
        </AbsoluteFill>
      </AbsoluteFill>
    </StyleProvider>
  );
}
'''

BARS = '''import { AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig, Easing } from "remotion";

export const config = { width: 1080, height: 1080, fps: 30, durationInFrames: 150, fonts: ["vazirmatn"] };

const DATA = [
  { label: "الف", value: 40, color: "#ff6b6b" },
  { label: "ب", value: 75, color: "#ffd166" },
  { label: "ج", value: 55, color: "#4ecdc4" },
  { label: "د", value: 90, color: "#6a5cff" },
];

const Bar = ({ i, label, value, color }: { i: number; label: string; value: number; color: string }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - 10 - i * 8, fps, config: { damping: 14, stiffness: 110 } });
  const shown = Math.round(value * Math.min(1, p));
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", width: 170, height: 620 }}>
      <div style={{ fontSize: 56, fontWeight: 900, color: "#fff", fontFamily: "Vazirmatn, sans-serif", marginBottom: 12 }}>{shown}</div>
      <div style={{ width: 120, height: value * 5.4 * Math.max(0.001, p), background: color, borderRadius: "18px 18px 0 0" }} />
      <div style={{ fontSize: 52, color: "#cbd5e1", fontFamily: "Vazirmatn, sans-serif", marginTop: 16 }}>{label}</div>
    </div>
  );
};

export default function Video() {
  const frame = useCurrentFrame();
  const fade = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  return (
    <AbsoluteFill style={{ background: "#0f172a", justifyContent: "center", alignItems: "center", direction: "rtl", opacity: fade }}>
      <div style={{ fontSize: 78, fontWeight: 900, color: "#fff", fontFamily: "Vazirmatn, sans-serif", marginBottom: 30 }}>نمودارِ نمونه</div>
      <div style={{ display: "flex", gap: 24, alignItems: "flex-end" }}>
        {DATA.map((d, i) => (
          <Sequence key={d.label} from={0} layout="none">
            <Bar i={i} {...d} />
          </Sequence>
        ))}
      </div>
    </AbsoluteFill>
  );
}
'''

SAMPLES = [
    {"id": "hello", "title": "عنوانِ متحرک (فنر + درون‌یابی)", "code": HELLO},
    {"id": "styled", "title": "استفاده از سبک‌های استودیو", "code": STYLED},
    {"id": "bars", "title": "نمودارِ میله‌ای", "code": BARS},
]
