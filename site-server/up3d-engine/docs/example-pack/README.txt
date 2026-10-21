بستهٔ نمونهٔ UpMarket 3D
========================
هر پوشه یک دارایی است با manifest.json (و فایل‌هایش کنارِ آن).
  room_simple/        محیط از فایلِ glb (builder: model_file) + جایگاهِ بازیگر (marks) + سطحِ محصول (surfaces)
  presenter_young_m/  شخصِ ساخته‌شده با MPFB (دستورِ ساخت؛ بی‌فایل). شخصِ آماده: provider=file + path=x.glb/x.fbx + rigmap
  wave_mocap/         حرکتِ mocap از فایلِ BVH (source.type=clip). FBX ِ Mixamo هم: "rig": "mixamo"
  light_sunset/       نور: HDRI ِ داخلیِ Blender (sunset) + یک نورِ کلید
  cam_hero_low/       نمای دوربین: ارتفاعِ قاب، لنز، زاویه
مختصات به متر؛ بازیگر در جایگاهِ center رو به -Y (رو به دوربین) می‌ایستد.
