"""وضعیتِ مشترکِ ساختِ صحنه (برنامهٔ اجرایی، بازیگرها، محصول‌ها، نگه‌داشتن‌ها، گزارش)."""
import hashlib
import math

import bpy
from mathutils import Matrix, Quaternion, Vector


class Context:
    def __init__(self, compiled, out_dir):
        self.c = compiled
        self.out = out_dir
        self.fps = compiled['fps']
        self.f_start = compiled['frame_start']
        self.f_end = compiled['frame_end']
        self.profile = compiled['profile']
        self.quality = self.profile.get('quality', {})
        self.rigs = {}
        self.products = {}
        self.hold_G = {}
        self._holding = {}      # (actor, side) -> [(f_from, f_to|None, pid)]
        self.events = []
        self.cameras = []
        self.report = {'warnings': []}
        self._colls = {}
        self.root_coll = bpy.context.scene.collection
        self.energy = {}        # actor -> {frame: 0..1}

    def coll(self, name):
        if name not in self._colls:
            c = bpy.data.collections.new(name)
            self.root_coll.children.link(c)
            self._colls[name] = c
        return self._colls[name]

    def seed(self, key):
        return int(hashlib.md5(str(key).encode()).hexdigest()[:6], 16) / float(0xFFFFFF) * 10.0

    # ── محیط
    def surface_matrix(self, sid):
        sp = self.c['environment']['surfaces'][sid]
        return Matrix.LocRotScale(Vector(sp['pos']), Quaternion((0, 0, 1), math.radians(sp.get('yaw', 0.0))),
                                  Vector((1, 1, 1)))

    # ── نگه‌داشتن
    def holding(self, actor, side, frame=None):
        """الان (در ترتیبِ اعمالِ حرکت‌ها) چه چیزی در این دست است؟"""
        spans = self._holding.get((actor, side), [])
        if not spans:
            return None
        if frame is None:
            last = spans[-1]
            return last[2] if last[1] is None else None
        for a, b, pid in spans:
            if a <= frame and (b is None or frame <= b):
                return pid
        return None

    def begin_hold(self, pid, actor, side, f_grasp, gp):
        self._holding.setdefault((actor, side), []).append([f_grasp, None, pid])
        self.products[pid].holds.append({'actor': actor, 'side': side, 'f_grasp': f_grasp, 'f_release': None,
                                         'gp': gp, 'release_world': None})

    def end_hold(self, pid, f_release, release_world, surface_id):
        for spans in self._holding.values():
            for sp in spans:
                if sp[2] == pid and sp[1] is None:
                    sp[1] = f_release
        prod = self.products[pid]
        if prod.holds and prod.holds[-1]['f_release'] is None:
            prod.holds[-1]['f_release'] = f_release
            prod.holds[-1]['release_world'] = release_world
        prod.place_world = release_world.copy()
        prod.surface_id = surface_id

    # ── صدا
    def set_energy(self, actor, segments):
        d = self.energy.setdefault(actor, {})
        for seg in segments or []:
            for i, v in enumerate(seg['values']):
                d[seg['f0'] + i] = max(v, d.get(seg['f0'] + i, 0.0))

    def energy_at(self, actor, frame):
        return self.energy.get(actor, {}).get(int(frame), 0.0)

    def energy_peaks(self, actor, f0, f1, min_gap=12, thresh=0.55):
        e = self.energy.get(actor, {})
        if not e:
            # بی‌صدا: از بازه‌های گفتار در compiled
            spans = [s for s in self.c['face'].get(actor, {}).get('speaking', []) if s[1] > f0 and s[0] < f1]
            peaks = []
            for a, b in spans:
                f = max(a + 8, f0)
                while f < min(b, f1):
                    peaks.append(f)
                    f += min_gap * 1.6
            return peaks
        peaks = []
        last = -1e9
        for f in range(int(f0), int(f1)):
            v = e.get(f, 0.0)
            if v >= thresh and v >= e.get(f - 1, 0) and v >= e.get(f + 1, 0) and f - last >= min_gap:
                peaks.append(f)
                last = f
        return peaks

    def warn(self, msg):
        self.report['warnings'].append(msg)
