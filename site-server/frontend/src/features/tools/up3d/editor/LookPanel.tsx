import { Button, Field, Select } from "../../../../components/ui";
import { fa } from "../api";
import type { RenderLook, SceneDoc } from "../types";
import { DraftRange } from "./fields";

/**
 * «نگاه و لنز» (موتورِ ۱٫۳): رنگ‌نگاریِ AgX با نگاه‌های آماده، نوردهی، عمقِ میدان، تاریِ حرکت، دستِ لرزان، درخششِ نور،
 * تیرگیِ گوشه‌ها و محوِ آغاز/پایان. همه اختیاری است؛ خالی = همان پروفایلِ رندر. در سند زیرِ کلیدِ `render` می‌نشیند
 * (up3d.scene.norm_render) و رندرِ Cycles روی کارتِ گرافیک آن را اجرا می‌کند.
 */

export const LOOKS: [string, string][] = [
  ["", "پیش‌فرضِ پروفایل (AgX متوازن)"],
  ["agx", "AgX · استاندارد"],
  ["agx_soft", "AgX · نرم (کنتراستِ کم)"],
  ["agx_contrast", "AgX · پرکنتراست (سینمایی)"],
  ["agx_punchy", "AgX · پررنگ و جذاب"],
  ["agx_golden", "AgX · طلایی و گرم"],
  ["agx_bw", "AgX · سیاه‌وسفید"],
];

export const EASES_CAM: [string, string][] = [
  ["", "پیش‌فرض (نرم)"],
  ["smooth", "نرم (آرام شروع، آرام پایان)"],
  ["linear", "یکنواخت"],
  ["ease_in", "آرام شروع"],
  ["ease_out", "آرام پایان"],
  ["expo", "سینمایی (شروعِ بلند، میانهٔ تند)"],
  ["sine", "سینوسی"],
];

type Change = (fn: (d: SceneDoc) => void) => void;

export default function LookPanel({ doc, change }: { doc: SceneDoc; change: Change }) {
  const r: RenderLook = doc.render || {};
  const set = (k: keyof RenderLook, v: unknown) =>
    change((d) => {
      const cur: Record<string, unknown> = { ...(d.render || {}) };
      if (v === undefined || v === "") delete cur[k];
      else cur[k] = v;
      if (Object.keys(cur).length) d.render = cur as RenderLook;
      else delete d.render;
    });
  const num = (k: keyof RenderLook, lo: number, hi: number, step: number, def: number, title: string, hint?: string) => {
    const cur = typeof r[k] === "number" ? (r[k] as number) : def;
    return (
      <Field label={`${title}: ${fa(cur)}`} hint={hint}>
        <DraftRange value={cur} min={lo} max={hi} step={step} onCommit={(v) => set(k, v)} />
      </Field>
    );
  };
  return (
    <div className="space-y-2" data-testid="look-panel">
      <Field label="نگاهِ رنگ (AgX)">
        <Select value={r.look || ""} onChange={(e) => set("look", e.target.value || undefined)}>
          {LOOKS.map(([v, t]) => (
            <option key={v} value={v}>
              {t}
            </option>
          ))}
        </Select>
      </Field>
      {num("exposure", -3, 3, 0.1, 0, "نوردهی (stop)")}
      <div className="grid grid-cols-2 gap-2">
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={r.dof !== false} onChange={(e) => set("dof", e.target.checked ? undefined : false)} />
          عمقِ میدان (تاریِ پس‌زمینه)
        </label>
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={r.motion_blur !== false} onChange={(e) => set("motion_blur", e.target.checked ? undefined : false)} />
          تاریِ حرکت
        </label>
      </div>
      {r.dof !== false && num("dof_strength", 0, 3, 0.05, 1, "شدتِ عمقِ میدان", "بیشتر = پس‌زمینهٔ تارتر")}
      {r.motion_blur !== false && num("shutter", 0.05, 1, 0.05, 0.4, "بازبودنِ شاتر", "بیشتر = تاریِ حرکتِ بیشتر")}
      {num("handheld", 0, 1, 0.05, 0, "دستِ لرزان", "۰ = سه‌پایه؛ ۰٫۲ تا ۰٫۴ = دوربینِ روی دستِ طبیعی")}
      <Field label="آسانیِ حرکتِ دوربین">
        <Select value={r.ease || ""} onChange={(e) => set("ease", e.target.value || undefined)}>
          {EASES_CAM.map(([v, t]) => (
            <option key={v} value={v}>
              {t}
            </option>
          ))}
        </Select>
      </Field>
      {num("bloom", 0, 1.5, 0.05, 0, "درخششِ نورهای قوی (bloom)")}
      {num("vignette", 0, 0.6, 0.02, 0, "تیرگیِ گوشه‌ها")}
      <div className="grid grid-cols-2 gap-2">
        {num("fade_in", 0, 3, 0.1, 0, "محوِ آغاز (ث)")}
        {num("fade_out", 0, 3, 0.1, 0, "محوِ پایان (ث)")}
      </div>
      {doc.render && (
        <Button size="sm" variant="ghost" onClick={() => change((d) => void delete d.render)}>
          بازگشت به پیش‌فرضِ پروفایل
        </Button>
      )}
    </div>
  );
}
