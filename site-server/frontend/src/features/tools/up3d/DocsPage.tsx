import { Link } from "react-router-dom";

import { openTool } from "../../../components/Layout";
import { Card, PageHeader, Table } from "../../../components/ui";
import { P } from "./api";

/** راهنمای UpMarket 3D — همان docs.html ِ قدیمی، با نشانی‌های تازهٔ API زیرِ /api/v1/up3d/. */

const SECTIONS = [
  ["flow", "۱. روندِ کار"],
  ["three", "۲. سه راهِ ساخت"],
  ["scene", "۳. سندِ صحنه"],
  ["api", "۴. API"],
  ["sdk", "۵. SDK پایتون و خطِ فرمان"],
  ["quality", "۶. کیفیت و سخت‌افزار"],
  ["extend", "۷. توسعه (حرفه‌ای‌تر کردن)"],
  ["game", "۸. بازی، مدل، وب"],
  ["files", "۹. ساختارِ پوشه‌ها"],
  ["packs", "۱۰. بستهٔ دارایی (محیط، شخص، حرکت)"],
];

const SCENE_JSON = `{
 "format": "up3d.scene/1",
 "meta": {"title": "عطر رز"},
 "output": {"aspect": "9:16", "fps": 24, "duration": 13.5},
 "environment": {"id": "studio_warm", "params": {"backdrop_color": "#d8cbbd"}},
 "lighting": {"id": "soft_beauty", "params": {"intensity": 1.0, "warmth": 0.2}},
 "actors":   [{"id": "host", "character": "presenter_f_01", "mark": "center", "params": {"outfit": "elegant"}}],
 "products": [{"id": "p1", "asset": "perfume_bottle", "name": "عطر رز", "surface": "table_right",
               "params": {"brand": "UpMarket", "liquid_color": "#e8b04a", "label_image": "/path/logo.png"}}],
 "actions":  [{"actor": "host", "motion": "pick_up", "start": 2.0, "duration": 1.5, "params": {"product": "p1"}}],
 "speech":   [{"actor": "host", "text": "سلام! با عطرِ رز آشنا بشید.", "start": 0.3, "voice": "fa_female_nova"}],
 "expressions": [{"actor": "host", "expression": "smile", "start": 3, "duration": 2, "intensity": 0.7}],
 "gaze":     [{"actor": "host", "target": "product:p1", "start": 2, "duration": 1}],
 "shots":    [{"shot": "medium", "start": 0, "duration": 4, "subject": "host", "move": "push_in"}],
 "overlays": [{"type": "cta", "text": "سفارش در آپ‌مارکت", "start": 11, "duration": 2.5}],
 "audio": {"subtitles": true, "music": null, "music_volume": 0.14}
}`;

const API_ROWS: [string, string, string][] = [
  ["GET/POST", "/api/v1/up3d/video-projects/", "فهرست / ساخت ‎{brief, mode: ai|template, template}"],
  ["GET/DELETE", "/api/v1/up3d/video-projects/{id}/", "وضعیت، سند، کارها، نسخه‌ها / حذف"],
  ["POST", "/api/v1/up3d/video-projects/{id}/plan/", "برنامه‌ریزیِ دوباره"],
  ["GET/PUT", "/api/v1/up3d/video-projects/{id}/scene/", "خواندن/نوشتنِ سند (repair=1 ترمیم)"],
  ["POST", "/api/v1/up3d/video-projects/{id}/edit/", "ویرایش با زبانِ طبیعی ‎{instruction}"],
  ["POST", "/api/v1/up3d/video-projects/{id}/preview/", "‎{profile: animatic|preview}"],
  ["POST", "/api/v1/up3d/video-projects/{id}/render/", "‎{profile: standard|high|ultra}"],
  ["POST", "/api/v1/up3d/video-projects/{id}/export/", "‎{format: glb|fbx|usd|blend|game_pack}"],
  ["POST", "/api/v1/up3d/video-projects/{id}/contact/", "‎{count: 6} فریم‌های نمونه"],
  ["GET", "/api/v1/up3d/video-projects/{id}/result/", "لینکِ ویدئوی نهایی"],
  ["POST", "/api/v1/up3d/scenes/", "ساختِ پروژه از سندِ آماده (SDK)"],
  ["POST", "/api/v1/up3d/validate/", "وارسی/ترمیمِ یک سند"],
  ["GET", "/api/v1/up3d/jobs/ · jobs/{id}/", "فهرست/وضعیتِ کار (?active=1 فقط در جریان)"],
  ["POST", "/api/v1/up3d/jobs/{id}/cancel/", "لغوِ کار"],
  ["GET", "/api/v1/up3d/assets/?kind=", "دفترِ دارایی‌ها"],
  ["GET", "/api/v1/up3d/estimate/?profile=&project=", "تخمینِ زمانِ رندر"],
  ["*", "/3d/api/worker/…", "پروتکلِ کارگرِ رندر (توکنِ کارگر)"],
];

function H2({ children }: { children: string }) {
  return (
    <h2 className="mb-2 text-lg font-bold" style={{ color: "var(--text)" }}>
      {children}
    </h2>
  );
}

function H3({ children }: { children: string }) {
  return (
    <h3 className="mb-1 font-bold" style={{ color: "var(--text)" }}>
      {children}
    </h3>
  );
}

export default function DocsPage() {
  const server = window.location.origin;
  const text = { color: "var(--text-2)" } as const;

  return (
    <div className="space-y-4">
      <PageHeader title="راهنمای UpMarket 3D" />
      <div className="u3d-docs">
        <Card>
          <nav>
            {SECTIONS.map(([id, name]) => (
              <a key={id} href={`#${id}`}>
                {name}
              </a>
            ))}
          </nav>
        </Card>
        <div className="space-y-4 text-sm leading-7" style={text}>
          <Card>
            <section id="flow">
              <H2>۱. روندِ کار</H2>
              <ol style={{ listStyle: "decimal" }}>
                <li>
                  <b>پروژهٔ تازه:</b> محصول (نام، شکل، برچسب/عکس، رنگ)، مجری، محیط، صدا و یک درخواستِ آزاد.
                </li>
                <li>
                  <b>برنامه‌ریزی:</b> کارگردانِ هوشِ مصنوعی «سندِ صحنه» را می‌نویسد؛ وارس‌گر آن را چک و خودکار ترمیم می‌کند (اگر AI در دسترس
                  نباشد، قالبِ قاعده‌محور).
                </li>
                <li>
                  <b>ویرایش:</b> در خطِ زمان شات، حرکت، گفتار، حالتِ چهره، نگاه و نوشته را جابه‌جا/عوض کنید، یا به زبانِ فارسی از AI بخواهید.
                </li>
                <li>
                  <b>انیمیک</b> (چند دقیقه) ⇐ <b>پیش‌نمایش</b> با نورِ واقعی ⇐ <b>رندرِ نهایی</b> روی کارگرِ GPU.
                </li>
                <li>
                  <b>خروجی:</b> MP4 با صدای فارسی، هماهنگیِ لب، زیرنویس و دعوت به خرید + کنترلِ کیفیتِ خودکار؛ و GLB/FBX/BLEND برای بازی و
                  نرم‌افزارهای سه‌بعدی.
                </li>
              </ol>
              <p>
                وضعیت‌های هر کار: <code>PENDING ⇐ PLANNING ⇐ PLANNED ⇐ SCENE_BUILDING ⇐ RENDERING ⇐ QUALITY_CHECK ⇐ ASSEMBLING ⇐ COMPLETED</code>{" "}
                (یا FAILED/CANCELLED).
              </p>
            </section>
          </Card>

          <Card>
            <section id="three">
              <H2>۲. سه راهِ ساخت — همه روی یک سند</H2>
              <div className="grid gap-4 md:grid-cols-3">
                <div>
                  <H3>هوشِ مصنوعی</H3>
                  <p>
                    در «پروژهٔ تازه» یا تبِ «ویرایش با هوشِ مصنوعی». مدل فقط از کتابخانه انتخاب می‌کند و خروجی‌اش وارسی می‌شود؛ هیچ‌وقت حرکتِ
                    «خیالی» نمی‌سازد. تنظیمِ سرویس/کلید/مدل در{" "}
                    <button type="button" className="underline" onClick={() => openTool("/admin/up3d/aisettings/1/change/")} style={{ color: "var(--brand-strong)" }}>
                      جنگو ادمین
                    </button>{" "}
                    (Metis، OpenAI یا هر سرویسِ سازگار با کتابخانهٔ openai).
                  </p>
                </div>
                <div>
                  <H3>محیطِ گرافیکی</H3>
                  <p>
                    صفحهٔ هر پروژه پنج گام دارد: ۱ محصول، مجری و صحنه · ۲ حرکت و دوربین (خطِ زمانِ شش‌شیاره، بازرس، وارسیِ زنده، ویرایش با AI) ·
                    ۳ متن، صدا و موسیقی · ۴ کیفیت و رندر (پروفایل + تنظیمِ دستیِ وضوح/نمونه/گام) · ۵ خروجی‌ها. کد و نسخه‌ها زیرِ «ابزارهای پیشرفته»؛
                    کارتِ چسبانِ «خلاصه و وضعیت» می‌گوید چه چیزی، با چه کیفیتی، روی کدام کارگر و چقدر.
                  </p>
                </div>
                <div>
                  <H3>کد</H3>
                  <p>
                    SDK ِ پایتون (<code>up3d.sdk.Scene</code>)، خطِ فرمان (<code>python -m up3d</code>) و REST API. تبِ «کد» ِ هر پروژه همان
                    صحنه را به‌صورتِ کد نشان می‌دهد.
                  </p>
                </div>
              </div>
            </section>
          </Card>

          <Card>
            <section id="scene">
              <H2>۳. سندِ صحنه (up3d.scene/1)</H2>
              <p>قراردادِ مشترکِ همهٔ بخش‌ها. زمان‌ها ثانیه‌اند؛ تبدیل به فریم فقط در compiler.</p>
              <pre className="u3d-pre">{SCENE_JSON}</pre>
              <p className="mt-2">
                قاعده‌های وارسی: حرکت‌های بدنِ یک بازیگر هم‌پوشانی ندارند (حرکت‌های «لایه» مثلِ nod/look_at دارند)؛ مدتِ هر حرکت در بازهٔ مجاز؛
                «گرافِ حرکت»: محصول اول برداشته شود بعد نشان داده/چرخانده/گذاشته شود؛ شات‌ها کلِ زمان را بی‌فاصله بپوشانند؛ گفتار در زمان جا شود.
                «ترمیمِ خودکار» بیشترِ این‌ها را خودش درست می‌کند (مثلاً «برداشتن» را پیش از «نشان‌دادن» اضافه می‌کند).
              </p>
            </section>
          </Card>

          <Card padded={false}>
            <section id="api" className="p-5">
              <H2>۴. API</H2>
              <p>
                توکن: <Link to={P.token()} style={{ color: "var(--brand-strong)" }}>صفحهٔ «توکنِ API»</Link> ⇐ سرآیندِ{" "}
                <code>Authorization: Token …</code>. همان نشانی‌ها با JWT ِ پنل هم کار می‌کنند. همهٔ آن‌ها فقط برای کارکنان بازند.
              </p>
              <Table>
                <thead>
                  <tr>
                    <th>روش</th>
                    <th>نشانی</th>
                    <th>کار</th>
                  </tr>
                </thead>
                <tbody>
                  {API_ROWS.map(([m, u, d]) => (
                    <tr key={u}>
                      <td className="u3d-mono">{m}</td>
                      <td className="u3d-mono">{u}</td>
                      <td>{d}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <pre className="u3d-pre mt-3">{`curl -X POST -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \\
  -d '{"brief": {"product_name": "عطر رز", "request": "یک خانم عطر را بردارد و معرفی کند"}, "mode": "ai"}' \\
  ${server}/api/v1/up3d/video-projects/`}</pre>
            </section>
          </Card>

          <Card>
            <section id="sdk">
              <H2>۵. SDK ِ پایتون و خطِ فرمان</H2>
              <pre className="u3d-pre">{`from up3d.sdk import Scene
s = (Scene('عطر رز', duration=12)
     .environment('studio_warm').lighting('soft_beauty')
     .actor('host', 'presenter_f_01')
     .product('p1', 'perfume_bottle', name='عطر رز', surface='table_right', brand='UpMarket')
     .at(0.3).do('host', 'wave_hello').say('host', 'سلام! با عطرِ رز آشنا بشید.')
     .at(2.2).do('host', 'pick_up', product='p1').do('host', 'present', product='p1')
     .shot('medium', 0, move='push_in').shot('product_macro', 4.2, subject='p1', move='orbit_left')
     .overlay('cta', 'سفارش در آپ‌مارکت', 9.5, 2.5))
print(s.validate(repair=True))
s.render('preview', server='${server}', token='...')`}</pre>
              <pre className="u3d-pre mt-2">{`python -m up3d assets motion                       # فهرستِ حرکت‌ها
python -m up3d template showcase --brief brief.json -o scene.json
python -m up3d plan --brief brief.json -o scene.json     # کارگردانِ AI
python -m up3d validate scene.json --repair -o fixed.json
python -m up3d render scene.json --profile preview  # کلِ خط روی همین ماشین
python -m up3d export scene.json --format glb
python -m up3d worker --server ${server}/3d --token T  # کارگرِ رندر`}</pre>
            </section>
          </Card>

          <Card padded={false}>
            <section id="quality" className="p-5">
              <H2>۶. کیفیت و سخت‌افزار</H2>
              <Table>
                <thead>
                  <tr>
                    <th>سطح</th>
                    <th>موتور</th>
                    <th>وضوح</th>
                    <th>کجا</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>انیمیک</td>
                    <td>Workbench</td>
                    <td>360×640</td>
                    <td>سرور — برای وارسیِ حرکت و زمان</td>
                  </tr>
                  <tr>
                    <td>پیش‌نمایش</td>
                    <td>Cycles ۱۴ نمونه + حذفِ نویز، ۱۲fps ⇐ ۲۴</td>
                    <td>360×640</td>
                    <td>سرور (کند ولی شدنی)</td>
                  </tr>
                  <tr>
                    <td>استاندارد</td>
                    <td>Cycles ۶۴، تاریِ حرکت، پوستِ زیرتقسیم‌شده</td>
                    <td>720×1280</td>
                    <td>GPU</td>
                  </tr>
                  <tr>
                    <td>بالا</td>
                    <td>Cycles ۱۹۲</td>
                    <td>1080×1920</td>
                    <td>GPU (مثلاً RTX 3060)</td>
                  </tr>
                  <tr>
                    <td>4K</td>
                    <td>Cycles ۵۱۲، زیرتقسیمِ ۲</td>
                    <td>2160×3840</td>
                    <td>GPU ِ قوی</td>
                  </tr>
                </tbody>
              </Table>
              <p className="mt-3">
                سرورِ فعلی ۲ هسته و بی‌کارتِ گرافیک است؛ برای همین سطح‌های بالا به «کارگرِ GPU» می‌روند. همان صحنه روی سیستمِ قوی‌تر خودکار
                کیفیتِ بیشتری می‌دهد. واقع‌گرایی علاوه بر سخت‌افزار به دارایی‌ها بستگی دارد: کاراکترِ اسکن‌شده، موی رشته‌ای، HDRI و بافتِ PBR ِ
                واقعی — همه به‌صورتِ «بستهٔ دارایی» قابلِ افزودن‌اند (بخشِ ۷).
              </p>
            </section>
          </Card>

          <Card>
            <section id="extend">
              <H2>۷. توسعه: حرفه‌ای‌تر کردن بدونِ بازنویسی</H2>
              <ul style={{ listStyle: "disc" }}>
                <li>
                  <b>کاراکترِ تازه (MPFB):</b> پوشهٔ <code>assets/characters/&lt;id&gt;/manifest.json</code> با دستورِ ساخت (جنسیت، سن، اندام،
                  پوست، مو، لباس).
                </li>
                <li>
                  <b>کاراکترِ ممتاز/اسکن‌شده:</b> <code>"provider": "file"</code> + فایلِ <code>.blend/.glb/.fbx</code> + نقشهٔ استخوان در{" "}
                  <code>engine/rigs/&lt;name&gt;.json</code> (نقش‌ها: دست، پا، ستون، سر، چشم، انگشت + نامِ shape key های صورت). حرکت‌ها همه
                  روی نقش‌اند، پس بی‌تغییر کار می‌کنند.
                </li>
                <li>
                  <b>حرکتِ تازه:</b> یک تابع با <code>@motion('id')</code> در <code>engine/up3d_engine/motions.py</code> + manifest (مدت،
                  نیاز، اثر، پارامترها). راهِ بعدی: منبعِ «کلیپ» (Mocap/BVH) با همان قرارداد.
                </li>
                <li>
                  <b>محیطِ تازه:</b> تابعِ <code>@env('name')</code> یا <code>"builder": "blend_file"</code> برای صحنهٔ آماده/اسکن‌شده؛ جایگاه‌ها
                  و سطح‌ها در manifest.
                </li>
                <li>
                  <b>بافتِ واقعی و HDRI:</b> پوشه‌های <code>assets/textures/&lt;id&gt;/</code> (نام‌گذاریِ ambientCG/PolyHaven) و{" "}
                  <code>assets/hdri/</code>؛ موادِ رویه‌ای خودکار جایشان را می‌دهند.
                </li>
                <li>
                  <b>محصول:</b> سازندهٔ تازه در <code>products.py</code> یا مدلِ GLB ِ خودِ فروشنده (<code>custom_model</code>).
                </li>
                <li>
                  <b>نور، نمای دوربین، کیفیتِ رندر، صدا:</b> فقط JSON.
                </li>
                <li>
                  <b>موتورِ رندرِ دیگر</b> (مثلاً Unreal): ورودی‌اش همان <code>compiled.json</code> است (همهٔ زمان‌ها به فریم، همهٔ دارایی‌ها
                  با مسیر).
                </li>
                <li>
                  <b>صدا:</b> فراهم‌کنندهٔ تازه در <code>up3d/tts.py</code> (Piper آفلاین آماده است).
                </li>
              </ul>
            </section>
          </Card>

          <Card>
            <section id="game">
              <H2>۸. بازی، مدل و وب</H2>
              <p>
                «خروجیِ GLB» کلِ صحنه را با انیمیشنِ پخته‌شده (IK و نگاه به کلید تبدیل می‌شود)، حالت‌های چهره و دوربین‌ها می‌دهد؛ در نمایشگرِ
                داخلی (three.js)، Unity، Unreal، Godot و Blender باز می‌شود. «BLEND» کلِ صحنه را برای کارِ حرفه‌ای در Blender نگه می‌دارد.
                کاراکترها و حرکت‌ها همان دارایی‌های بازی‌اند.
              </p>
            </section>
          </Card>

          <Card>
            <section id="packs">
              <H2>۱۰. بستهٔ دارایی: محیط/صحنه، شخص و حرکتِ تازه بی‌کد</H2>
              <p className="text-sm" style={text}>
                در <Link to={P.assets()} className="underline">کتابخانهٔ دارایی‌ها ← بسته‌های دارایی</Link> یک zip بارگذاری کنید: هر پوشه یک{" "}
                <code className="u3d-mono">manifest.json</code> با «kind» (environment، person، animation، product، lighting، camera) و
                فایل‌هایش — محیط از glb/fbx/obj/blend، شخص از glb/fbx ِ اسکلت‌دار (Mixamo، Ready Player Me؛ rigmap: auto/mixamo) یا دستورِ
                ساختِ MPFB، حرکت از BVH یا FBX (روی هر بازیگری بازهدف‌گیری می‌شود). وارسی پیش از نصب، روشن/خاموش و حذف از همان صفحه؛
                راهنمای کامل با نمونه و «بستهٔ نمونه (zip)» همان‌جاست. API: <code className="u3d-mono">GET/POST /api/v1/up3d/asset-packs/</code>
                (multipart: file، replace، dry_run)، <code className="u3d-mono">POST …/asset-packs/&lt;id&gt;/toggle/</code>،{" "}
                <code className="u3d-mono">DELETE …/asset-packs/&lt;id&gt;/</code>.
              </p>
            </section>
          </Card>
          <Card>
            <section id="files">
              <H2>۹. ساختارِ پوشه‌ها (UP3D_ROOT)</H2>
              <pre className="u3d-pre">{`up3d/        هستهٔ مستقل از موتور (سند، وارسی، compiler، AI، صدا، لب، مونتاژ، کارگر، SDK، CLI)
engine/      اجرای داخلِ Blender (کاراکتر، ریگ و IK، حرکت، چهره، محصول، محیط، نور، دوربین، رندر، خروجی)
assets/      دفترِ دارایی‌ها (manifest ها) + فونت
worker-windows/  راه‌اندازیِ کارگرِ GPU روی ویندوز
backend/apps/up3d/   پنل (Django + DRF): مدل‌ها، سرویس‌ها، API و پروتکلِ کارگر
data/up3d/   کارها، بارگذاری‌ها، بستهٔ کارگر (پشتیبان‌گیری)
vendor/      Blender 4.5 LTS و افزونهٔ MPFB2 با داده‌ها`}</pre>
            </section>
          </Card>
        </div>
      </div>
    </div>
  );
}
