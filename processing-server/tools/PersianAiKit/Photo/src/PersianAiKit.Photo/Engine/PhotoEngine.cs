namespace PersianAiKit.Photo.Engine;

/// <summary>
/// اجرای «نسخهٔ ویرایش» روی عکس. ترتیب مثلِ Camera Raw است (هر مرحله روی خروجیِ قبلی):
/// ترمیمِ لکه ⇒ تعادلِ سفیدی و نوردهی (خطی) ⇒ مه‌زدایی ⇒ روشنی‌ها/سایه‌ها ⇒ منحنی‌ها ⇒ بافت/وضوح ⇒ رنگ ⇒ نویزگیری و شارپ
/// ⇒ لنز، چرخش، برش ⇒ وینیت و دانه. پس‌زمینه و قالبِ خروجی در <see cref="Output"/>.
/// </summary>
public static class PhotoEngine
{
    /// <param name="src">عکس (دست نمی‌خورد؛ نسخهٔ تازه برمی‌گردد).</param>
    /// <param name="scale">اندازهٔ <paramref name="src"/> به اندازهٔ اصلی (پیش‌نمایش &lt; ۱) — برای شعاع‌هایی که به پیکسلِ اصلی‌اند.</param>
    public static PhotoImage Render(PhotoImage src, Recipe recipe, double scale = 1)
    {
        var r = recipe;
        var img = src.Clone();
        try
        {
            if (r.Spots is { Count: > 0 }) Retouch.Heal(img.Color, r.Spots);
            Tone.WhiteBalanceExposure(img.Color, r);
            if (r.Has("dehaze")) Local.Dehaze(img.Color, r.Get("dehaze"));
            if (r.Has("highlights") || r.Has("shadows")) Local.HighlightsShadows(img.Color, r.Get("highlights"), r.Get("shadows"));
            Tone.ApplyCurves(img.Color, r);
            if (r.Has("texture") || r.Has("clarity")) Local.TextureClarity(img.Color, r.Get("texture"), r.Get("clarity"));
            ColorOps.Apply(img.Color, r);
            Detail.Apply(img.Color, r, scale);
            Geometry.Apply(img, r);
            Effects.Apply(img.Color, r, scale);
            Px.Clamp01(img.Color);
            return img;
        }
        catch
        {
            img.Dispose();
            throw;
        }
    }
}
