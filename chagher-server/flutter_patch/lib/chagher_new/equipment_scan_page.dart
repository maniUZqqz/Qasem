/// صفحهٔ «اسکنِ دستگاه‌های باشگاه با دوربین» — سیستمِ اولِ تشخیصِ تصویر.
///
/// کاربر (مربی یا ورزشکارِ شخصی) در باشگاه می‌چرخد، چند عکس می‌گیرد و می‌فرستد.
/// سامانه دستگاه‌ها را تشخیص می‌دهد و **تا تأییدِ کاربر هیچ چیزی ثبت نمی‌شود**؛
/// کنارِ هر تشخیص، عکسِ مرجعِ همان دستگاه از کاتالوگ نشان داده می‌شود تا کاربر
/// ببیند سامانه چه فهمیده است.
///
/// وابستگی‌ها: image_picker، و ChagherApi (فایلِ chagher_api.dart).
library equipment_scan_page;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import 'chagher_api.dart';

class EquipmentScanPage extends StatefulWidget {
  const EquipmentScanPage({super.key, required this.api, this.gymName});

  final ChagherApi api;

  /// نامِ باشگاه — برای ورزشکارِ شخصی که باشگاهِ محلِ تمرینش را اسکن می‌کند.
  final String? gymName;

  @override
  State<EquipmentScanPage> createState() => _EquipmentScanPageState();
}

class _EquipmentScanPageState extends State<EquipmentScanPage> {
  final _picker = ImagePicker();
  final List<File> _photos = [];
  final Set<int> _accepted = {};

  int _maxPhotos = 12;
  int _tokenCost = 0;
  bool _busy = false;
  String? _error;
  String? _message;
  Map<String, dynamic>? _scan;
  List<Map<String, dynamic>> _items = const [];
  List<Map<String, dynamic>> _added = const [];

  @override
  void initState() {
    super.initState();
    _loadLimits();
  }

  Future<void> _loadLimits() async {
    try {
      final data = await widget.api.scanCandidates();
      setState(() {
        _maxPhotos = (data['max_photos'] as num?)?.toInt() ?? 12;
        _tokenCost = (data['token_cost'] as num?)?.toInt() ?? 0;
      });
    } catch (_) {/* سقف پیش‌فرض کافی است */}
  }

  Future<void> _takePhoto() async {
    if (_photos.length >= _maxPhotos) {
      setState(() => _error = 'در هر اسکن حداکثر $_maxPhotos عکس می‌شود فرستاد.');
      return;
    }
    final shot = await _picker.pickImage(
      source: ImageSource.camera,
      preferredCameraDevice: CameraDevice.rear,
      imageQuality: 85,
      maxWidth: 1600,
    );
    if (shot == null) return;
    setState(() {
      _photos.add(File(shot.path));
      _error = null;
    });
  }

  Future<void> _pickFromGallery() async {
    final shots = await _picker.pickMultiImage(imageQuality: 85, maxWidth: 1600);
    if (shots.isEmpty) return;
    setState(() {
      for (final s in shots.take(_maxPhotos - _photos.length)) {
        _photos.add(File(s.path));
      }
    });
  }

  Future<void> _send() async {
    if (_photos.isEmpty) {
      setState(() => _error = 'اول چند عکس بگیر.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _message = 'در حالِ تشخیص… (هر عکس چند ثانیه)';
    });
    try {
      final data = await widget.api.scanPhotos(_photos, gymName: widget.gymName);
      final scan = (data['scan'] as Map).cast<String, dynamic>();
      final items = (scan['items'] as List? ?? []).cast<Map<String, dynamic>>();
      setState(() {
        _scan = scan;
        _items = items;
        _message = data['message']?.toString();
        _accepted
          ..clear()
          // پیش‌فرض: چیزهایی که مطمئن‌اند و از قبل در باشگاه نبودند تیک می‌خورند
          ..addAll(items
              .where((i) => i['already_exists'] != true && (i['confidence'] as num) >= 0.5)
              .map((i) => (i['id'] as num).toInt()));
      });
    } on ChagherApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _confirm() async {
    final scan = _scan;
    if (scan == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final data = await widget.api.scanConfirm(
        (scan['id'] as num).toInt(),
        accept: _accepted.toList(),
      );
      setState(() {
        _added = (data['added'] as List? ?? []).cast<Map<String, dynamic>>();
        _message = data['message']?.toString();
        _items = const [];
        _scan = null;
        _photos.clear();
      });
    } on ChagherApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        appBar: AppBar(title: const Text('اسکنِ دستگاه‌های باشگاه')),
        body: ListView(
          padding: const EdgeInsets.all(14),
          children: [
            const Text(
              'در باشگاه بچرخ و از هر دستگاه یک عکسِ نزدیک بگیر. تا تأیید نکنی، '
              'هیچ دستگاهی به فهرستِ باشگاه اضافه نمی‌شود.',
              style: TextStyle(fontSize: 13, height: 1.8),
            ),
            if (_tokenCost > 0)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('هزینهٔ این اسکن: $_tokenCost توکن',
                    style: const TextStyle(fontSize: 13, color: Colors.orange)),
              ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton.icon(
                  onPressed: _busy ? null : _takePhoto,
                  icon: const Icon(Icons.photo_camera),
                  label: const Text('گرفتنِ عکس'),
                ),
                OutlinedButton.icon(
                  onPressed: _busy ? null : _pickFromGallery,
                  icon: const Icon(Icons.photo_library),
                  label: const Text('از گالری'),
                ),
                if (_photos.isNotEmpty)
                  OutlinedButton(
                    onPressed: _busy ? null : () => setState(_photos.clear),
                    child: const Text('پاک‌کردنِ عکس‌ها'),
                  ),
              ],
            ),
            if (_photos.isNotEmpty) ...[
              const SizedBox(height: 10),
              SizedBox(
                height: 92,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: _photos.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (_, i) => ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Image.file(_photos[i], width: 92, height: 92, fit: BoxFit.cover),
                  ),
                ),
              ),
              const SizedBox(height: 10),
              FilledButton(
                onPressed: _busy ? null : _send,
                child: Text('فرستادنِ ${_photos.length} عکس و تشخیص'),
              ),
            ],
            if (_busy) const Padding(
              padding: EdgeInsets.symmetric(vertical: 14),
              child: Center(child: CircularProgressIndicator()),
            ),
            if (_message != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(_message!, style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(_error!, style: const TextStyle(color: Colors.red)),
              ),
            if (_items.isNotEmpty) ...[
              const SizedBox(height: 14),
              const Text('تأییدِ دستگاه‌ها',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              ..._items.map(_itemTile),
              const SizedBox(height: 10),
              FilledButton(
                onPressed: _busy ? null : _confirm,
                child: Text('تأیید و افزودنِ ${_accepted.length} دستگاه'),
              ),
            ],
            if (_added.isNotEmpty) ...[
              const SizedBox(height: 14),
              const Text('اضافه شد:', style: TextStyle(fontWeight: FontWeight.bold)),
              Wrap(
                spacing: 6,
                children: _added
                    .map((a) => Chip(label: Text(a['name']?.toString() ?? '-')))
                    .toList(),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _itemTile(Map<String, dynamic> item) {
    final id = (item['id'] as num).toInt();
    final confidence = ((item['confidence'] as num) * 100).round();
    final image = item['catalog_image']?.toString();
    final exists = item['already_exists'] == true;
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
                    width: 52, height: 52, fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => const Icon(Icons.fitness_center)),
              ),
        title: Text(item['name']?.toString() ?? '-'),
        subtitle: Text([
          'اطمینان $confidence٪',
          if (item['muscle_group'] != null) item['muscle_group'].toString(),
          if (exists) 'از قبل در باشگاه بود',
          if (item['in_library'] != true) 'نامِ تازه',
        ].join(' · '), style: const TextStyle(fontSize: 12)),
      ),
    );
  }
}
