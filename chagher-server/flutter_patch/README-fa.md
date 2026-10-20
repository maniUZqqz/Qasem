# صفحه‌های تازهٔ اپِ فلاتر — آمادهٔ کپی در پروژه

این پوشه **سورسِ آمادهٔ Dart** چهار صفحهٔ تازه است. چون روی سرور فقط نسخهٔ
**بیلدشدهٔ** اپ هست (`frontend/web/main.dart.js`، بدونِ `pubspec.yaml` و `lib/`)،
نمی‌شد مستقیم به اپ اضافه کرد. پس کد را این‌جا گذاشتم تا در پروژهٔ فلاترِ خودتان
کپی و بیلد شود.

> ⚠ این فایل‌ها روی این سرور **کامپایل نشده‌اند** (فلاتر این‌جا نصب نیست). بعد از
> کپی، `flutter pub get` و بعد `flutter analyze` بزنید؛ اگر چیزی ایراد گرفت،
> بگویید تا همان‌جا درستش کنم.

## فایل‌ها

| فایل | کار |
|---|---|
| `chagher_api.dart` | کلاینتِ همهٔ APIهای تازه (یک جا، با مدیریتِ خطا) |
| `equipment_scan_page.dart` | **OCR ۱:** اسکنِ دستگاه‌های باشگاه با دوربین + تأیید |
| `form_check_page.dart` | **OCR ۲:** بررسیِ درستیِ حرکت، زنده، با کادرِ سبز/قرمز و خطِ زرد |
| `manual_program_page.dart` | برنامهٔ دستیِ مربی (بدونِ هوش مصنوعی) |
| `athlete_b2c_page.dart` | ورزشکارِ شخصی: مشخصات، اسکنِ باشگاه، توکن، برنامهٔ خودش |

## ۱) کپی

همه را در `lib/chagher_new/` بریزید (هر جای دیگری هم باشد فرقی نمی‌کند، فقط
`import`های نسبی را نگه دارید؛ فایل‌ها فقط همدیگر را صدا می‌زنند).

## ۲) وابستگی‌ها — `pubspec.yaml`

```yaml
dependencies:
  http: ^1.2.0
  image_picker: ^1.1.0      # برای اسکنِ دستگاه
  camera: ^0.11.0           # برای بررسیِ درستیِ حرکت (زنده)
```

بعد: `flutter pub get`

## ۳) اجازهٔ دوربین

**اندروید** — `android/app/src/main/AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.CAMERA" />
<uses-feature android:name="android.hardware.camera" android:required="false" />
```

**iOS** — `ios/Runner/Info.plist`:

```xml
<key>NSCameraUsageDescription</key>
<string>برای اسکنِ دستگاه‌ها و بررسیِ درستیِ حرکت به دوربین نیاز است.</string>
<key>NSPhotoLibraryUsageDescription</key>
<string>برای انتخابِ عکسِ دستگاه از گالری.</string>
```

**وب** — دوربینِ زنده فقط روی **HTTPS** کار می‌کند (قاعدهٔ خودِ مرورگر است).
روی `http://185.239.3.189:8000` مرورگر اجازه نمی‌دهد؛ صفحهٔ وبِ جنگو در این حالت
خودش به حالتِ «عکسی» می‌افتد.

## ۴) ساختنِ کلاینت

```dart
final api = ChagherApi(
  baseUrl: 'http://185.239.3.189:8000/chagher/api/',   // اسلشِ آخر لازم است
  token: userToken,                                    // همان توکنِ DRF که اپ دارد
);
```

## ۵) وصل‌کردنِ صفحه‌ها

```dart
// مربی
Navigator.push(context, MaterialPageRoute(
  builder: (_) => ManualProgramPage(api: api)));

Navigator.push(context, MaterialPageRoute(
  builder: (_) => EquipmentScanPage(api: api)));

// ورزشکارِ شخصی (B2C)
Navigator.push(context, MaterialPageRoute(
  builder: (_) => AthleteB2CPage(api: api)));
```

### دکمهٔ «بررسیِ درستیِ حرکت» — مهم

این قابلیت از **جنگو ادمین** خاموش و روشن می‌شود و وقتی خاموش است **نباید هیچ
نشانی از آن باشد**. پس دکمه را این‌طور بسازید:

```dart
FutureBuilder<Map<String, dynamic>?>(
  future: api.formCheckInfo(exercise.externalId),
  builder: (context, snap) {
    // null = قابلیت خاموش است ⇒ هیچ دکمه‌ای ساخته نمی‌شود
    if (snap.data == null) return const SizedBox.shrink();
    return FilledButton.icon(
      icon: const Icon(Icons.photo_camera),
      label: const Text('بررسیِ درستیِ حرکت با دوربین'),
      onPressed: () => Navigator.push(context, MaterialPageRoute(
        builder: (_) => FormCheckPage(
          api: api,
          externalId: exercise.externalId,
          exerciseName: exercise.nameFa,
        ),
      )),
    );
  },
)
```

## ۶) این صفحه‌ها چه چیزی را از سرور می‌گیرند

هیچ عددی داخلِ اپ ثابت نیست؛ همه از سرور می‌آید تا با عوض‌شدنِ تنظیماتِ ادمین،
اپ دوباره بیلد نشود:

- سهمِ رایگانِ برنامهٔ دستی و هزینهٔ توکنش
- هزینهٔ توکنِ اسکن و حداکثر عکسِ هر اسکن
- روشن/خاموشِ بررسیِ حرکت، فاصلهٔ فریم‌ها، سقفِ فریم و هزینه‌اش
- قدم‌های ورزشکارِ شخصی (`api/me/status/`)

## ۷) نکته‌های سازگاری

- کد با **Dart 3** نوشته شده (`super.key`، `records` استفاده نشده).
- اگر نسخهٔ فلاترِ شما قدیمی‌تر از ۳٫۱۰ است، `super.key` را به
  `Key? key`/`super(key: key)` برگردانید.
- `DropdownButtonFormField` در نسخه‌های تازه `initialValue` و در قدیمی‌ترها
  `value` می‌خواهد؛ این‌جا `value` نوشته شده که در هر دو کار می‌کند.
- اگر `withOpacity` در نسخهٔ شما هشدار داد، به `withValues(alpha: …)` عوضش کنید.

---

## پلِ وب (برای همین بیلدی که الان زنده است)

تا وقتی سورس نرسیده، صفحه‌های جنگو از داخلِ همین بیلد قابلِ دسترس‌اند:
`web_bridge/chagher-bridge.js` به‌صورتِ درون‌خطی در `frontend/web/index.html`
تزریق شده و یک دکمهٔ کوچک («⊞ ابزارهای چغر») می‌گذارد که با **ورودِ یک‌باره**
(`panel/sso/`) کاربر را بی‌ورودِ دوباره به صفحه می‌برد.

**بعد از هر بیلدِ تازه** یک‌بار این را بزنید تا پل برگردد:

```bash
python /www/wwwroot/Cheghar/flutter_patch/web_bridge/apply_bridge.py
```

وقتی سورسِ فلاتر رسید، این پل لازم نیست: همان صفحه‌ها را با فایل‌های Dartِ همین
پوشه داخلِ خودِ اپ می‌سازیم و پل را با `--remove` برمی‌داریم.
