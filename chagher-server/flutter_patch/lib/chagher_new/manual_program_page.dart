/// صفحهٔ «برنامهٔ دستیِ مربی» — بدونِ هوش مصنوعی.
///
/// مربی جلسه‌ها را می‌سازد، حرکت‌ها را از کتابخانهٔ ۱۳۲۴تایی انتخاب می‌کند و
/// ست/تکرار می‌گذارد. سهمِ رایگانِ هر ورزشکار و هزینهٔ توکن را سرور می‌گوید
/// (تنظیمش در جنگو ادمین است)، پس این صفحه هیچ عددی از خودش ندارد.
library manual_program_page;

import 'package:flutter/material.dart';

import 'chagher_api.dart';

class ManualProgramPage extends StatefulWidget {
  const ManualProgramPage({super.key, required this.api});

  final ChagherApi api;

  @override
  State<ManualProgramPage> createState() => _ManualProgramPageState();
}

class _ManualDay {
  _ManualDay();

  final TextEditingController title = TextEditingController();
  final List<_ManualExercise> exercises = [];
}

class _ManualExercise {
  _ManualExercise({required this.externalId, required this.name});

  final String? externalId;
  final String name;
  final TextEditingController sets = TextEditingController(text: '3');
  final TextEditingController reps = TextEditingController(text: '12');
  final TextEditingController rest = TextEditingController();
}

class _ManualProgramPageState extends State<ManualProgramPage> {
  final _name = TextEditingController();
  final _notes = TextEditingController();
  final List<_ManualDay> _days = [_ManualDay()];

  Map<String, dynamic>? _quota;
  Map<String, dynamic>? _result;
  bool _busy = false;
  String? _error;

  Future<void> _refreshQuota() async {
    final name = _name.text.trim();
    if (name.isEmpty) return;
    try {
      final data = await widget.api.manualQuota(name: name);
      setState(() => _quota = data);
    } catch (_) {/* سهمیه نمایشی است؛ شکستش کار را نمی‌خواباند */}
  }

  Future<void> _addExercise(_ManualDay day) async {
    final picked = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _ExercisePicker(api: widget.api),
    );
    if (picked == null) return;
    setState(() => day.exercises.add(_ManualExercise(
          externalId: picked['external_id']?.toString(),
          name: (picked['name_fa'] ?? picked['name']).toString(),
        )));
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _error = 'نامِ ورزشکار را بنویس.');
      return;
    }
    if (_days.any((d) => d.exercises.isEmpty)) {
      setState(() => _error = 'هر جلسه باید حداقل یک حرکت داشته باشد.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final data = await widget.api.manualCreate({
        'name': _name.text.trim(),
        'notes': _notes.text.trim(),
        'days': _days
            .map((d) => {
                  'title': d.title.text.trim(),
                  'exercises': d.exercises
                      .map((e) => {
                            'exercise_id': e.externalId,
                            'name': e.name,
                            'sets': e.sets.text.trim(),
                            'reps': e.reps.text.trim(),
                            'rest': e.rest.text.trim(),
                          })
                      .toList(),
                })
            .toList(),
      });
      setState(() {
        _result = data;
        _quota = (data['quota'] as Map?)?.cast<String, dynamic>();
      });
    } on ChagherApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final quota = _quota;
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        appBar: AppBar(title: const Text('برنامهٔ دستی (بدونِ هوش مصنوعی)')),
        body: ListView(
          padding: const EdgeInsets.all(14),
          children: [
            TextField(
              controller: _name,
              onEditingComplete: _refreshQuota,
              decoration: const InputDecoration(
                  labelText: 'نامِ ورزشکار', border: OutlineInputBorder()),
            ),
            if (quota != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  quota['next_is_free'] == true
                      ? 'این برنامه رایگان است — از ${quota['free_quota']} '
                          'برنامهٔ رایگان، ${quota['free_remaining']} تا مانده.'
                      : 'سهمِ رایگان تمام شده — این برنامه ${quota['next_cost']} توکن کم می‌کند.',
                  style: TextStyle(
                    fontSize: 13,
                    color: quota['next_is_free'] == true ? Colors.green : Colors.orange,
                  ),
                ),
              ),
            const SizedBox(height: 14),
            ..._days.asMap().entries.map((entry) => _dayCard(entry.key, entry.value)),
            OutlinedButton.icon(
              onPressed: () => setState(() => _days.add(_ManualDay())),
              icon: const Icon(Icons.add),
              label: const Text('جلسهٔ تازه'),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _notes,
              maxLines: 2,
              decoration: const InputDecoration(
                  labelText: 'نکتهٔ کلی (اختیاری)', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 14),
            FilledButton(
              onPressed: _busy ? null : _save,
              child: const Text('ساختِ برنامه'),
            ),
            if (_busy) const Padding(
              padding: EdgeInsets.symmetric(vertical: 14),
              child: Center(child: CircularProgressIndicator()),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Text(_error!, style: const TextStyle(color: Colors.red)),
              ),
            if (_result != null) _resultCard(_result!),
          ],
        ),
      ),
    );
  }

  Widget _dayCard(int index, _ManualDay day) => Card(
        margin: const EdgeInsets.only(bottom: 10),
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text('جلسهٔ ${index + 1}',
                      style: const TextStyle(fontWeight: FontWeight.bold)),
                  const Spacer(),
                  if (_days.length > 1)
                    IconButton(
                      icon: const Icon(Icons.delete_outline),
                      onPressed: () => setState(() => _days.removeAt(index)),
                    ),
                ],
              ),
              TextField(
                controller: day.title,
                decoration: const InputDecoration(labelText: 'عنوانِ جلسه (مثلاً سینه و پشت بازو)'),
              ),
              const SizedBox(height: 6),
              ...day.exercises.asMap().entries.map((e) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      children: [
                        Expanded(flex: 4, child: Text('${e.key + 1}. ${e.value.name}')),
                        Expanded(child: _tiny(e.value.sets, 'ست')),
                        const SizedBox(width: 4),
                        Expanded(child: _tiny(e.value.reps, 'تکرار')),
                        const SizedBox(width: 4),
                        Expanded(child: _tiny(e.value.rest, 'استراحت')),
                        IconButton(
                          icon: const Icon(Icons.close, size: 18),
                          onPressed: () => setState(() => day.exercises.removeAt(e.key)),
                        ),
                      ],
                    ),
                  )),
              OutlinedButton.icon(
                onPressed: () => _addExercise(day),
                icon: const Icon(Icons.add),
                label: const Text('افزودنِ حرکت'),
              ),
            ],
          ),
        ),
      );

  Widget _tiny(TextEditingController c, String hint) => TextField(
        controller: c,
        textAlign: TextAlign.center,
        keyboardType: TextInputType.number,
        decoration: InputDecoration(hintText: hint, isDense: true),
      );

  Widget _resultCard(Map<String, dynamic> data) {
    final program = (data['program'] as Map).cast<String, dynamic>();
    return Card(
      margin: const EdgeInsets.only(top: 14),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              data['was_free'] == true
                  ? 'رایگان ساخته شد · شناسهٔ برنامه: ${program['id']}'
                  : '${data['charged_tokens']} توکن کم شد · شناسهٔ برنامه: ${program['id']}',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text((program['generated_workout'] ?? '').toString(),
                style: const TextStyle(fontSize: 13, height: 1.9)),
            const SizedBox(height: 8),
            const Text(
              'PDF را از همان مسیرِ همیشگیِ اپ بگیرید؛ نامِ حرکت‌ها در PDF به صفحهٔ '
              'آموزش لینک است.',
              style: TextStyle(fontSize: 12, color: Colors.black54),
            ),
          ],
        ),
      ),
    );
  }
}

/// جست‌وجو در کتابخانهٔ حرکت‌ها برای انتخابِ حرکت.
class _ExercisePicker extends StatefulWidget {
  const _ExercisePicker({required this.api});

  final ChagherApi api;

  @override
  State<_ExercisePicker> createState() => _ExercisePickerState();
}

class _ExercisePickerState extends State<_ExercisePicker> {
  final _query = TextEditingController();
  List<Map<String, dynamic>> _results = const [];
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _search();
  }

  Future<void> _search() async {
    setState(() => _busy = true);
    try {
      final rows = await widget.api.exerciseSearch(_query.text.trim());
      setState(() => _results = rows);
    } catch (_) {
      setState(() => _results = const []);
    } finally {
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Directionality(
        textDirection: TextDirection.rtl,
        child: Padding(
          padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
          child: SizedBox(
            height: MediaQuery.of(context).size.height * 0.72,
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: TextField(
                    controller: _query,
                    autofocus: true,
                    onChanged: (_) => _search(),
                    decoration: const InputDecoration(
                      labelText: 'نامِ حرکت یا دستگاه',
                      prefixIcon: Icon(Icons.search),
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                if (_busy) const LinearProgressIndicator(),
                Expanded(
                  child: ListView.builder(
                    itemCount: _results.length,
                    itemBuilder: (_, i) {
                      final row = _results[i];
                      final thumb = row['thumb']?.toString();
                      return ListTile(
                        leading: thumb == null || thumb.isEmpty
                            ? const Icon(Icons.fitness_center)
                            : ClipRRect(
                                borderRadius: BorderRadius.circular(6),
                                child: Image.network(thumb,
                                    width: 44,
                                    height: 44,
                                    fit: BoxFit.cover,
                                    errorBuilder: (_, __, ___) =>
                                        const Icon(Icons.fitness_center)),
                              ),
                        title: Text((row['name_fa'] ?? row['name']).toString()),
                        subtitle: Text(row['equipment_fa']?.toString() ?? '',
                            style: const TextStyle(fontSize: 12)),
                        onTap: () => Navigator.of(context).pop(row),
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
        ),
      );
}
