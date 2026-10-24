"""پختن (bake): یک دور روی همهٔ فریم‌ها با اسکلتِ ارزیابی‌شده.

  - محصولِ در دست فریم‌به‌فریم همراهِ مچ (تبدیلِ ثابتِ لحظهٔ گرفتن) ⇐ بی‌لغزش، بی‌پرش
  - ثبتِ مسیرِ سر/سینه/لگنِ هر بازیگر (برای دوربین و نگاه)
  - اندازه‌گیریِ کیفیت: فاصلهٔ دست تا نقطهٔ گرفتن، معلق‌ماندنِ محصول پس از گذاشتن، لغزشِ پا، پرشِ مفصل
"""
import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import anim
from .util import log, progress


def run(ctx):
    sc = bpy.context.scene
    frames = anim.frames_range(ctx.f_start, ctx.f_end)
    for rig in ctx.rigs.values():
        rig.hide_meshes(True)
    rec = {aid: {'head': {}, 'eyes': {}, 'chest': {}, 'hips': {}, 'feet0': None} for aid in ctx.rigs}
    rq = {aid: {} for aid in ctx.rigs}
    grasp_err, float_err, slide, jump = [], [], 0.0, (0.0, '')
    prod_series = {pid: {} for pid in ctx.products}
    hold_state = {}
    watch = {}
    for aid, rig in ctx.rigs.items():
        r = rig.roles
        watch[aid] = [r['arm.R']['hand'], r['arm.L']['hand'], r['head'], r['spine'][-1], r['arm.R']['fore'], r['arm.L']['fore']]
    for i, f in enumerate(frames):
        sc.frame_set(f)
        for aid, rig in ctx.rigs.items():
            mw = rig.arm.matrix_world
            pb = rig.pb
            r = rig.roles
            rec[aid]['head'][f] = mw @ pb[r['head']].head
            rec[aid]['eyes'][f] = rig.eyes_point()
            rec[aid]['chest'][f] = mw @ pb[r['spine'][-1]].head
            rec[aid]['hips'][f] = mw @ pb[r['hips']].head
            # لغزشِ پا در «فضای بازیگر»: جابه‌جاییِ کل‌بدن با کلیدهای ویرایشگر لغزش نیست
            inv = rig.root.matrix_world.inverted()
            feet = [inv @ rig.foot_world(s) for s in ('R', 'L')]
            if rec[aid]['feet0'] is None:
                rec[aid]['feet0'] = feet
            else:
                slide = max(slide, max((a - b).length for a, b in zip(feet, rec[aid]['feet0'])))
            for b in watch[aid]:
                q = (mw @ pb[b].matrix).to_quaternion()
                prev = rq[aid].get(b)
                if prev is not None and i > 0:
                    ang = math.degrees(prev.rotation_difference(q).angle)
                    ang = min(ang, 360.0 - ang)   # q و -q یک چرخش‌اند
                    if ang > jump[0]:
                        jump = (ang, '%s@%d' % (b, f))
                rq[aid][b] = q
        for pid, prod in ctx.products.items():
            resting = prod.keyed_world(f) if prod.keys else prod.rest_world
            for h in prod.holds:
                if h['f_release'] is not None and f > h['f_release']:
                    resting = hold_state.get(('released', id(h)), resting)
            active = next((h for h in prod.holds
                           if f >= h['f_grasp'] and (h['f_release'] is None or f <= h['f_release'])), None)
            if not active:
                prod_series[pid][f] = resting.copy()
                continue
            rig = ctx.rigs[active['actor']]
            W = rig.wrist_matrix_world(active['side'])
            key = ('G', id(active))
            if key not in hold_state:
                # لحظهٔ گرفتن: تبدیلِ واقعی از روی مچِ واقعی (بی‌پرش) + خطای رسیدنِ دست
                hold_state[key] = W.inverted() @ resting
                ideal = rig.root.matrix_world @ Matrix.LocRotScale(active['gp']['wrist'], active['gp']['q'], Vector((1, 1, 1)))
                grasp_err.append((W.translation - ideal.translation).length * 1000)
            cur = W @ hold_state[key]
            if active['f_release'] is not None and f == active['f_release']:
                rw = active['release_world']
                err = (cur.translation - rw.translation).length * 1000
                float_err.append(err)
                hold_state[('attached_end', id(active))] = cur.copy()
                cur = rw.copy() if err < 40 else cur
                hold_state[('released', id(active))] = cur.copy()
            prod_series[pid][f] = cur.copy()
        if i % 10 == 0:
            progress(i + 1, len(frames))
    for rig in ctx.rigs.values():
        rig.hide_meshes(False)
    # کلیدهای محصول (+ پخشِ نرمِ اصلاحِ «نشستن روی سطح» در ۴ فریمِ آخرِ نگه‌داشتن)
    for pid, prod in ctx.products.items():
        ser = prod_series[pid]
        for h in prod.holds:
            end = hold_state.get(('attached_end', id(h)))
            final = hold_state.get(('released', id(h)))
            if h['f_release'] is None or end is None or final is None:
                continue
            # اختلافِ کوچکِ «جای دست» تا «جای دقیق روی سطح» نرم در ۴ فریمِ آخر پخش می‌شود
            dloc = final.translation - end.translation
            dq = final.to_quaternion() @ end.to_quaternion().inverted()
            for k in range(1, 5):
                f = h['f_release'] - k
                if f in ser:
                    u = 1 - k / 5.0
                    loc, rot, _ = ser[f].decompose()
                    ser[f] = Matrix.LocRotScale(loc + dloc * u, Quaternion().slerp(dq, u) @ rot, Vector((1, 1, 1)))
        locs, rots, prev = [], [], None
        for f in frames:
            loc, rot, _ = ser[f].decompose()
            if prev is not None and prev.dot(rot) < 0:
                rot = -rot
            prev = rot
            locs.append(loc[:])
            rots.append(rot[:])
        prod.root.parent = None
        anim.bulk_keys(prod.root, 'location', frames, locs)
        anim.bulk_keys(prod.root, 'rotation_quaternion', frames, rots)
        if prod.keys and any(k.get('scale') is not None for k in prod.keys):
            anim.bulk_keys(prod.root, 'scale', frames, [ser[f].to_scale()[:] for f in frames])
        prod.baked = ser
    ctx.rec = rec
    rep = ctx.report
    rep['grasp_max_mm'] = max(grasp_err) if grasp_err else None
    rep['release_float_max_mm'] = max(float_err) if float_err else None
    rep['foot_slide_max_mm'] = slide * 1000
    rep['joint_jump_max_deg'] = jump[0]
    rep['joint_jump_bone'] = jump[1]
    log('bake', 'grasp_mm=%s float_mm=%s slide_mm=%.1f jump=%.1f(%s)' % (
        rep['grasp_max_mm'], rep['release_float_max_mm'], slide * 1000, jump[0], jump[1]))


def series_fn(ctx):
    """تابعِ نقطهٔ سوژه برای دوربین و نگاه."""
    def fn(kind, sid, anchor, f):
        if kind == 'actor':
            r = ctx.rec[sid]
            if anchor in ('eyes', 'face'):
                return r['eyes'].get(f, r['eyes'][min(r['eyes'])])
            if anchor == 'chest':
                return r['chest'][f] + Vector((0, 0, 0.04))
            if anchor == 'waist':
                return r['hips'][f] + Vector((0, 0, 0.12))
            if anchor == 'full':
                rig = ctx.rigs[sid]
                return Vector((r['hips'][f].x, r['hips'][f].y, rig.L['height'] * 0.52))
            return r['head'][f]
        prod = ctx.products[sid]
        return prod.center_world(f)
    return fn


def gaze(ctx, fn):
    """هدفِ نگاهِ چشم و سر در هر فریم (چشم سریع، سر آهسته‌تر) + تکانِ سر (nod) از کانالِ head_off."""
    frames = anim.frames_range(ctx.f_start, ctx.f_end)
    for aid, rig in ctx.rigs.items():
        segs = ctx.c['gaze'].get(aid, [])

        def target_at(f):
            tg = 'camera'
            for s in segs:
                if s['f0'] <= f <= s['f1']:
                    tg = s['target']
            if tg == 'camera':
                return ctx.camera_pos.get(f) or (rig.root.matrix_world @ (rig.L['eyes'] + Vector((0, -2, 0))))
            if tg == 'forward':
                return rig.root.matrix_world @ (rig.L['eyes'] + Vector((0, -2, -0.05)))
            kind, sid = tg.split(':', 1)
            if kind == 'product' and sid in ctx.products:
                return ctx.products[sid].center_world(f)
            if kind == 'actor' and sid in ctx.rec:
                return ctx.rec[sid]['eyes'][f]
            return rig.root.matrix_world @ (rig.L['eyes'] + Vector((0, -2, 0)))
        raw = [target_at(f) for f in frames]
        # چشم: جهش (saccade) به هدفِ تازه در ۲-۳ فریم + ریزجهش‌های پله‌ای هنگامِ خیره ماندن
        # سر: با ~۱۲۰ میلی‌ثانیه تأخیر و فنرِ نرم دنبالِ چشم می‌رود (قبلاً هر دو هموارسازیِ دوطرفه بودند ⇐
        # سر و چشم پیش از عوض‌شدنِ هدف راه می‌افتادند و حرکت «شناور» بود)
        eyes, cur = [], Vector(raw[0])
        for p in raw:
            cur = cur.lerp(Vector(p), 0.62)
            eyes.append(cur.copy())
        delay = max(1, int(round(ctx.fps * 0.12)))
        delayed = [raw[max(0, i - delay)] for i in range(len(raw))]
        head = anim.spring_follow(delayed, ctx.fps, freq=1.25, zeta=0.92)
        sacc = anim.saccade_offsets(frames, ctx.fps, ctx.seed(aid))
        e_locs, h_locs = [], []
        for i, f in enumerate(frames):
            ep = ctx.rec[aid]['eyes'][f]
            t = f / ctx.fps
            dist_e = max(0.3, (eyes[i] - ep).length)
            k = dist_e * 0.006                      # ~۰٫۳ درجه
            e_locs.append((eyes[i] + Vector((sacc[i].x * k, 0, sacc[i].y * k)))[:])
            pitch, yaw, _ = rig.ch['head_off'].value(f)
            hp = head[i] + Vector((anim.noise1(t * 0.31, ctx.seed(aid) + 41) * 0.012 * dist_e,
                                   0, anim.noise1(t * 0.27, ctx.seed(aid) + 43) * 0.008 * dist_e))
            dist = max(0.3, (hp - ep).length)
            hp = hp + Vector((0, 0, -math.tan(math.radians(pitch)) * dist)) + Vector((math.tan(math.radians(yaw)) * dist, 0, 0))
            h_locs.append(hp[:])
        anim.bulk_keys(rig.t['look_eyes'], 'location', frames, e_locs)
        anim.bulk_keys(rig.t['look_head'], 'location', frames, h_locs)
