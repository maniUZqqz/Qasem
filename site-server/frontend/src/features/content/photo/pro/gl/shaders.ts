/**
 * شیدرهای موتور. فرمول‌ها از کدِ C# کیت (PersianAiKit.Photo/Engine: Tone, ColorOps, Local, Detail, Geometry/Effects) برگردانده شده‌اند؛
 * آن‌جا که کیت از OpenCV (NLM، فیلترِ هدایت‌شده روی نسخهٔ ۶۴۰ پیکسلی…) کمک می‌گیرد، همان الگوریتم با پاس‌های GPU آمده و
 * فقط نویزگیری (NLM) تقریبی است.
 */
const PRE = `#version 300 es
precision highp float; precision highp sampler2D;
in vec2 vUv; out vec4 oc;
const vec3 LW = vec3(0.2126, 0.7152, 0.0722);
float lum(vec3 c){ return dot(c, LW); }
float sst(float a, float b, float x){ float t = clamp((x - a) / (b - a), 0.0, 1.0); return t * t * (3.0 - 2.0 * t); }
vec3 ratio(vec3 rgb, float y0, float y1){ return y0 > 1e-4 ? rgb * (y1 / y0) : rgb + (y1 - y0); }
`;

const sh = (body: string) => PRE + body;

export const SH = {
  copy: sh(`uniform sampler2D uT; void main(){ oc = texture(uT, vUv); }`),

  /**
   * جلوه‌های لایه (سایه/درخشش/دورخط): همان قراردادِ fx.py. ۱) fxPad: تایلِ لایه (پیش‌ضرب‌شده) با حاشیهٔ متقارن، اگر لازم باشد با
   * تغییرِ اندازه (تصویر) و قرینه ⇒ بافتِ «پدشده». ۲) fxAlpha: آلفا ⇒ R (با جابه‌جاییِ دوخطیِ سایه). ۳) fxDilate: بیشینه روی دیسکِ
   * شعاعِ uS (هستهٔ ellipse ِ cv2: نیم‌پهنای ردیفِ dy = round(√(s²−dy²)))؛ شعاعِ بزرگ ⇒ چند گامِ ≤ ۱۲ پشتِ هم.
   * ۴) محو = همان blur ِ گاوسی (روی نسخهٔ ۱/f). ۵) fxFinal: سایه، درخشش، دورخط، پیکسل‌های لایه با «over» ِ معمولی و گردکردنِ
   * نقشهٔ هر جلوه به ۸ بیت پس از ضرب در opacity (مثلِ fx.maps)؛ خروجی پیش‌ضرب‌شده.
   */
  fxPad: sh(`uniform sampler2D uT; uniform vec2 uOut; uniform vec2 uM; uniform vec2 uIn; uniform vec2 uFlip;
  void main(){
    vec2 p = vUv * uOut - uM;
    bool inside = p.x >= 0.0 && p.y >= 0.0 && p.x <= uIn.x && p.y <= uIn.y;
    vec2 t = clamp(p / uIn, 0.0, 1.0);
    if (uFlip.x < 0.0) t.x = 1.0 - t.x;
    if (uFlip.y < 0.0) t.y = 1.0 - t.y;
    vec4 c = texture(uT, t);
    oc = inside ? c : vec4(0.0);
  }`),
  fxAlpha: sh(`uniform sampler2D uT; uniform vec2 uOff;
  void main(){ float a = texture(uT, vUv - uOff).a; oc = vec4(a, a, a, a); }`),
  fxDilate: sh(`uniform sampler2D uT; uniform vec2 uPx; uniform float uS;
  void main(){
    int S = int(uS + 0.5);
    float m = texture(uT, vUv).r;
    for (int dy = -S; dy <= S; dy++) {
      int hw = int(floor(sqrt(float(S * S - dy * dy)) + 0.5));
      for (int dx = -hw; dx <= hw; dx++) m = max(m, texture(uT, vUv + vec2(float(dx), float(dy)) * uPx).r);
    }
    oc = vec4(m, m, m, m);
  }`),
  fxFinal: sh(`uniform sampler2D uL; uniform sampler2D uSh; uniform sampler2D uGl; uniform sampler2D uSt;
  uniform vec3 uShC; uniform vec3 uGlC; uniform vec3 uStC; uniform vec3 uOp;
  uniform vec2 uOut; uniform vec2 uOff; uniform vec2 uPad;
  float q(float a, float op){ return floor(a * op * 255.0 + 0.5) / 255.0; }
  void main(){
    vec2 uv = (vUv * uOut + uOff) / uPad;
    vec3 pm = vec3(0.0); float ac = 0.0;
    if (uOp.x > 0.0) { float al = q(texture(uSh, uv).r, uOp.x); pm = pm * (1.0 - al) + uShC * al; ac = al + ac * (1.0 - al); }
    if (uOp.y > 0.0) { float al = q(texture(uGl, uv).r, uOp.y); pm = pm * (1.0 - al) + uGlC * al; ac = al + ac * (1.0 - al); }
    if (uOp.z > 0.0) { float al = q(texture(uSt, uv).r, uOp.z); pm = pm * (1.0 - al) + uStC * al; ac = al + ac * (1.0 - al); }
    vec4 L = texture(uL, uv);
    pm = L.rgb + pm * (1.0 - L.a); ac = L.a + ac * (1.0 - L.a);
    oc = vec4(pm, ac);
  }`),

  /**
   * مرحلهٔ «قاب» (frame-first): عکسِ پایه (فضای عکس) ⇒ بومِ نهایی. uInv: uv بوم ⇒ uv عکس (پرسپکتیو/چرخش/صاف‌کردن/قرینه/برش/قابِ
   * شبکه همه در یک هموگرافی؛ معکوسِ دقیق). نمونه‌برداری با میپ‌مپِ سه‌خطی (uBias کمی تیزتر) ⇒ بی لرزش روی عکسِ چرخیده؛ لبهٔ عکس
   * clamp (مثلِ BORDER_REPLICATE ِ سرور). uContain: عکس داخلِ مستطیلِ uFg (پیکسلِ واقعیِ بوم) و بیرونش پُر می‌شود —
   * uFill: ۰ سفید، ۱ سیاه، ۲ رنگ، ۳ محو (uBg، از frameBg)، ۴ شفاف. لبهٔ مستطیل با پوششِ نیم‌پیکسلی نرم می‌شود.
   */
  frame: sh(`uniform sampler2D uT; uniform sampler2D uBg; uniform mat3 uInv; uniform vec2 uCanvas; uniform vec2 uWork;
  uniform float uContain; uniform vec4 uFg; uniform float uFill; uniform vec3 uFillColor; uniform float uBias;
  void main(){
    vec3 h = uInv * vec3(vUv, 1.0);
    vec2 uv = h.xy / h.z;
    vec4 s = texture(uT, uv, uBias);
    if (uContain < 0.5) { oc = s; return; }
    vec2 cp = vUv * uCanvas;
    vec2 lo = cp - uFg.xy;
    vec2 hi = uFg.xy + uFg.zw - cp;
    float d = min(min(lo.x, hi.x), min(lo.y, hi.y)) * (uWork.x / uCanvas.x);
    float cov = clamp(d + 0.5, 0.0, 1.0);
    if (uFill > 3.5) { oc = vec4(s.rgb, s.a * cov); return; }
    vec3 bg = uFill < 0.5 ? vec3(1.0) : (uFill < 1.5 ? vec3(0.0) : (uFill < 2.5 ? uFillColor : texture(uBg, vUv).rgb * 0.82));
    oc = vec4(mix(bg, s.rgb, s.a * cov), 1.0);
  }`),

  /** پس‌زمینهٔ «محو»ِ قاب (۱/۸ بوم): نسخهٔ cover-scale شدهٔ عکسِ پس از هندسه، روی سفید flatten؛ گاوسِ ۶ و ×۰٫۸۲ بعداً */
  frameBg: sh(`uniform sampler2D uT; uniform mat3 uInv;
  void main(){
    vec3 h = uInv * vec3(vUv, 1.0);
    vec4 s = texture(uT, h.xy / h.z);
    oc = vec4(mix(vec3(1.0), s.rgb, s.a), 1.0);
  }`),

  /** کلیپ به ۰..۱ و تبدیل به ۸ بیت (برای readPixels) */
  quant: sh(`uniform sampler2D uT; void main(){ vec4 c = texture(uT, vUv); oc = vec4(clamp(c.rgb, 0.0, 1.0), c.a); }`),

  /** تعادلِ سفیدی + نوردهی (فضای خطی ۲٫۲)، شانهٔ نرم برای روشن‌ترها */
  wb: sh(`uniform sampler2D uT; uniform vec3 uK; uniform float uShoulder;
  void main(){
    vec4 c = texture(uT, vUv);
    vec3 lin = pow(clamp(c.rgb, 0.0, 1.0), vec3(2.2)) * uK;
    vec3 v = pow(max(lin, 0.0), vec3(1.0 / 2.2));
    if (uShoulder > 0.5) {
      vec3 s = 0.9 + 0.1 * (1.0 - exp(-(v - 0.9) / 0.1));
      v = mix(v, s, step(0.9, v));
    }
    oc = vec4(v, c.a);
  }`),

  /** تارکنندهٔ گاوسیِ جدا شدنی؛ uStep = اندازهٔ یک پیکسل در جهت، uSigma به پیکسل */
  blur: sh(`uniform sampler2D uT; uniform vec2 uStep; uniform float uSigma;
  void main(){
    int R = int(min(ceil(uSigma * 3.0), 30.0));
    vec4 acc = texture(uT, vUv); float ws = 1.0;
    float inv = 1.0 / (2.0 * uSigma * uSigma);
    for (int i = 1; i <= 30; i++) {
      if (i > R) break;
      float w = exp(-float(i * i) * inv);
      acc += w * (texture(uT, vUv + uStep * float(i)) + texture(uT, vUv - uStep * float(i)));
      ws += 2.0 * w;
    }
    oc = acc / ws;
  }`),

  /** فیلترِ جعبه‌ای جدا شدنی (شعاع به پیکسل) */
  box: sh(`uniform sampler2D uT; uniform vec2 uStep; uniform float uR;
  void main(){
    int R = int(uR);
    vec4 acc = texture(uT, vUv);
    for (int i = 1; i <= 40; i++) {
      if (i > R) break;
      acc += texture(uT, vUv + uStep * float(i)) + texture(uT, vUv - uStep * float(i));
    }
    oc = acc / float(2 * R + 1);
  }`),

  /** حداقل‌گیریِ جعبه‌ای (erode) */
  boxMin: sh(`uniform sampler2D uT; uniform vec2 uStep; uniform float uR;
  void main(){
    int R = int(uR);
    vec4 acc = texture(uT, vUv);
    for (int i = 1; i <= 24; i++) {
      if (i > R) break;
      acc = min(acc, min(texture(uT, vUv + uStep * float(i)), texture(uT, vUv - uStep * float(i))));
    }
    oc = acc;
  }`),

  lumaOnly: sh(`uniform sampler2D uT; void main(){ float y = lum(texture(uT, vUv).rgb); oc = vec4(y, y, y, 1.0); }`),

  /** بستهٔ فیلترِ هدایت‌شده: (I, p, I·I, I·p) از (R=I, G=p) */
  gfPack: sh(`uniform sampler2D uIP; void main(){ vec2 ip = texture(uIP, vUv).rg; oc = vec4(ip.x, ip.y, ip.x * ip.x, ip.x * ip.y); }`),

  gfAB: sh(`uniform sampler2D uM; uniform float uEps;
  void main(){
    vec4 m = texture(uM, vUv);
    float a = (m.w - m.x * m.y) / (m.z - m.x * m.x + uEps);
    float b = m.y - a * m.x;
    oc = vec4(a, b, 0.0, 1.0);
  }`),

  /** q = mean_a · I + mean_b  (روی نسخهٔ کوچک) */
  gfOut: sh(`uniform sampler2D uAB; uniform sampler2D uI;
  void main(){ vec2 ab = texture(uAB, vUv).rg; float i = texture(uI, vUv).r; float q = ab.x * i + ab.y; oc = vec4(q, q, q, 1.0); }`),

  /** روشنی‌ها/سایه‌ها: پایهٔ لبه‌آگاه از GB (a,b) */
  hs: sh(`uniform sampler2D uT; uniform sampler2D uGB; uniform float uSh; uniform float uHl;
  void main(){
    vec4 c = texture(uT, vUv);
    float y = lum(c.rgb);
    vec2 ab = texture(uGB, vUv).rg;
    float b = clamp(ab.x * y + ab.y, 0.0, 1.0);
    float ws = 1.0 - sst(0.0, 0.6, b);
    float wh = sst(0.4, 1.0, b);
    float g = uSh * 1.3 * ws + uHl * 1.0 * wh;
    float v = y * pow(2.0, g);
    float yn = v > 0.95 ? 0.95 + 0.05 * (1.0 - exp(-(v - 0.95) / 0.05)) : v;
    oc = vec4(ratio(c.rgb, y, yn), c.a);
  }`),

  /** منحنی‌ها: جدولِ ۱۰۲۵×۱ (R,G,B) */
  lut: sh(`uniform sampler2D uT; uniform sampler2D uLut; uniform float uN;
  vec3 look(vec3 v){
    vec3 x = (clamp(v, 0.0, 1.0) * uN + 0.5) / (uN + 1.0);
    return vec3(texture(uLut, vec2(x.r, 0.5)).r, texture(uLut, vec2(x.g, 0.5)).g, texture(uLut, vec2(x.b, 0.5)).b);
  }
  void main(){ vec4 c = texture(uT, vUv); oc = vec4(look(c.rgb), c.a); }`),

  /** بافت و وضوح */
  tc: sh(`uniform sampler2D uT; uniform sampler2D uGB; uniform sampler2D uBlur; uniform float uClar; uniform float uTex;
  void main(){
    vec4 c = texture(uT, vUv);
    float y = lum(c.rgb);
    float yn = y;
    if (uClar != 0.0) {
      vec2 ab = texture(uGB, vUv).rg;
      float b = ab.x * y + ab.y;
      float cl = clamp(y, 0.0, 1.0);
      float mid = 4.0 * cl * (1.0 - cl);
      yn += uClar * (y - b) * (0.35 + 0.65 * mid);
    }
    if (uTex != 0.0) { float yb = lum(texture(uBlur, vUv).rgb); yn += uTex * (y - yb); }
    oc = vec4(ratio(c.rgb, y, yn), c.a);
  }`),

  /** مه‌زدایی: نرمالِ کانالِ تیره */
  dzNorm: sh(`uniform sampler2D uT; uniform vec3 uAir;
  void main(){ vec3 c = clamp(texture(uT, vUv).rgb, 0.0, 1.0) / uAir; float m = min(c.r, min(c.g, c.b)); oc = vec4(m, m, m, 1.0); }`),
  /** (I=خاکستری، p=tRaw) */
  dzIP: sh(`uniform sampler2D uT; uniform sampler2D uE;
  void main(){ float g = lum(texture(uT, vUv).rgb); float e = texture(uE, vUv).r; oc = vec4(g, 1.0 - 0.95 * e, 0.0, 1.0); }`),
  dzApply: sh(`uniform sampler2D uT; uniform sampler2D uTr; uniform vec3 uAir; uniform float uA;
  void main(){
    vec4 c = texture(uT, vUv);
    float tt = max(texture(uTr, vUv).r, 0.1);
    vec3 p = c.rgb;
    if (uA > 0.0) { float s = uA * 0.85; p += s * ((p - uAir) / tt + uAir - p); }
    else { float s = -uA * 0.45 * (1.2 - tt); p += s * (uAir - p); }
    oc = vec4(p, c.a);
  }`),

  /** رنگ‌به‌رنگ، وایبرنس، اشباع، رنگ‌دهی */
  color: sh(`uniform sampler2D uT;
  uniform float uDh[9]; uniform float uDs[9]; uniform float uDl[9];
  uniform float uHsl; uniform float uVib; uniform float uSat; uniform float uGrade; uniform float uShS; uniform float uHiS; uniform float uBal;
  uniform vec3 uShT; uniform vec3 uHiT;
  const float CEN[9] = float[9](0.0, 30.0, 60.0, 120.0, 180.0, 240.0, 270.0, 300.0, 360.0);
  vec3 toHsv(vec3 c){
    float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b)), d = mx - mn;
    float h = 0.0;
    if (d > 1e-6) {
      if (mx == c.r) h = 60.0 * ((c.g - c.b) / d);
      else if (mx == c.g) h = 60.0 * ((c.b - c.r) / d + 2.0);
      else h = 60.0 * ((c.r - c.g) / d + 4.0);
      if (h < 0.0) h += 360.0;
    }
    return vec3(h, mx > 1e-6 ? d / mx : 0.0, mx);
  }
  vec3 fromHsv(float h, float s, float v){
    if (s <= 0.0) return vec3(v);
    h = mod(mod(h, 360.0) + 360.0, 360.0) / 60.0;
    int i = int(floor(h)); float f = h - float(i);
    float p = v * (1.0 - s), q = v * (1.0 - s * f), t = v * (1.0 - s * (1.0 - f));
    if (i == 0) return vec3(v, t, p);
    if (i == 1) return vec3(q, v, p);
    if (i == 2) return vec3(p, v, t);
    if (i == 3) return vec3(p, q, v);
    if (i == 4) return vec3(t, p, v);
    return vec3(v, p, q);
  }
  void main(){
    vec4 c0 = texture(uT, vUv);
    vec3 c = clamp(c0.rgb, 0.0, 1.0);
    if (uHsl > 0.5 || uVib != 0.0 || uSat != 0.0) {
      vec3 hsv = toHsv(c);
      float h = hsv.x, s = hsv.y, v = hsv.z;
      if (uHsl > 0.5 && s > 0.001) {
        int i = 0;
        for (int k = 0; k < 7; k++) { if (h >= CEN[k + 1]) i = k + 1; }
        float t = (h - CEN[i]) / (CEN[i + 1] - CEN[i]);
        float wdh = uDh[i] * (1.0 - t) + uDh[i + 1] * t;
        float wds = uDs[i] * (1.0 - t) + uDs[i + 1] * t;
        float wdl = uDl[i] * (1.0 - t) + uDl[i + 1] * t;
        h += wdh; if (h < 0.0) h += 360.0; else if (h >= 360.0) h -= 360.0;
        s = clamp(s * (1.0 + wds), 0.0, 1.0);
        v = clamp(v * (1.0 + wdl * 0.6 * min(1.0, s * 1.5)), 0.0, 1.0);
      }
      if (uVib != 0.0) {
        float skin = (h > 5.0 && h < 50.0) ? 0.5 + 0.5 * abs(h - 27.5) / 22.5 : 1.0;
        s = clamp(s * (1.0 + uVib * (1.0 - s) * (uVib > 0.0 ? skin : 1.0)), 0.0, 1.0);
      }
      if (uSat > 0.0) s = clamp(s * (1.0 + uSat), 0.0, 1.0);
      c = fromHsv(h, s, v);
      if (uSat < 0.0) { float l = lum(c); c = l + (c - l) * (1.0 + uSat); }
    }
    if (uGrade > 0.5) {
      float l = lum(c);
      float ws = 1.0 - sst(0.0, 0.6 + 0.3 * uBal, l);
      float wh = sst(0.4 + 0.3 * uBal, 1.0, l);
      c += uShT * (uShS * 0.3 * ws) + uHiT * (uHiS * 0.3 * wh);
    }
    oc = vec4(c, c0.a);
  }`),

  /** نویزگیریِ تقریبی (دوطرفه روی روشنایی + صافِ رنگ) */
  denoise: sh(`uniform sampler2D uT; uniform vec2 uPx; uniform float uLuma; uniform float uColor;
  void main(){
    vec4 c0 = texture(uT, vUv);
    vec3 c = c0.rgb;
    float y0 = lum(c);
    if (uLuma > 0.0) {
      float hr = (2.0 + uLuma * 16.0) / 255.0 * 1.6;
      float acc = 0.0, ws = 0.0;
      for (int j = -2; j <= 2; j++) for (int i = -2; i <= 2; i++) {
        vec3 s = texture(uT, vUv + uPx * vec2(float(i), float(j))).rgb;
        float ys = lum(s);
        float d = (ys - y0) / hr;
        float w = exp(-0.5 * float(i * i + j * j) / 2.25) * exp(-0.5 * d * d);
        acc += w * ys; ws += w;
      }
      float yd = acc / ws;
      float diff = clamp(yd - y0, -0.08, 0.08);
      c = ratio(c, y0, y0 + diff);
    }
    if (uColor > 0.0) {
      float yy = lum(c);
      vec3 ch = c - yy; vec3 acc = vec3(0.0); float ws = 0.0;
      float st = 1.0 + uColor * 3.0;
      for (int j = -2; j <= 2; j++) for (int i = -2; i <= 2; i++) {
        vec3 s = texture(uT, vUv + uPx * st * vec2(float(i), float(j))).rgb;
        float w = exp(-0.5 * float(i * i + j * j) / 2.25);
        acc += w * (s - lum(s)); ws += w;
      }
      float k = min(1.0, uColor * 1.3);
      c = yy + mix(ch, acc / ws, k);
    }
    oc = vec4(c, c0.a);
  }`),

  /** شارپ: ماسکِ غیرشارپ روی روشنایی با ماسکِ لبه (سوبل روی تارشده) */
  sharpen: sh(`uniform sampler2D uT; uniform sampler2D uBlur; uniform vec2 uPx; uniform float uK; uniform float uM0; uniform float uUseMask;
  void main(){
    vec4 c = texture(uT, vUv);
    float y = lum(c.rgb);
    float yb = lum(texture(uBlur, vUv).rgb);
    float mask = 1.0;
    if (uUseMask > 0.5) {
      float a = lum(texture(uBlur, vUv + uPx * vec2(-1.0, -1.0)).rgb), b = lum(texture(uBlur, vUv + uPx * vec2(0.0, -1.0)).rgb), cc = lum(texture(uBlur, vUv + uPx * vec2(1.0, -1.0)).rgb);
      float d = lum(texture(uBlur, vUv + uPx * vec2(-1.0, 0.0)).rgb), f = lum(texture(uBlur, vUv + uPx * vec2(1.0, 0.0)).rgb);
      float g = lum(texture(uBlur, vUv + uPx * vec2(-1.0, 1.0)).rgb), h = lum(texture(uBlur, vUv + uPx * vec2(0.0, 1.0)).rgb), i = lum(texture(uBlur, vUv + uPx * vec2(1.0, 1.0)).rgb);
      float gx = (cc + 2.0 * f + i) - (a + 2.0 * d + g);
      float gy = (g + 2.0 * h + i) - (a + 2.0 * b + cc);
      mask = sst(uM0, uM0 + 0.15, length(vec2(gx, gy)));
    }
    float yn = y + uK * (y - yb) * mask;
    oc = vec4(ratio(c.rgb, y, yn), c.a);
  }`),

  /** اعوجاجِ لنز + تاریکیِ گوشهٔ لنز */
  lens: sh(`uniform sampler2D uT; uniform vec2 uSize; uniform float uK; uniform float uNorm; uniform float uLv;
  void main(){
    vec2 uv = vUv;
    if (uK != 0.0) {
      vec2 c = (uSize - 1.0) * 0.5; float R = length(c);
      vec2 p = uv * uSize - 0.5;
      vec2 n = (p - c) / R;
      float f = (1.0 + uK * dot(n, n)) * uNorm;
      uv = ((c + n * f * R) + 0.5) / uSize;
    }
    vec4 col = texture(uT, uv);
    if (uLv > 0.0) {
      vec2 n = (vUv - 0.5) * 2.0;
      float g = 1.0 + uLv * dot(n, n) * 0.5;
      col.rgb *= g;
    }
    oc = col;
  }`),

  /** وینیت و دانه */
  fx: sh(`uniform sampler2D uT; uniform vec2 uSize; uniform float uVig; uniform float uInner; uniform float uOuter; uniform float uGrain; uniform float uCell;
  float h21(vec2 p){ vec3 q = fract(vec3(p.xyx) * 0.1031); q += dot(q, q.yzx + 33.33); return fract((q.x + q.y) * q.z); }
  float vnoise(vec2 p){
    vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
    float a = h21(i), b = h21(i + vec2(1.0, 0.0)), c = h21(i + vec2(0.0, 1.0)), d = h21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
  }
  float gauss(vec2 p){
    float s = vnoise(p) + vnoise(p * 1.7 + 11.3) + vnoise(p * 2.9 + 37.1) + vnoise(p * 4.1 + 5.7);
    return (s - 2.0) * 1.7;
  }
  void main(){
    vec4 c = texture(uT, vUv);
    vec3 p = c.rgb;
    if (uVig != 0.0) {
      vec2 n = (vUv - 0.5) * 2.0;
      float d = sqrt(dot(n, n) / 2.0);
      float m = sst(uInner, uOuter, d) * abs(uVig) * 0.85;
      if (uVig < 0.0) p *= (1.0 - m); else p += (1.0 - p) * m;
    }
    if (uGrain > 0.0) {
      float l = clamp(lum(p), 0.0, 1.0);
      float n = gauss(vUv * uSize / uCell);
      p += n * uGrain * 0.09 * (0.4 + 2.4 * l * (1.0 - l));
    }
    oc = vec4(p, c.a);
  }`),

  /** ترکیبِ یک لایه با پیش‌زمینه (همهٔ حالت‌های آمیزش W3C) + ماسک */
  comp: sh(`uniform sampler2D uDst; uniform sampler2D uSrc; uniform sampler2D uMask;
  uniform vec2 uDoc; uniform vec2 uC; uniform vec2 uS; uniform float uRot; uniform vec2 uFlip;
  uniform float uFull; uniform float uPremul; uniform float uOpacity; uniform float uMode;
  uniform sampler2D uClip; uniform float uUseClip;
  uniform float uMType; uniform float uMInv; uniform vec4 uMP; uniform float uMFeather;
  float lum2(vec3 c){ return 0.3 * c.r + 0.59 * c.g + 0.11 * c.b; }
  vec3 clipC(vec3 c){ float l = lum2(c); float n = min(c.r, min(c.g, c.b)); float x = max(c.r, max(c.g, c.b));
    if (n < 0.0) c = l + (c - l) * l / (l - n);
    if (x > 1.0) c = l + (c - l) * (1.0 - l) / (x - l);
    return c; }
  vec3 setLum(vec3 c, float l){ return clipC(c + (l - lum2(c))); }
  float satOf(vec3 c){ return max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b)); }
  vec3 setSat(vec3 c, float s){ float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b)); return mx > mn ? (c - mn) * s / (mx - mn) : vec3(0.0); }
  float hardL(float cb, float cs){ return cs <= 0.5 ? cb * 2.0 * cs : (cb + (2.0 * cs - 1.0) - cb * (2.0 * cs - 1.0)); }
  float softL(float cb, float cs){
    if (cs <= 0.5) return cb - (1.0 - 2.0 * cs) * cb * (1.0 - cb);
    float d = cb <= 0.25 ? ((16.0 * cb - 12.0) * cb + 4.0) * cb : sqrt(cb);
    return cb + (2.0 * cs - 1.0) * (d - cb);
  }
  float dodge(float cb, float cs){ return cb == 0.0 ? 0.0 : (cs >= 1.0 ? 1.0 : min(1.0, cb / (1.0 - cs))); }
  float burn(float cb, float cs){ return cb >= 1.0 ? 1.0 : (cs <= 0.0 ? 0.0 : 1.0 - min(1.0, (1.0 - cb) / cs)); }
  vec3 blendRGB(float m, vec3 cb, vec3 cs){
    if (m < 0.5) return cs;
    if (m < 1.5) return cb * cs;
    if (m < 2.5) return cb + cs - cb * cs;
    if (m < 3.5) return vec3(hardL(cs.r, cb.r), hardL(cs.g, cb.g), hardL(cs.b, cb.b));
    if (m < 4.5) return vec3(softL(cb.r, cs.r), softL(cb.g, cs.g), softL(cb.b, cs.b));
    if (m < 5.5) return vec3(hardL(cb.r, cs.r), hardL(cb.g, cs.g), hardL(cb.b, cs.b));
    if (m < 6.5) return min(cb, cs);
    if (m < 7.5) return max(cb, cs);
    if (m < 8.5) return vec3(dodge(cb.r, cs.r), dodge(cb.g, cs.g), dodge(cb.b, cs.b));
    if (m < 9.5) return vec3(burn(cb.r, cs.r), burn(cb.g, cs.g), burn(cb.b, cs.b));
    if (m < 10.5) return abs(cb - cs);
    if (m < 11.5) return cb + cs - 2.0 * cb * cs;
    if (m < 12.5) return setLum(setSat(cs, satOf(cb)), lum2(cb));
    if (m < 13.5) return setLum(setSat(cb, satOf(cs)), lum2(cb));
    if (m < 14.5) return setLum(cs, lum2(cb));
    return setLum(cb, lum2(cs));
  }
  float maskVal(vec2 uv){
    float m = 1.0;
    if (uMType > 0.5 && uMType < 1.5) { m = texture(uMask, uv).r; }
    else if (uMType > 1.5 && uMType < 2.5) {
      vec2 a = uMP.xy * uDoc, b = uMP.zw * uDoc, ab = b - a;
      float t = clamp(dot(uv * uDoc - a, ab) / max(dot(ab, ab), 1e-6), 0.0, 1.0);
      m = 1.0 - t * t * (3.0 - 2.0 * t);
    } else if (uMType > 2.5) {
      vec2 d = (uv * uDoc - uMP.xy * uDoc) / (uMP.zw * uDoc.x);
      float dd = length(d), inner = max(0.0, 1.0 - uMFeather);
      m = dd >= 1.0 ? 0.0 : (inner >= 0.9999 ? 1.0 : 1.0 - sst(inner, 1.0, dd));
    }
    return uMInv > 0.5 ? 1.0 - m : m;
  }
  void main(){
    vec4 d = texture(uDst, vUv);
    vec4 s;
    if (uFull > 0.5) { s = texture(uSrc, vUv); }
    else {
      vec2 p = vUv * uDoc - uC;
      float cr = cos(uRot), sr = sin(uRot);
      vec2 q = vec2(cr * p.x + sr * p.y, -sr * p.x + cr * p.y) * uFlip;
      vec2 t = q / uS + 0.5;
      if (t.x < 0.0 || t.y < 0.0 || t.x > 1.0 || t.y > 1.0) { oc = d; return; }
      s = texture(uSrc, t);
      if (uPremul > 0.5) s.rgb = s.a > 1e-4 ? s.rgb / s.a : vec3(0.0);
    }
    float as = s.a * uOpacity * maskVal(vUv);
    if (uUseClip > 0.5) as *= texture(uClip, vUv).a;
    float ab = d.a;
    float ar = as + ab * (1.0 - as);
    if (ar <= 1e-6) { oc = vec4(0.0); return; }
    vec3 cb = clamp(d.rgb, 0.0, 1.0), cs = clamp(s.rgb, 0.0, 1.0);
    vec3 B = blendRGB(uMode, cb, cs);
    vec3 cr2 = ((1.0 - as) * ab * cb + (1.0 - ab) * as * cs + as * ab * B) / ar;
    oc = vec4(cr2, ar);
  }`),

  /** لایهٔ تنظیم / روتوش: مخلوطِ پیش‌زمینه با نسخهٔ تنظیم‌شده زیرِ ماسک */
  mix: sh(`uniform sampler2D uDst; uniform sampler2D uAdj; uniform sampler2D uMask; uniform sampler2D uBrush;
  uniform vec2 uDoc; uniform float uOpacity; uniform float uUseBrush;
  uniform float uMType; uniform float uMInv; uniform vec4 uMP; uniform float uMFeather;
  float maskVal(vec2 uv){
    float m = 1.0;
    if (uMType > 0.5 && uMType < 1.5) { m = texture(uMask, uv).r; }
    else if (uMType > 1.5 && uMType < 2.5) {
      vec2 a = uMP.xy * uDoc, b = uMP.zw * uDoc, ab = b - a;
      float t = clamp(dot(uv * uDoc - a, ab) / max(dot(ab, ab), 1e-6), 0.0, 1.0);
      m = 1.0 - t * t * (3.0 - 2.0 * t);
    } else if (uMType > 2.5) {
      vec2 d = (uv * uDoc - uMP.xy * uDoc) / (uMP.zw * uDoc.x);
      float dd = length(d), inner = max(0.0, 1.0 - uMFeather);
      m = dd >= 1.0 ? 0.0 : (inner >= 0.9999 ? 1.0 : 1.0 - sst(inner, 1.0, dd));
    }
    return uMInv > 0.5 ? 1.0 - m : m;
  }
  void main(){
    vec4 d = texture(uDst, vUv);
    vec4 a = texture(uAdj, vUv);
    float k = uOpacity * maskVal(vUv);
    if (uUseBrush > 0.5) k *= texture(uBrush, vUv).r;
    oc = vec4(mix(d.rgb, a.rgb, k), d.a);
  }`),

  /**
   * مایع‌سازی (فضای عکس): out(u,v) = src(u+dx, v+dy). نقشه (uF، RG32F، gw×gh، آفستِ نرمال) با قرارداد «مرکزِ سلول» و نمونه‌برداریِ
   * دوخطیِ دستی (texelFetch، بی نیاز به float-linear) بزرگ می‌شود — همان cv2.resize ِ liquify.py؛ نمونه از عکس دوخطی در میپِ ۰
   * (مثلِ INTER_LINEAR) با لبهٔ clamp.
   */
  liquify: sh(`uniform sampler2D uT; uniform sampler2D uF; uniform vec2 uG;
  vec2 fld(ivec2 c){ c = clamp(c, ivec2(0), ivec2(uG) - 1); return texelFetch(uF, c, 0).rg; }
  void main(){
    vec2 p = vUv * uG - 0.5;
    vec2 f0 = floor(p);
    vec2 t = p - f0;
    ivec2 i0 = ivec2(f0);
    vec2 a = mix(fld(i0), fld(i0 + ivec2(1, 0)), t.x);
    vec2 b = mix(fld(i0 + ivec2(0, 1)), fld(i0 + ivec2(1, 1)), t.x);
    vec2 d = mix(a, b, t.y);
    oc = textureLod(uT, vUv + d, 0.0);
  }`),

  /**
   * قرمزیِ چشم (لایهٔ redeye؛ همان فرمولِ redeye.py): چشم‌ها پشتِ هم به ترتیبِ فهرست؛ uE = [x_px, y_px, r_px] به ازای هر چشم (≤۱۶).
   * k = پیدایی × ماسکِ لایه؛ نتیجه با رنگِ پیشین lerp می‌شود (مثلِ لایهٔ تنظیم).
   */
  redeye: sh(`uniform sampler2D uDst; uniform sampler2D uMask;
  uniform vec2 uDoc; uniform float uOpacity; uniform float uAmount; uniform float uDarken; uniform float uN; uniform float uE[48];
  uniform float uMType; uniform float uMInv; uniform vec4 uMP; uniform float uMFeather;
  float maskVal(vec2 uv){
    float m = 1.0;
    if (uMType > 0.5 && uMType < 1.5) { m = texture(uMask, uv).r; }
    else if (uMType > 1.5 && uMType < 2.5) {
      vec2 a = uMP.xy * uDoc, b = uMP.zw * uDoc, ab = b - a;
      float t = clamp(dot(uv * uDoc - a, ab) / max(dot(ab, ab), 1e-6), 0.0, 1.0);
      m = 1.0 - t * t * (3.0 - 2.0 * t);
    } else if (uMType > 2.5) {
      vec2 d = (uv * uDoc - uMP.xy * uDoc) / (uMP.zw * uDoc.x);
      float dd = length(d), inner = max(0.0, 1.0 - uMFeather);
      m = dd >= 1.0 ? 0.0 : (inner >= 0.9999 ? 1.0 : 1.0 - sst(inner, 1.0, dd));
    }
    return uMInv > 0.5 ? 1.0 - m : m;
  }
  void main(){
    vec4 d = texture(uDst, vUv);
    vec3 c = clamp(d.rgb, 0.0, 1.0);
    vec2 p = vUv * uDoc;
    int n = int(uN + 0.5);
    for (int i = 0; i < 16; i++) {
      if (i >= n) break;
      vec2 e = vec2(uE[i * 3], uE[i * 3 + 1]);
      float r = uE[i * 3 + 2];
      float w = 1.0 - sst(0.75 * r, 1.2 * r, length(p - e));
      float neutral = (c.g + c.b) * 0.5;
      float ratio = c.r / max(1e-4, neutral + 0.04);
      float m = sst(1.4, 2.4, ratio) * sst(0.15, 0.35, c.r) * w * uAmount;
      float nr = c.r + (min(c.r, neutral * (1.0 - 0.5 * uDarken)) - c.r) * m;
      float k = 1.0 - 0.4 * uDarken * m;
      c = vec3(nr, c.g * k, c.b * k);
    }
    float k = uOpacity * maskVal(vUv);
    oc = vec4(mix(d.rgb, c, k), d.a);
  }`),

  /** روتوش: نمونه از جابه‌جاییِ dst؛ ترمیم = + (تارِ مقصد − تارِ منبع) */
  retouchSample: sh(`uniform sampler2D uDst; uniform sampler2D uBlur; uniform vec2 uOff; uniform float uHeal;
  void main(){
    vec3 s = texture(uDst, vUv + uOff).rgb;
    if (uHeal > 0.5) s += texture(uBlur, vUv).rgb - texture(uBlur, vUv + uOff).rgb;
    oc = vec4(s, 1.0);
  }`),

  /** نمایش: صفحه ⇐ ماتریس ⇐ مختصاتِ پیکسلِ ترکیب */
  display: sh(`uniform sampler2D uA; uniform sampler2D uB; uniform mat3 uM; uniform vec2 uRes; uniform vec2 uDocSize;
  uniform float uSplit; uniform float uBefore; uniform vec3 uBg; uniform float uMax; uniform sampler2D uSel; uniform float uSelOn;
  void main(){
    vec2 sp = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);
    vec3 h = uM * vec3(sp, 1.0);
    vec2 uv = (h.xy / h.z) / uDocSize;
    vec3 bg = uBg;
    float chk = mod(floor(sp.x / 10.0) + floor(sp.y / 10.0), 2.0);
    vec3 pat = mix(vec3(0.82), vec3(0.94), chk);
    if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0 || h.z <= 0.0) { oc = vec4(bg, 1.0); return; }
    bool before = uBefore > 0.5 || (uSplit >= 0.0 && sp.x < uSplit);
    vec4 c = before ? texture(uB, uv) : texture(uA, uv);
    vec3 rgb = clamp(c.rgb, 0.0, 1.0);
    float a = clamp(c.a, 0.0, 1.0);
    rgb = mix(pat, rgb, a);
    if (uSelOn > 0.5) { float sv = texture(uSel, uv).r; rgb = mix(rgb, vec3(1.0, 0.25, 0.3), sv * 0.38); }
    if (uSplit >= 0.0 && abs(sp.x - uSplit) < 1.0) rgb = vec3(1.0);
    oc = vec4(rgb, 1.0);
  }`),
};
