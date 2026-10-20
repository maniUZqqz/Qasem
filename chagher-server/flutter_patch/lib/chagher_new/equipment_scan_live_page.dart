/// اسکنِ **زندهٔ** دستگاه‌های باشگاه (مورد ۶) — نسخهٔ فلاتر.
///
/// دوربین روشن می‌ماند، کاربر در باشگاه می‌چرخد و هر چند ثانیه یک فریم به سرور
/// می‌رود؛ هر دستگاهی که پیدا شود همان لحظه به فهرست اضافه می‌شود و در پایان
/// تأیید گرفته می‌شود. دوربینِ جلو و عقب هر دو، با دکمهٔ تعویض.
///
/// فاصلهٔ فریم‌ها و سقفشان را **سرور** می‌گوید (تنظیمِ جنگو ادمین)، پس عددِ
/// ثابتی در اپ نیست.
///
/// وابستگی‌ها: camera، و ChagherApi (فایلِ chagher_api.dart).
library equipment_scan_live_page;

import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import 'chagher_api.dart';

class EquipmentScanLivePage extends StatefulWidget {
  const EquipmentScanLivePage({super.key, required this.api, this.gymName});

  final ChagherApi api;
  final String? gymName;

  @override
  State<EquipmentScanLivePage> createState() => _EquipmentScanLivePageState();
}

class _EquipmentScanLivePageState extends State<EquipmentScanLivePage> {
  CameraController? _controller;
  List<CameraDescription> _cameras = const [];
  bool _useFront = false;
  bool _running = false;
  bool _busy = false;
  Timer? _timer;

  int? _scanId;
  int _framesLeft = 0;
  int _intervalMs = 2500;
  String _toast = '';
  String? _error;

  /// شناسه → دادهٔ تشخیص. با Map، تکراری خودش حذف می‌شود.
  final Map<int, Map<String, dynamic>> _items = {};
  final Set<int> _accepted = {};
  List<Map<String, dynamic>> _added = const [];

  @override
  void initState() {
    super.initState();
    _initCameras();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _initCameras() async {
    try {
      _cameras = await availableCameras();
      await _openCamera();
    } catch (e) {
      setState(() => _error = 'دوربین آماده نشد: $e');
    }
  }

  CameraDescription? _pick() {
    if (_cameras.isEmpty) return null;
    final want = _useFront ? CameraLensDirection.front : CameraLensDirection.back;
    return _cameras.firstWhere((c) => c.lensDirection == want,
        orElse: () => _cameras.first);
  }

  Future<void> _openCamera() async {
    final camera = _pick();
    if (camera == null) {
      setState(() => _error = 'دوربینی پیدا نشد.');
      return;
    }
    await _controller?.dispose();
    final controller = CameraController(camera, ResolutionPreset.high, enableAudio: false);
    await controller.initialize();
    if (!mounted) return;
    setState(() {
      _controller = controller;
      _error = null;
    });
  }

  Future<void> _swap() async {
    setState(() => _useFront = !_useFront);
    await _openCamera();
  }

  void _say(String text) {
    setState(() => _toast = text);
    Timer(const Duration(seconds: 4), () {
      if (mounted && _toast == text) setState(() => _toast = '');
    });
  }

  Future<void> _start() async {
    setState(() {
      _error = null;
      _added = const [];
    });
    try {
      final data = await widget.api.scanStart(gymName: widget.gymName);
      _scanId = (data['scan_id'] as num).toInt();
      _framesLeft = (data['max_frames'] as num?)?.toInt() ?? 12;
      _intervalMs = (data['frame_interval_ms'] as num?)?.toInt() ?? 2500;
      setState(() => _running = true);
      _say(data['charged_tokens'] == 0
          ? 'اسکن شروع شد (رایگان). آرام در باشگاه بچرخ.'
          : 'اسکن شروع شد · ${data['charged_tokens']} توکن کم شد');
      _timer = Timer.periodic(Duration(milliseconds: _intervalMs), (_) => _sendFrame());
    } on ChagherApiException catch (e) {
      setState(() => _error = e.message);
    }
  }

  Future<void> _sendFrame() async {
    final controller = _controller;
    final id = _scanId;
    if (controller == null || id == null || _busy || !controller.value.isInitialized) return;
    _busy = true;
    try {
      final shot = await controller.takePicture();
      final bytes = await shot.readAsBytes();
      final data = await widget.api.scanFrame(id, bytes);
      if (!mounted) return;
      final fresh = (data['new_items'] as List? ?? []).cast<Map<String, dynamic>>();
      final all = (data['items'] as List? ?? []).cast<Map<String, dynamic>>();
      setState(() {
        for (final item in all) {
          final key = (item['id'] as num).toInt();
          _items[key] = item;
          if (item['already_exists'] != true &&
              (item['confidence'] as num) >= 0.5 &&
              !_accepted.contains(key)) {
            _accepted.add(key);
          }
        }
        _framesLeft = (data['frames_left'] as num?)?.toInt() ?? _framesLeft;
      });
      if (fresh.isNotEmpty) {
        _say('پیدا شد: ${fresh.map((i) => i['name']).join('، ')}');
      }
      if (_framesLeft <= 0) await _stop();
    } on ChagherApiException catch (e) {
      if (e.statusCode == 429) {
        _say(e.message);
        await _stop();
      } else {
        _say(e.message);
      }
    } catch (e) {
      debugPrint('فریم نرفت: $e');
    } finally {
      _busy = false;
    }
  }

  Future<void> _stop() async {
    _timer?.cancel();
    _timer = null;
    setState(() => _running = false);
    if (_items.isNotEmpty) _say('اسکن تمام شد — پایین تأیید کن.');
  }

  Future<void> _confirm() async {
    final id = _scanId;
    if (id == null) return;
    try {
      final data = await widget.api.scanConfirm(id, accept: _accepted.toList());
      setState(() {
        _added = (data['added'] as List? ?? []).cast<Map<String, dynamic>>();
        _items.clear();
        _accepted.clear();
        _scanId = null;
      });
      _say(data['message']?.toString() ?? 'ثبت شد.');
    } on ChagherApiException catch (e) {
      setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('اسکنِ زندهٔ دستگاه‌ها'),
          actions: [
            IconButton(
              tooltip: 'دوربینِ جلو / عقب',
              onPressed: _cameras.length > 1 ? _swap : null,
              icon: const Icon(Icons.cameraswitch),
            ),
          ],
        ),
        body: Column(
          children: [
            AspectRatio(
              aspectRatio: 3 / 4,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (controller != null && controller.value.isInitialized)
                    CameraPreview(controller)
                  else
                    ColoredBox(
                      color: const Color(0xFF0D1117),
                      child: Center(
                        child: Text(_error ?? 'در حالِ آماده‌سازیِ دوربین…',
                            style: const TextStyle(color: Colors.white70)),
                      ),
                    ),
                  if (_running)
                    Positioned(
                      top: 10,
                      right: 10,
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                        decoration: BoxDecoration(
                          color: const Color(0xFFD32F2F),
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: const Text('● زنده',
                            style: TextStyle(color: Colors.white, fontSize: 12)),
                      ),
                    ),
                  if (_toast.isNotEmpty)
                    Positioned(
                      bottom: 0,
                      left: 0,
                      right: 0,
                      child: Container(
                        color: Colors.black.withOpacity(0.6),
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                        child: Text(_toast,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                                color: Color(0xFFFFD400),
                                fontWeight: FontWeight.bold,
                                fontSize: 14)),
                      ),
                    ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  Expanded(
                    child: FilledButton(
                      onPressed: _running ? _stop : _start,
                      child: Text(_running ? 'پایانِ اسکن' : 'شروعِ اسکن'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(_running ? 'باقی: $_framesLeft فریم' : 'پیدا شده: ${_items.length}'),
                ],
              ),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                children: [
                  if (_items.isNotEmpty)
                    const Padding(
                      padding: EdgeInsets.only(bottom: 6),
                      child: Text('تأییدِ دستگاه‌ها — تا تأیید نکنی ثبت نمی‌شود',
                          style: TextStyle(fontWeight: FontWeight.bold)),
                    ),
                  ..._items.values.map(_tile),
                  if (_items.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      child: FilledButton(
                        onPressed: _confirm,
                        child: Text('تأیید و افزودنِ ${_accepted.length} دستگاه'),
                      ),
                    ),
                  if (_added.isNotEmpty) ...[
                    const Text('اضافه شد:', style: TextStyle(fontWeight: FontWeight.bold)),
                    Wrap(
                      spacing: 6,
                      children: _added
                          .map((a) => Chip(label: Text(a['name']?.toString() ?? '-')))
                          .toList(),
                    ),
                  ],
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: Text(_error!, style: const TextStyle(color: Colors.red)),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _tile(Map<String, dynamic> item) {
    final id = (item['id'] as num).toInt();
    final image = item['catalog_image']?.toString();
    final confidence = ((item['confidence'] as num) * 100).round();
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: CheckboxListTile(
        value: _accepted.contains(id),
        onChanged: (on) => setState(() {
          if (on == true) {
            _accepted.add(id);
          } else {
            _accepted.remove(id);
          }
        }),
        secondary: image == null
            ? const Icon(Icons.fitness_center)
            : ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Image.network(image,
                    width: 48,
                    height: 48,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => const Icon(Icons.fitness_center)),
              ),
        title: Text(item['name']?.toString() ?? '-'),
        subtitle: Text([
          'اطمینان $confidence٪',
          if (item['muscle_group'] != null) item['muscle_group'].toString(),
          if (item['already_exists'] == true) 'از قبل بود',
          if (item['in_library'] != true) 'نامِ تازه',
        ].join(' · '), style: const TextStyle(fontSize: 12)),
      ),
    );
  }
}
