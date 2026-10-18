"""خطِ فرمان:  python -m up3d <فرمان>

  assets [kind]                         فهرستِ دارایی‌ها
  template <name> --brief brief.json    ساختِ صحنه از قالب      (-o scene.json)
  plan --brief brief.json               ساختِ صحنه با کارگردانِ AI  (کلید: UP3D_AI_KEY / UP3D_AI_BASE_URL / UP3D_AI_MODEL)
  validate scene.json [--repair]        وارسی (و ترمیم)
  compile scene.json --profile preview  برنامهٔ اجرایی (-o compiled.json)
  render scene.json --profile preview   کلِ خط روی همین ماشین ⇐ final.mp4
  export scene.json --format glb        خروجیِ سه‌بعدی (وب/بازی/نرم‌افزارهای دیگر)
  worker --server URL --token T         کارگرِ رندر
"""
import argparse
import json
import os
import sys


def _load(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _dump(obj, path=None):
    text = json.dumps(obj, ensure_ascii=False, indent=1)
    if path:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
        print('نوشته شد:', path)
    else:
        print(text)


def ai_settings_from_env():
    return {'api_key': os.environ.get('UP3D_AI_KEY') or os.environ.get('OPENAI_API_KEY', ''),
            'base_url': os.environ.get('UP3D_AI_BASE_URL') or os.environ.get('OPENAI_BASE_URL', ''),
            'model': os.environ.get('UP3D_AI_MODEL', 'gpt-4o-mini')}


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(prog='up3d', description='UpMarket 3D')
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('assets')
    a.add_argument('kind', nargs='?')
    t = sub.add_parser('template')
    t.add_argument('name')
    t.add_argument('--brief')
    t.add_argument('-o')
    p = sub.add_parser('plan')
    p.add_argument('--brief', required=True)
    p.add_argument('-o')
    v = sub.add_parser('validate')
    v.add_argument('scene')
    v.add_argument('--repair', action='store_true')
    v.add_argument('-o')
    c = sub.add_parser('compile')
    c.add_argument('scene')
    c.add_argument('--profile', default='preview')
    c.add_argument('-o')
    r = sub.add_parser('render')
    r.add_argument('scene')
    r.add_argument('--profile', default='preview')
    r.add_argument('--job-dir')
    r.add_argument('--threads', type=int, default=0)
    e = sub.add_parser('export')
    e.add_argument('scene')
    e.add_argument('--format', default='glb', choices=['glb', 'gltf', 'fbx', 'usd', 'blend'])
    e.add_argument('--job-dir')
    w = sub.add_parser('worker')
    w.add_argument('--server', required=True)
    w.add_argument('--token', required=True)
    w.add_argument('--name')
    w.add_argument('--profiles', default='')
    w.add_argument('--nice', type=int, default=15)
    w.add_argument('--threads', type=int, default=0)
    w.add_argument('--once', action='store_true')
    args = ap.parse_args(argv)

    from .assets import registry
    reg = registry()
    if args.cmd == 'assets':
        if args.kind:
            for x in reg.list(args.kind):
                print('%-22s %s' % (x.id, x.label()))
        else:
            for k, n in reg.counts().items():
                print('%-16s %d' % (k, n))
            for pr in reg.problems:
                print('مشکل:', pr)
    elif args.cmd == 'template':
        from . import templates
        doc = templates.build(args.name, _load(args.brief) if args.brief else {}, reg)
        _dump(doc, args.o)
    elif args.cmd == 'plan':
        from . import director
        doc, info = director.plan(_load(args.brief), ai_settings_from_env(), reg)
        print('منبع:', info['source'], info.get('fallback_reason', ''), file=sys.stderr)
        _dump(doc, args.o)
    elif args.cmd == 'validate':
        from .validate import repair, validate
        doc = _load(args.scene)
        if args.repair:
            doc, changes, rep = repair(doc, reg)
            for ch in changes:
                print('ترمیم:', ch)
            if args.o:
                _dump(doc, args.o)
        else:
            rep = validate(doc, reg)
        for i in rep.issues:
            print('[%s] %s: %s' % (i['level'], i['path'], i['message']))
        print('معتبر' if rep.ok else 'نامعتبر')
        return 0 if rep.ok else 1
    elif args.cmd == 'compile':
        from . import compiler
        _dump(compiler.compile_scene(_load(args.scene), reg, args.profile), args.o)
    elif args.cmd == 'render':
        from . import pipeline
        out = pipeline.run_local(_load(args.scene), args.profile, args.job_dir, threads=args.threads)
        print('ویدئو:', out['video'])
        print('کیفیت:', out['qc']['result'])
    elif args.cmd == 'export':
        from . import paths, pipeline
        jd = args.job_dir or paths.job_dir('export-%s' % os.getpid())
        pipeline.prepare(_load(args.scene), jd, 'animatic')
        pipeline.render(jd, mode='export', extra=['--format', args.format], log_path=os.path.join(jd, 'engine.log'))
        print('خروجی در', jd)
    elif args.cmd == 'worker':
        from .worker import Worker
        profiles = [x for x in args.profiles.split(',') if x] or None
        Worker(args.server, args.token, args.name, profiles, args.nice, args.threads, once=args.once).loop()
    return 0
