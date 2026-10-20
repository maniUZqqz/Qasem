// ignore_for_file: avoid_print
/// کلاینتِ APIهای تازهٔ چغر — اسکنِ دستگاه، برنامهٔ دستی، ورزشکارِ شخصی و
/// بررسیِ درستیِ حرکت.
///
/// همهٔ این مسیرها همان‌هایی هستند که پنلِ وبِ جنگو هم صدا می‌زند، پس رفتارِ اپ و
/// وب یکی می‌ماند و منطق در یک جا (سمتِ سرور) است.
///
/// نکتهٔ مهم برای «قابلیتِ پنهان»: اگر مدیر «بررسیِ درستیِ حرکت» را در جنگو ادمین
/// خاموش کند، مسیرهایش ۴۰۴ می‌دهند. تابعِ [formCheckInfo] در این حالت null
/// برمی‌گرداند و اپ **باید دکمه را کامل پنهان کند**، نه این‌که پیامِ خطا بدهد.
library chagher_api;

import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

class ChagherApiException implements Exception {
  ChagherApiException(this.statusCode, this.message, [this.data]);

  final int statusCode;
  final String message;
  final Map<String, dynamic>? data;

  @override
  String toString() => 'ChagherApiException($statusCode): $message';
}

class ChagherApi {
  ChagherApi({required this.baseUrl, required this.token});

  /// مثال: `http://185.239.3.189:8000/chagher/api/` — اسلشِ آخر لازم است.
  final String baseUrl;

  /// توکنِ DRF همان کاربر (همان که برای بقیهٔ APIها استفاده می‌کنید).
  final String token;

  Map<String, String> get _headers => {'Authorization': 'Token $token'};

  Uri _uri(String path, [Map<String, String>? query]) {
    final uri = Uri.parse('$baseUrl$path');
    if (query == null || query.isEmpty) return uri;
    return uri.replace(queryParameters: {...uri.queryParameters, ...query});
  }

  Map<String, dynamic> _decode(http.Response res) {
    final body = res.body.isEmpty ? '{}' : utf8.decode(res.bodyBytes);
    Map<String, dynamic> data;
    try {
      final parsed = jsonDecode(body);
      data = parsed is Map<String, dynamic> ? parsed : {'results': parsed};
    } catch (_) {
      data = {'raw': body};
    }
    if (res.statusCode >= 400) {
      throw ChagherApiException(
        res.statusCode,
        (data['error'] ?? data['detail'] ?? 'خطای سرور (${res.statusCode})').toString(),
        data,
      );
    }
    return data;
  }

  Future<Map<String, dynamic>> _get(String path, [Map<String, String>? query]) async =>
      _decode(await http.get(_uri(path, query), headers: _headers));

  Future<Map<String, dynamic>> _post(String path, [Map<String, dynamic>? body]) async {
    final res = await http.post(
      _uri(path),
      headers: {..._headers, 'Content-Type': 'application/json'},
      body: jsonEncode(body ?? <String, dynamic>{}),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> _upload(
    String path, {
    required List<MultipartEntry> files,
    Map<String, String> fields = const {},
  }) async {
    final request = http.MultipartRequest('POST', _uri(path))
      ..headers.addAll(_headers)
      ..fields.addAll(fields);
    for (final entry in files) {
      request.files.add(http.MultipartFile.fromBytes(
        entry.field,
        entry.bytes,
        filename: entry.filename,
      ));
    }
    return _decode(await http.Response.fromStream(await request.send()));
  }

  // ───────────────────────── ۱) اسکنِ دستگاه با دوربین ─────────────────────────

  /// نام‌هایی که سامانه می‌شناسد + سقفِ عکس + هزینهٔ توکن.
  Future<Map<String, dynamic>> scanCandidates() => _get('equipment-scan/candidates/');

  /// عکس‌ها را می‌فرستد و فهرستِ تشخیص را برمی‌گرداند. **هیچ دستگاهی ثبت نمی‌شود**
  /// تا [scanConfirm] صدا زده شود.
  Future<Map<String, dynamic>> scanPhotos(List<File> photos, {String? gymName}) async {
    final entries = <MultipartEntry>[];
    for (var i = 0; i < photos.length; i++) {
      entries.add(MultipartEntry(
        field: 'photos',
        bytes: await photos[i].readAsBytes(),
        filename: 'photo_$i.jpg',
      ));
    }
    return _upload(
      'equipment-scan/',
      files: entries,
      fields: {if (gymName != null && gymName.isNotEmpty) 'gym_name': gymName},
    );
  }

  // ── اسکنِ زنده (ویدیو) ──
  /// یک دورِ اسکن باز می‌کند؛ هزینهٔ توکن **یک بار** همین‌جا کم می‌شود.
  Future<Map<String, dynamic>> scanStart({String? gymName}) =>
      _post('equipment-scan/start/',
          {if (gymName != null && gymName.isNotEmpty) 'gym_name': gymName});

  /// یک فریمِ دوربین → فقط تشخیص‌های **تازه** برمی‌گردد.
  Future<Map<String, dynamic>> scanFrame(int scanId, List<int> jpegBytes) => _upload(
        'equipment-scan/$scanId/frame/',
        files: [MultipartEntry(field: 'frame', bytes: jpegBytes, filename: 'frame.jpg')],
      );

  Future<Map<String, dynamic>> scanDetail(int scanId) => _get('equipment-scan/$scanId/');

  Future<Map<String, dynamic>> scanList() => _get('equipment-scan/');

  /// تأییدِ کاربر: فقط شناسه‌هایی که [accept] می‌دهید ساخته می‌شوند. برای «تأییدِ
  /// همه» مقدار [acceptAll] را true بگذارید.
  Future<Map<String, dynamic>> scanConfirm(
    int scanId, {
    List<int> accept = const [],
    bool acceptAll = false,
  }) =>
      _post('equipment-scan/$scanId/confirm/',
          acceptAll ? {'accept_all': true} : {'accept': accept});

  // ───────────────────────── ۲) برنامهٔ دستیِ مربی ─────────────────────────

  /// سهمِ رایگانِ این ورزشکار و هزینهٔ برنامهٔ بعدی.
  Future<Map<String, dynamic>> manualQuota({String? name, int? gymClient}) => _get(
        'programs/manual/quota/',
        {
          if (name != null) 'name': name,
          if (gymClient != null) 'gym_client': '$gymClient',
        },
      );

  /// payload: `{name, days: [{title, exercises: [{exercise_id, sets, reps, rest}]}], notes}`
  Future<Map<String, dynamic>> manualCreate(Map<String, dynamic> payload) =>
      _post('programs/manual/', payload);

  Future<Map<String, dynamic>> manualDetail(int programId) =>
      _get('programs/manual/$programId/');

  /// جست‌وجوی کتابخانهٔ حرکت‌ها برای انتخابِ حرکت.
  Future<List<Map<String, dynamic>>> exerciseSearch(String query, {int pageSize = 25}) async {
    final data = await _get('exercise-library/', {
      'search': query,
      'page_size': '$pageSize',
    });
    return (data['results'] as List? ?? []).cast<Map<String, dynamic>>();
  }

  // ── حرکت‌های خودِ مربی (مورد ۵) ──
  /// حرکتی که در کتابخانهٔ سراسری نیست، در کتابخانهٔ خودِ مربی ثبت می‌شود.
  Future<Map<String, dynamic>> addMyExercise({
    required String nameFa,
    String? equipmentFa,
    String? targetFa,
    List<String>? steps,
  }) =>
      _post('exercise-library/mine/', {
        'name_fa': nameFa,
        if (equipmentFa != null) 'equipment_fa': equipmentFa,
        if (targetFa != null) 'target_fa': targetFa,
        if (steps != null) 'steps_fa': steps,
      });

  Future<Map<String, dynamic>> myExercises() => _get('exercise-library/mine/');

  // ───────────────────────── ۳) ورزشکارِ شخصی (B2C) ─────────────────────────

  Future<Map<String, dynamic>> myStatus() => _get('me/status/');

  Future<Map<String, dynamic>> athleteProfile() => _get('me/athlete-profile/');

  Future<Map<String, dynamic>> saveAthleteProfile(Map<String, dynamic> data) async {
    final res = await http.patch(
      _uri('me/athlete-profile/'),
      headers: {..._headers, 'Content-Type': 'application/json'},
      body: jsonEncode(data),
    );
    return _decode(res);
  }

  Future<Map<String, dynamic>> tokenPackages() => _get('token-packages/');

  Future<Map<String, dynamic>> generateProgram(Map<String, dynamic> data) =>
      _post('programs/generate/', data);

  Future<Map<String, dynamic>> myEquipment() => _get('equipments/');

  // ───────────────────── ۴) بررسیِ درستیِ حرکت با دوربین ─────────────────────

  /// null یعنی قابلیت از جنگو ادمین **خاموش** است ⇒ دکمه را نشان ندهید.
  Future<Map<String, dynamic>?> formCheckInfo(String externalId) async {
    try {
      return await _get('form-check/$externalId/');
    } on ChagherApiException catch (e) {
      if (e.statusCode == 404) return null;
      rethrow;
    }
  }

  /// camera: `back` یا `front`.
  Future<Map<String, dynamic>> formCheckStart(String externalId, {String camera = 'back'}) =>
      _post('form-check/$externalId/start/', {'camera': camera});

  /// یک فریمِ JPEG → حکم (`ok`/`bad`/`unsure`)، رنگ، پیامِ فارسی و جعبهٔ بدن.
  Future<Map<String, dynamic>> formCheckFrame(int sessionId, List<int> jpegBytes) => _upload(
        'form-check/session/$sessionId/frame/',
        files: [MultipartEntry(field: 'frame', bytes: jpegBytes, filename: 'frame.jpg')],
      );

  Future<Map<String, dynamic>> formCheckFinish(int sessionId) =>
      _post('form-check/session/$sessionId/finish/');
}

class MultipartEntry {
  MultipartEntry({required this.field, required this.bytes, required this.filename});

  final String field;
  final List<int> bytes;
  final String filename;
}
