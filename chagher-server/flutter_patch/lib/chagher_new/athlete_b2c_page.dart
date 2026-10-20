/// صفحهٔ «ورزشکارِ شخصی (B2C)» — مشخصات، اسکنِ باشگاه، توکن و برنامهٔ خودش.
///
/// قدم‌ها را خودِ سرور می‌گوید (`api/me/status/`)، پس اگر قاعده‌ای در سمتِ سرور
/// عوض شود، این صفحه هم خودش عوض می‌شود و لازم نیست اپ دوباره بیلد شود.
library athlete_b2c_page;

import 'package:flutter/material.dart';

import 'chagher_api.dart';
import 'equipment_scan_page.dart';

class AthleteB2CPage extends StatefulWidget {
  const AthleteB2CPage({super.key, required this.api});

  final ChagherApi api;

  @override
  State<AthleteB2CPage> createState() => _AthleteB2CPageState();
}

class _AthleteB2CPageState extends State<AthleteB2CPage> {
  final _fields = <String, TextEditingController>{
    'full_name': TextEditingController(),
    'age': TextEditingController(),
    'height': TextEditingController(),
    'weight': TextEditingController(),
    'program_days': TextEditingController(),
    'gym_name': TextEditingController(),
    'goal': TextEditingController(),
    'injuries': TextEditingController(),
  };
  String _gender = '';
  String _programType = 'workout';

  Map<String, dynamic>? _status;
  Map<String, dynamic>? _profile;
  Map<String, dynamic>? _program;
  bool _busy = false;
  String? _error;
  String? _note;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void dispose() {
    for (final c in _fields.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _reload() async {
    setState(() => _busy = true);
    try {
      final profile = await widget.api.athleteProfile();
      final status = await widget.api.myStatus();
      final p = (profile['profile'] as Map).cast<String, dynamic>();
      for (final entry in _fields.entries) {
        final value = p[entry.key];
        if (value != null) entry.value.text = value.toString();
      }
      setState(() {
        _profile = p;
        _status = status;
        _gender = (p['gender'] ?? '').toString();
      });
    } on ChagherApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _error = null;
      _note = null;
    });
    final body = <String, dynamic>{};
    for (final entry in _fields.entries) {
      final text = entry.value.text.trim();
      if (text.isNotEmpty) body[entry.key] = text;
    }
    if (_gender.isNotEmpty) body['gender'] = _gender;
    try {
      await widget.api.saveAthleteProfile(body);
      setState(() => _note = 'مشخصات ذخیره شد.');
      await _reload();
    } on ChagherApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _generate() async {
    setState(() {
      _busy = true;
      _error = null;
      _note = 'در حالِ ساختنِ برنامه… (یک تا دو دقیقه)';
    });
    try {
      final profile = await widget.api.athleteProfile();
      final defaults = (profile['program_defaults'] as Map).cast<String, dynamic>();
      final data = await widget.api.generateProgram({
        ...defaults,
        'program_type': _programType,
      });
      setState(() {
        _program = (data['program'] as Map?)?.cast<String, dynamic>() ?? data;
        _note = 'برنامه ساخته شد.';
      });
      await _reload();
    } on ChagherApiException catch (e) {
      setState(() {
        _error = e.message;
        _note = null;
      });
    } finally {
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final status = _status;
    final canGenerate = status?['can_generate_program'] == true;
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        appBar: AppBar(title: const Text('حسابِ من')),
        body: ListView(
          padding: const EdgeInsets.all(14),
          children: [
            if (status != null) ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('توکن: ${status['token_balance']} · '
                          'دستگاه: ${status['equipment_count']} · '
                          'برنامه: ${status['program_count']}'),
                      const SizedBox(height: 8),
                      ...((status['steps'] as List? ?? []).cast<Map<String, dynamic>>()).map(
                        (s) => Row(
                          children: [
                            Icon(s['done'] == true ? Icons.check_circle : Icons.circle_outlined,
                                size: 18,
                                color: s['done'] == true ? Colors.green : Colors.grey),
                            const SizedBox(width: 6),
                            Expanded(child: Text(s['title']?.toString() ?? '')),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 10),
            ],
            FilledButton.icon(
              icon: const Icon(Icons.photo_camera),
              label: const Text('اسکنِ باشگاهم با دوربین'),
              onPressed: () async {
                await Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => EquipmentScanPage(
                    api: widget.api,
                    gymName: _fields['gym_name']!.text.trim(),
                  ),
                ));
                await _reload();
              },
            ),
            const SizedBox(height: 16),
            const Text('مشخصاتِ من', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            const Text('یک‌بار پر کن؛ هر بار برنامه‌گرفتن از همین برداشته می‌شود.',
                style: TextStyle(fontSize: 12, color: Colors.black54)),
            _text('full_name', 'نام و نام خانوادگی'),
            Row(children: [
              Expanded(child: _text('age', 'سن', number: true)),
              const SizedBox(width: 8),
              Expanded(
                child: DropdownButtonFormField<String>(
                  value: _gender.isEmpty ? null : _gender,
                  decoration: const InputDecoration(labelText: 'جنسیت'),
                  items: const [
                    DropdownMenuItem(value: 'M', child: Text('مرد')),
                    DropdownMenuItem(value: 'F', child: Text('زن')),
                  ],
                  onChanged: (v) => setState(() => _gender = v ?? ''),
                ),
              ),
            ]),
            Row(children: [
              Expanded(child: _text('height', 'قد (سانتی‌متر)', number: true)),
              const SizedBox(width: 8),
              Expanded(child: _text('weight', 'وزن (کیلوگرم)', number: true)),
            ]),
            Row(children: [
              Expanded(child: _text('program_days', 'روزهای تمرین در هفته', number: true)),
              const SizedBox(width: 8),
              Expanded(child: _text('gym_name', 'نامِ باشگاه')),
            ]),
            _text('goal', 'هدف'),
            _text('injuries', 'آسیب‌ها'),
            const SizedBox(height: 10),
            FilledButton(onPressed: _busy ? null : _save, child: const Text('ذخیرهٔ مشخصات')),
            const Divider(height: 30),
            const Text('برنامهٔ من', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
            DropdownButtonFormField<String>(
              value: _programType,
              decoration: const InputDecoration(labelText: 'نوعِ برنامه'),
              items: const [
                DropdownMenuItem(value: 'workout', child: Text('فقط ورزشی')),
                DropdownMenuItem(value: 'both', child: Text('ورزشی + غذایی')),
                DropdownMenuItem(value: 'meal', child: Text('فقط غذایی')),
              ],
              onChanged: (v) => setState(() => _programType = v ?? 'workout'),
            ),
            const SizedBox(height: 8),
            FilledButton(
              onPressed: (_busy || !canGenerate) ? null : _generate,
              child: const Text('ساختِ برنامه'),
            ),
            if (!canGenerate)
              const Padding(
                padding: EdgeInsets.only(top: 6),
                child: Text('برای ساختِ برنامه، مشخصاتِ کامل و توکن لازم است.',
                    style: TextStyle(fontSize: 12, color: Colors.black54)),
              ),
            if (_busy) const Padding(
              padding: EdgeInsets.symmetric(vertical: 14),
              child: Center(child: CircularProgressIndicator()),
            ),
            if (_note != null)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(_note!, style: const TextStyle(fontWeight: FontWeight.bold)),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(_error!, style: const TextStyle(color: Colors.red)),
              ),
            if (_program != null)
              Card(
                margin: const EdgeInsets.only(top: 12),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text(
                    (_program!['generated_workout'] ?? _program!['generated_meal_plan'] ?? '')
                        .toString(),
                    style: const TextStyle(fontSize: 13, height: 1.9),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _text(String key, String label, {bool number = false}) => Padding(
        padding: const EdgeInsets.only(top: 8),
        child: TextField(
          controller: _fields[key],
          keyboardType: number ? TextInputType.number : TextInputType.text,
          decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
        ),
      );
}
