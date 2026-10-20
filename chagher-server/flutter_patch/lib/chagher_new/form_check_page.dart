/// صفحهٔ «بررسیِ درستیِ حرکت با دوربین» — سیستمِ دومِ تشخیصِ تصویر.
///
/// جریانِ کار: دوربین باز می‌شود (جلو یا عقب، با دکمهٔ تعویض)، هر چند ثانیه یک
/// فریم به سرور می‌رود و نتیجه روی تصویر کشیده می‌شود:
///   · کادرِ **سبز** = درست می‌زنی
///   · کادرِ **قرمز** = اشتباه است
///   · خطِ **زرد** پایینِ تصویر = راهنمایی («آرنجت را نزدیکِ بدن بیاور»)
///
/// فاصلهٔ فریم‌ها و سقفِ تعدادشان را **سرور** می‌گوید (از جنگو ادمین تنظیم می‌شود)،
/// پس این صفحه عددِ ثابتی در خودش ندارد.
///
/// وابستگی‌ها: camera، و ChagherApi (فایلِ chagher_api.dart).
library form_check_page;

import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import 'chagher_api.dart';

class FormCheckPage extends StatefulWidget {
  const FormCheckPage({
    super.key,
    required this.api,
    required this.externalId,
    required this.exerciseName,
  });

  final ChagherApi api;
  final String externalId;
  final String exerciseName;

  @override
  State<FormCheckPage> createState() => _FormCheckPageState();
}

class _FormCheckPageState extends State<FormCheckPage> {
  CameraController? _controller;
  List<CameraDescription> _cameras = const [];
  bool _useFront = false;
  bool _running = false;
  bool _busy = false;
  Timer? _timer;

  int? _sessionId;
  int _maxFrames = 40;
  int _intervalMs = 2500;
  int _framesLeft = 0;

  String _verdict = 'unsure';
  String _message = 'دوربین را جایی بگذار که تمامِ بدنت در کادر باشد.';
  Rect? _box;
  String? _error;
  Map<String, dynamic>? _summary;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _controller?.dispose();
    // اگر کاربر صفحه را ببندد، دور بسته شود تا حسابِ هزینه ناتمام نماند
    final id = _sessionId;
    if (id != null) widget.api.formCheckFinish(id).catchError((_) => <String, dynamic>{});
    super.dispose();
  }

  Future<void> _bootstrap() async {
    try {
      final info = await widget.api.formCheckInfo(widget.externalId);
      if (info == null) {
        // قابلیت از جنگو ادمین خاموش شده است — صفحه نباید اصلاً باز بماند
        if (mounted) Navigator.of(context).pop();
        return;
      }
      _maxFrames = (info['max_frames'] as num?)?.toInt() ?? 40;
      _intervalMs = (info['frame_interval_ms'] as num?)?.toInt() ?? 2500;
      _cameras = await availableCameras();
      await _openCamera();
    } catch (e) {
      setState(() => _error = 'آماده‌سازی نشد: $e');
    }
  }

  CameraDescription? _pickCamera() {
    if (_cameras.isEmpty) return null;
    final want = _useFront ? CameraLensDirection.front : CameraLensDirection.back;
    return _cameras.firstWhere(
      (c) => c.lensDirection == want,
      orElse: () => _cameras.first,
    );
  }

  Future<void> _openCamera() async {
    final camera = _pickCamera();
    if (camera == null) {
      setState(() => _error = 'دوربینی پیدا نشد.');
      return;
    }
    await _controller?.dispose();
    final controller = CameraController(
      camera,
      ResolutionPreset.medium,
      enableAudio: false,
    );
    await controller.initialize();
    if (!mounted) return;
    setState(() {
      _controller = controller;
      _error = null;
    });
  }

  Future<void> _swapCamera() async {
    setState(() => _useFront = !_useFront);
    await _openCamera();
  }

  Future<void> _start() async {
    setState(() {
      _summary = null;
      _error = null;
    });
    try {
      final data = await widget.api.formCheckStart(
        widget.externalId,
        camera: _useFront ? 'front' : 'back',
      );
      _sessionId = (data['session_id'] as num).toInt();
      _maxFrames = (data['max_frames'] as num?)?.toInt() ?? _maxFrames;
      _intervalMs = (data['frame_interval_ms'] as num?)?.toInt() ?? _intervalMs;
      setState(() {
        _running = true;
        _framesLeft = _maxFrames;
        _message = 'شروع شد؛ حرکت را بزن.';
      });
      _timer = Timer.periodic(Duration(milliseconds: _intervalMs), (_) => _sendFrame());
    } on ChagherApiException catch (e) {
      setState(() => _error = e.message);
    }
  }

  Future<void> _sendFrame() async {
    final controller = _controller;
    final id = _sessionId;
    if (controller == null || id == null || _busy || !controller.value.isInitialized) return;
    _busy = true;
    try {
      final shot = await controller.takePicture();
      final bytes = await shot.readAsBytes();
      final data = await widget.api.formCheckFrame(id, bytes);
      if (!mounted) return;
      setState(() {
        _verdict = (data['verdict'] ?? 'unsure').toString();
        _message = (data['message'] ?? '').toString();
        _framesLeft = (data['frames_left'] as num?)?.toInt() ?? _framesLeft;
        final box = data['box'];
        _box = box is Map
            ? Rect.fromLTWH(
                (box['x'] as num).toDouble(),
                (box['y'] as num).toDouble(),
                (box['w'] as num).toDouble(),
                (box['h'] as num).toDouble(),
              )
            : null;
      });
      if (_framesLeft <= 0) await _stop();
    } on ChagherApiException catch (e) {
      if (e.statusCode == 429) {
        setState(() => _message = e.message);
        await _stop();
      } else {
        setState(() => _message = e.message);
      }
    } catch (e) {
      // خطای گرفتنِ عکس نباید دور را بشکند؛ فریمِ بعدی را می‌زنیم
      debugPrint('فریم نرفت: $e');
    } finally {
      _busy = false;
    }
  }

  Future<void> _stop() async {
    _timer?.cancel();
    _timer = null;
    final id = _sessionId;
    _sessionId = null;
    setState(() => _running = false);
    if (id == null) return;
    try {
      final data = await widget.api.formCheckFinish(id);
      if (mounted) setState(() => _summary = data);
    } catch (_) {/* خلاصه مهم نیست که بشکند */}
  }

  Color get _frameColor {
    if (_verdict == 'ok') return const Color(0xFF2BD466);
    if (_verdict == 'bad') return const Color(0xFFFF4D4D);
    return Colors.transparent;
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        backgroundColor: const Color(0xFF0D1117),
        appBar: AppBar(
          title: Text('بررسیِ درستیِ حرکت — ${widget.exerciseName}'),
          actions: [
            IconButton(
              tooltip: 'دوربینِ جلو / عقب',
              onPressed: _cameras.length > 1 ? _swapCamera : null,
              icon: const Icon(Icons.cameraswitch),
            ),
          ],
        ),
        body: Column(
          children: [
            Expanded(
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (controller != null && controller.value.isInitialized)
                    CameraPreview(controller)
                  else
                    Center(
                      child: Text(
                        _error ?? 'در حالِ آماده‌سازیِ دوربین…',
                        style: const TextStyle(color: Colors.white70),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  // کادرِ سبز/قرمز دورِ بدنِ ورزشکار
                  CustomPaint(painter: _BoxPainter(box: _box, color: _frameColor)),
                  if (_verdict != 'unsure')
                    Positioned(
                      top: 12,
                      right: 12,
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
                        decoration: BoxDecoration(
                          color: _frameColor,
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(
                          _verdict == 'ok' ? 'درست' : 'اشتباه',
                          style: const TextStyle(
                              color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13),
                        ),
                      ),
                    ),
                  // خطِ زردِ راهنمایی
                  Positioned(
                    bottom: 0,
                    left: 0,
                    right: 0,
                    child: Container(
                      color: Colors.black.withOpacity(0.62),
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                      child: Text(
                        _message,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: Color(0xFFFFD400),
                          fontWeight: FontWeight.bold,
                          fontSize: 15,
                          height: 1.7,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            Container(
              color: Colors.white,
              padding: const EdgeInsets.all(12),
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: FilledButton(
                          onPressed: _running ? _stop : _start,
                          child: Text(_running ? 'پایانِ بررسی' : 'شروعِ بررسی'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(_running ? 'باقی‌مانده: $_framesLeft' : 'سقف: $_maxFrames'),
                    ],
                  ),
                  if (_summary != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 10),
                      child: Text(
                        'بررسی‌شده: ${_summary!['frames_checked']} · درست: '
                        '${_summary!['ok_count']} · اشتباه: ${_summary!['bad_count']} · '
                        'درستی: ${_summary!['ok_percent']}٪\n${_summary!['note'] ?? ''}',
                        textAlign: TextAlign.center,
                        style: const TextStyle(fontSize: 13),
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _BoxPainter extends CustomPainter {
  _BoxPainter({required this.box, required this.color});

  /// مختصاتِ نسبی (۰ تا ۱) که سرور داده است؛ null یعنی کادرِ پیش‌فرضِ وسط.
  final Rect? box;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    if (color == Colors.transparent) return;
    final b = box ?? const Rect.fromLTWH(0.15, 0.08, 0.7, 0.84);
    final rect = Rect.fromLTWH(
      b.left * size.width,
      b.top * size.height,
      b.width * size.width,
      b.height * size.height,
    );
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = size.width * 0.012
      ..color = color;
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect, const Radius.circular(14)),
      paint,
    );
  }

  @override
  bool shouldRepaint(_BoxPainter old) => old.box != box || old.color != color;
}
