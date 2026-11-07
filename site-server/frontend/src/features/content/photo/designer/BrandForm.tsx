import type { Asset, FontInfo } from "../api";
import { Brand, POSITION_FA } from "./brandApi";
import "./designer.css";

type Props = {
  value: Brand;
  onChange: (b: Brand) => void;
  fonts: FontInfo[];
  assets: Asset[];
  hasStoreLogo: boolean;
  positions: string[];
  /** پیشوندِ شناسهٔ آزمون */
  tid?: string;
};

const HEX = /^#[0-9a-fA-F]{6}$/;

/** فرمِ «سبکِ برند»: رنگ‌ها، فونت‌ها، لوگو (جا و اندازه) و جملهٔ لحن. هم در تنظیمات و هم برای تغییرِ یک طراحی. */
export default function BrandForm({ value, onChange, fonts, assets, hasStoreLogo, positions, tid = "brand" }: Props) {
  const set = (p: Partial<Brand>) => onChange({ ...value, ...p });
  const setLogo = (p: Partial<Brand["logo"]>) => onChange({ ...value, logo: { ...value.logo, ...p } });
  const sizeAuto = !value.logo.size;
  return (
    <div className="dz-copy" data-testid={`${tid}-form`} style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
      <div className="dz-field wide">
        <span>رنگ‌های برند (تا ۵ رنگ؛ رنگِ اول، رنگِ تأکیدِ طراحی می‌شود)</span>
        <div className="dz-color" style={{ flexWrap: "wrap" }}>
          {value.colors.map((c, i) => (
            <span key={i} className="dz-color">
              <input
                type="color"
                value={HEX.test(c) ? c : "#888888"}
                aria-label={`رنگِ ${i + 1}`}
                onChange={(e) => set({ colors: value.colors.map((x, j) => (j === i ? e.target.value : x)) })}
                data-testid={`${tid}-color-${i}`}
              />
              <button type="button" className="dz-link" aria-label={`حذفِ رنگِ ${i + 1}`} onClick={() => set({ colors: value.colors.filter((_, j) => j !== i) })}>
                ×
              </button>
            </span>
          ))}
          {value.colors.length < 5 && (
            <button type="button" className="example-chip" onClick={() => set({ colors: [...value.colors, "#1e5aaa"] })} data-testid={`${tid}-add-color`}>
              + رنگ
            </button>
          )}
        </div>
      </div>
      <label className="dz-field">
        <span>فونتِ تیتر</span>
        <select className="u-input" value={value.heading_font} onChange={(e) => set({ heading_font: e.target.value })} data-testid={`${tid}-heading-font`}>
          <option value="">خودکار (بسته به الگو)</option>
          {fonts.map((f) => (
            <option key={f.key} value={f.key}>{f.title}</option>
          ))}
        </select>
      </label>
      <label className="dz-field">
        <span>فونتِ متن و دکمه</span>
        <select className="u-input" value={value.body_font} onChange={(e) => set({ body_font: e.target.value })} data-testid={`${tid}-body-font`}>
          <option value="">خودکار (بسته به الگو)</option>
          {fonts.map((f) => (
            <option key={f.key} value={f.key}>{f.title}</option>
          ))}
        </select>
      </label>
      <label className="dz-field">
        <span>لوگو</span>
        <select
          className="u-input"
          value={value.logo.mode}
          onChange={(e) => setLogo({ mode: e.target.value as Brand["logo"]["mode"], asset: e.target.value === "asset" ? value.logo.asset ?? assets[0]?.id ?? null : null })}
          data-testid={`${tid}-logo-mode`}
        >
          <option value="store">{hasStoreLogo ? "لوگوی ثبت‌شدهٔ فروشگاه" : "لوگوی فروشگاه (هنوز ثبت نشده)"}</option>
          <option value="asset" disabled={!assets.length}>یکی از عکس‌های کتابخانه</option>
          <option value="none">بدونِ لوگو</option>
        </select>
      </label>
      {value.logo.mode === "asset" && (
        <label className="dz-field">
          <span>عکسِ لوگو</span>
          <select className="u-input" value={value.logo.asset ?? ""} onChange={(e) => setLogo({ asset: Number(e.target.value) || null })} data-testid={`${tid}-logo-asset`}>
            {assets.map((a) => (
              <option key={a.id} value={a.id}>{a.title}</option>
            ))}
          </select>
        </label>
      )}
      {value.logo.mode !== "none" && (
        <>
          <label className="dz-field">
            <span>جای لوگو</span>
            <select className="u-input" value={value.logo.position} onChange={(e) => setLogo({ position: e.target.value })} data-testid={`${tid}-logo-pos`}>
              <option value="">پیش‌فرضِ الگو</option>
              {positions.map((p) => (
                <option key={p} value={p}>{POSITION_FA[p] ?? p}</option>
              ))}
            </select>
          </label>
          <div className="dz-field">
            <span>اندازهٔ لوگو</span>
            <div className="dz-range">
              <input
                type="range"
                min={6}
                max={30}
                value={sizeAuto ? 14 : Math.round(value.logo.size * 100)}
                disabled={sizeAuto}
                aria-label="اندازهٔ لوگو"
                onChange={(e) => setLogo({ size: Number(e.target.value) / 100 })}
                data-testid={`${tid}-logo-size`}
              />
              <b dir="ltr">{sizeAuto ? "خودکار" : `${Math.round(value.logo.size * 100)}%`}</b>
            </div>
            <label className="dz-field check" style={{ fontWeight: 400 }}>
              <input type="checkbox" checked={sizeAuto} onChange={(e) => setLogo({ size: e.target.checked ? 0 : 0.14 })} />
              اندازهٔ پیش‌فرضِ الگو
            </label>
          </div>
        </>
      )}
      <label className="dz-field wide">
        <span>لحنِ برند (یک جمله؛ برای نوشتنِ متن‌ها با هوش مصنوعی)</span>
        <input
          className="u-input"
          value={value.tone}
          maxLength={200}
          placeholder="مثلاً: گرم و صمیمی، کوتاه، بدونِ شعار و اغراق"
          onChange={(e) => set({ tone: e.target.value })}
          data-testid={`${tid}-tone`}
        />
      </label>
    </div>
  );
}
