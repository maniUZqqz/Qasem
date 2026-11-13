"""آزمونِ «Cycles کارتِ گرافیک را می‌بیند؟» (موتورِ ۱٫۳؛ فقط کتابخانهٔ استاندارد).

  python probe_gpu.py <blender.exe> [--explain]

Blender را بی‌مانیتور اجرا می‌کند و از Cycles می‌پرسد کدام دستگاه‌های OptiX / CUDA (و HIP، oneAPI، Metal) را می‌شناسد.
  خروجی ۰ = دست‌کم یک کارتِ OptiX یا CUDA پیدا شد (OptiX اول)؛ یک خطِ «UP3D-GPU …» چاپ می‌شود.
  خروجی ۲ = Blender اجرا شد ولی هیچ کارتی نمی‌بیند؛ علت و راهِ رفع (درایور) به فارسی و انگلیسی چاپ می‌شود.
  خروجی ۳ = Blender پیدا نشد یا اجرا نشد.
نصبِ خودکارِ گره (processing/requirements.d/blender-3d.json) از همین برای بخشِ «Cycles روی GPU» استفاده می‌کند؛ نتیجه در پنل دیده می‌شود.
"""
import json
import os
import subprocess
import sys

CODE = r"""
import bpy, json
res = []
try:
    p = bpy.context.preferences.addons['cycles'].preferences
except Exception as e:
    print('UP3D-PROBE ' + json.dumps({'error': 'cycles addon: %s' % e}))
    raise SystemExit(0)
for t in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
    try:
        p.compute_device_type = t
        try:
            p.refresh_devices()
        except Exception:
            pass
        p.get_devices()
        res += [{'type': t, 'name': d.name} for d in p.devices if d.type == t]
    except Exception:
        pass
print('UP3D-PROBE ' + json.dumps({'version': bpy.app.version_string, 'devices': res}))
"""

HINT = ("Cycles in Blender sees no OptiX/CUDA GPU on this computer. Install or update the NVIDIA driver (version 527 or newer; "
        "https://www.nvidia.com/Download/index.aspx) and restart the computer once. | "
        "Cycles در Blender هیچ کارتِ گرافیکِ OptiX/CUDA نمی‌بیند: درایورِ NVIDIA را (نسخهٔ ۵۲۷ یا بالاتر) نصب/به‌روز کنید و یک بار کامپیوتر را ری‌استارت کنید.")


def probe(exe, timeout=240):
    """(info dict or None, error text). info = {'version', 'devices': [{'type','name'}]}."""
    try:
        out = subprocess.run([exe, '-b', '--factory-startup', '--python-expr', CODE], capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL, encoding='utf-8', errors='replace')
    except (OSError, subprocess.SubprocessError) as e:
        return None, 'Blender could not be started: %s' % e
    for line in (out.stdout or '').splitlines():
        if line.startswith('UP3D-PROBE '):
            try:
                return json.loads(line[len('UP3D-PROBE '):]), ''
            except ValueError:
                break
    return None, ('Blender printed no probe result (exit %s): %s' % (out.returncode, ((out.stderr or '') + (out.stdout or ''))[-300:])).strip()


def main(argv):
    if not argv:
        print('usage: probe_gpu.py <blender> [--explain]')
        return 3
    exe = argv[0]
    if not os.path.isfile(exe):
        print('Blender is not installed yet (%s) | Blender هنوز نصب نشده است' % exe)
        return 3
    info, err = probe(exe)
    if info is None:
        print(err)
        return 3
    if info.get('error'):
        print(info['error'])
        return 3
    devs = info.get('devices') or []
    gpus = [d for d in devs if d['type'] in ('OPTIX', 'CUDA')]
    if not gpus:
        print(HINT + ('' if not devs else ' (other devices: %s)' % ', '.join('%s:%s' % (d['type'], d['name']) for d in devs)))
        return 2
    best = 'OPTIX' if any(d['type'] == 'OPTIX' for d in gpus) else 'CUDA'
    print('UP3D-GPU Blender %s; Cycles %s on %s (%s)' % (info.get('version'), best, gpus[0]['name'],
                                                      ', '.join(sorted({d['type'] for d in gpus}))))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
