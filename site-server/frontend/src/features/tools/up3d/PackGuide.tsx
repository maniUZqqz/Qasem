import { Card, Table } from "../../../components/ui";

/** راهنمای کوتاهِ فارسیِ «بستهٔ دارایی»: چیدمانِ zip، manifest ِ هر نوع، نمونه و محدودیت‌ها. */

const LAYOUT = `my-pack.zip
├── pack.json                     (اختیاری) {"id": "shop_pack", "name": "بستهٔ فروشگاه"}
├── my_room/                      یک پوشه = یک دارایی
│   ├── manifest.json             "kind": "environment"
│   └── room.glb
├── people/ali/                   نوع از نامِ پوشهٔ بالا هم فهمیده می‌شود
│   ├── manifest.json             (people، scenes، animations، products، lights، cameras)
│   └── ali.fbx
└── animations/dance_01/
    ├── manifest.json
    └── dance.bvh`;

const ENV = `{
  "kind": "environment",
  "id": "my_room",
  "name": {"fa": "مغازهٔ من", "en": "My shop"},
  "file": "room.glb",
  "scale": 1.0, "rotation_deg": 0, "offset": [0, 0, 0],
  "marks":    {"center": {"pos": [0, 0, 0], "facing": 0}},
  "surfaces": {"counter": {"pos": [0, -0.4, 0.9], "yaw": 0}},
  "add_table": false,
  "default_lighting": "warm_store",
  "license": "CC0"
}`;

const PERSON = `{
  "kind": "person",
  "id": "ali",
  "name": {"fa": "علی — مجریِ آقا"},
  "gender": "male",
  "path": "ali.fbx",
  "rigmap": "mixamo",
  "height_m": 1.78,
  "license": "Mixamo"
}`;

const PERSON_MPFB = `{
  "kind": "person", "id": "neda", "name": "ندا", "gender": "female",
  "provider": "mpfb",
  "macro": {"gender": 0.0, "age": 0.35, "weight": 0.45, "height": 0.55, "muscle": 0.5},
  "hair": "hair/long01/long01.mhclo", "hair_color": "#2b1a12"
}`;

const MOTION = `{
  "kind": "animation",
  "id": "dance_01",
  "name": {"fa": "رقصِ کوتاه"},
  "source": {"type": "clip", "file": "dance.bvh", "rig": "auto",
             "channels": ["spine", "neck", "arms", "fingers"],
             "loop": false, "speed": 1.0},
  "duration": {"min": 1, "default": 4, "max": 8},
  "license": "CC0"
}`;

const PRODUCT = `{
  "kind": "product", "id": "my_bottle", "name": "بطریِ من",
  "file": "bottle.glb",
  "dimensions": [0.07, 0.07, 0.18],
  "grasp": {"height": 0.4, "radius": 0.035}
}`;

const LIGHT = `{
  "kind": "lighting", "id": "golden_hour", "name": "ساعتِ طلایی",
  "world": {"hdri": "sky.exr", "hdri_strength": 0.8},
  "rig": [{"type": "AREA", "azimuth": -45, "elevation": 25, "distance": 2,
           "size": 1.2, "power": 150, "kelvin": 3800, "target": "face"}]
}`;

const CAMERA = `{
  "kind": "camera", "id": "low_hero", "name": "نمای پایین",
  "subject": "actor",
  "framing": {"height": 1.1, "lens": 35, "fstop": 2.8, "elevation": -8,
              "azimuth": 15, "anchor": "chest"},
  "moves": ["static", "push_in", "orbit_left"]
}`;

function Pre({ children }: { children: string }) {
  return (
    <pre className="u3d-pre mt-1" dir="ltr" style={{ textAlign: "left", fontSize: 12 }}>
      {children}
    </pre>
  );
}

function H({ children }: { children: string }) {
  return (
    <h3 className="mt-4 mb-1 font-bold" style={{ color: "var(--text)" }}>
      {children}
    </h3>
  );
}

export default function PackGuide() {
  const t = { color: "var(--text-2)" } as const;
  return (
    <Card>
      <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>
        راهنمای بستهٔ دارایی
      </h2>
      <p className="mt-1 text-sm" style={t}>
        هر دارایی یک پوشه است با <code className="u3d-mono">manifest.json</code> و فایل‌هایش کنارِ آن. «kind» یکی از
        environment (یا scene/location)، person (character)، animation (motion)، product، lighting، camera (shot) است. شناسه (id)
        فقط حروفِ کوچکِ انگلیسی، عدد، _ و -؛ اگر با دارایی‌ای در کتابخانه یکی باشد، نسخهٔ بسته جایش را می‌گیرد. مختصات به متر؛
        بازیگر روی «جایگاه» رو به ‎-Y (رو به دوربین) می‌ایستد، راستِ او ‎-X است.
      </p>
      <Pre>{LAYOUT}</Pre>

      <H>محیط / صحنه — فایلِ glb، gltf، fbx، obj یا blend</H>
      <p className="text-sm" style={t}>
        <b>marks</b> جای ایستادنِ بازیگر، <b>surfaces</b> جای گذاشتنِ محصول (ارتفاعِ رویهٔ میز/پیشخوان). اگر surfaces نیاید، یک میزِ
        گرد جلوی بازیگر و سه سطح روی آن ساخته می‌شود. نورهای خودِ فایل حذف می‌شوند (keep_lights: true نگهشان می‌دارد) و نورپردازی از
        default_lighting می‌آید. برای کفِ ساده: add_floor: true.
      </p>
      <Pre>{ENV}</Pre>

      <H>شخص — کاراکترِ اسکلت‌دار (Mixamo، Ready Player Me، …) یا دستورِ ساختِ MPFB</H>
      <p className="text-sm" style={t}>
        rigmap: <code className="u3d-mono">auto</code> (پیدا کردنِ خودکار)، <code className="u3d-mono">mixamo</code>،{" "}
        <code className="u3d-mono">mpfb_default</code> یا دیکشنریِ نقش‌ها ‎{"{"}"roles": {"{"}"hips": "...", "spine": [...], "head": "...",
        "arm.R": {"{"}"upper","fore","hand"{"}"}, "leg.R": {"{"}"upper","lower","foot"{"}"}, "fingers.R": {"{"}...{"}"}{"}"}{"}"}‎.
        پیشوندِ mixamorig: مهم نیست. اندازه، چرخش و جهت خودکار درست می‌شود (height_m قد را دقیق می‌کند؛ facing_deg اگر باز هم کج بود).
        شکلِ صورت (viseme_*، eyeBlinkLeft…) اگر در مش باشد لب‌خوانی و پلک هم کار می‌کند.
      </p>
      <Pre>{PERSON}</Pre>
      <Pre>{PERSON_MPFB}</Pre>

      <H>حرکت — کلیپِ mocap (BVH یا FBX)</H>
      <p className="text-sm" style={t}>
        روی هر بازیگری بازهدف‌گیری می‌شود (جهتِ هر استخوان، نه نامش؛ حالتِ T یا A فرقی نمی‌کند). rig: auto، mixamo، cmu یا
        mpfb_default (یا bone_map ِ دستی: ‎{"{"}"نامِ استخوانِ فایل": "arm.R.upper"{"}"}‎). channels: spine، neck، arms، fingers (پیش‌فرض
        = بالاتنه) + legs و root برای حرکتِ تمام‌بدن (راه رفتن، رقص). دستی که محصول گرفته رها نمی‌شود. مدتِ BVH خودکار خوانده می‌شود.
      </p>
      <Pre>{MOTION}</Pre>

      <H>محصول، نور، دوربین</H>
      <Pre>{PRODUCT}</Pre>
      <Pre>{LIGHT}</Pre>
      <Pre>{CAMERA}</Pre>

      <H>پذیرفته / نپذیرفته</H>
      <Table>
        <tbody>
          <tr>
            <td>پسوندهای مجاز</td>
            <td className="u3d-mono text-xs" dir="ltr">
              json png jpg webp tga tif exr hdr glb gltf bin fbx obj mtl blend bvh mp4 txt md
            </td>
          </tr>
          <tr>
            <td>حجم</td>
            <td>تا ۲۰۰ مگابایت در هر بارگذاری از پنل؛ بازشده حداکثر ۳ گیگابایت و ۴۰۰۰ فایل</td>
          </tr>
          <tr>
            <td>کارگرِ GPU</td>
            <td>فایل‌های دارایی‌های بسته همراهِ هر کار به کارگر (سرورِ پردازش) فرستاده می‌شوند؛ نصب روی گره لازم نیست</td>
          </tr>
          <tr>
            <td>تصویرِ کارت</td>
            <td>thumbnail.jpg کنارِ manifest، یا دکمهٔ «ساختِ تصویرِ این دسته با موتور» در کتابخانه</td>
          </tr>
        </tbody>
      </Table>
    </Card>
  );
}
