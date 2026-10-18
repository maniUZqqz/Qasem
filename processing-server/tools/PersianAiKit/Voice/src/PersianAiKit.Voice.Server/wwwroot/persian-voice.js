/*
 * PersianVoice — کلاینتِ مرورگر برای سرویسِ صدای فارسی (پروژهٔ Voice؛ بی‌وابستگی؛ در هر صفحه‌ای کپی و استفاده کنید).
 *
 *   PersianVoice.configure({ baseUrl: 'http://192.168.1.10:5600', apiKey: '...' })   // همان سرور ⇒ لازم نیست
 *
 *   ── متن ⇒ گفتار (Piper) ──
 *   PersianVoice.unlockAudio()                       درونِ کلیکِ کاربر (آیفون بی این اجازهٔ پخش نمی‌دهد)
 *   await PersianVoice.speak('سلام، ساعت 10:30')      پخش؛ وقتی تمام شد برمی‌گردد (متنِ بلند جمله‌جمله)
 *   PersianVoice.stopSpeaking()
 *   const blob = await PersianVoice.tts('متن', { voice, speed })   فقط فایلِ WAV
 *
 *   ── گفتار ⇒ متن (Vosk) ──
 *   const r = await PersianVoice.listen()            ضبط تا سکوت ⇒ سرور ⇒ { text, digits, numbers, words }
 *   const wav = await PersianVoice.record({ onLevel }) ; PersianVoice.stopRecording()
 *   const r = await PersianVoice.recognize(wav, { phrases: ['روشن کن', 'خاموش کن'] })   r.phrase = فرمانِ گفته‌شده یا null
 *
 *   ── صدای طبیعی، کلونِ صدا، صدای هر چیز (سرویسِ پایتونیِ voice\ — VOICE-SETUP.md) ──
 *   await PersianVoice.voice.voices()                [{ id, name, gender, kind: 'piper'|'builtin'|'cloned', ... }]
 *   const wav = await PersianVoice.voice.tts('متن', { voice: 'mana', seed })     await PersianVoice.voice.speak('متن', { voice })
 *   const r = await PersianVoice.voice.sfx('باران روی سقف حلبی', { seconds: 8 })   r.blob، r.promptEn (ترجمه‌ای که به مدل رسید)
 *   const v = await PersianVoice.voice.clone.create({ name, person, purpose })   ⇒ { id }   (با رضایتِ صاحبِ صدا)
 *   const s = await PersianVoice.voice.clone.script()      جمله‌هایی که باید خوانده شوند
 *   const wav = await PersianVoice.record({ rate: 24000, raw: true })  ;  await PersianVoice.voice.clone.clip(v.id, 1, s[0], wav)   ⇒ { ok, message }
 *
 * ⚠ میکروفون فقط روی https یا localhost کار می‌کند.
 */
(function (global) {
    'use strict';
    var cfg = { baseUrl: '', apiKey: '' };
    var PA = {};

    function url(p) { return String(cfg.baseUrl || '').replace(/\/$/, '') + p; }
    function call(path, opts) {
        opts = opts || {};
        var h = opts.headers || {};
        if (cfg.apiKey) h['X-Api-Key'] = cfg.apiKey;
        opts.headers = h;
        return fetch(url(path), opts).then(function (r) {
            var ct = r.headers.get('content-type') || '';
            if (!r.ok) {
                return (ct.indexOf('json') >= 0 ? r.json() : r.text()).then(function (b) {
                    var e = new Error((b && b.error) || b || ('HTTP ' + r.status)); e.status = r.status; throw e;
                });
            }
            return ct.indexOf('json') >= 0 ? r.json() : r.blob();
        });
    }
    function post(path, body, type) {
        var h = {}; if (type) h['Content-Type'] = type;
        return call(path, { method: 'POST', headers: h, body: body });
    }

    PA.configure = function (o) { for (var k in o) cfg[k] = o[k]; return PA; };
    PA.health = function () { return call('/api/health'); };
    PA.secure = function () { return !!global.isSecureContext; };

    // ═════════ متن ⇒ گفتار ═════════
    var audio = null, token = 0;
    // WAVِ بی‌صدای کوچک: با همان لمسِ کاربر پخش می‌شود تا پخش‌های بعدی (بی‌لمس) هم اجازه داشته باشند
    var SILENT = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=';
    PA.unlockAudio = function () {
        try { audio = audio || new Audio(); audio.src = SILENT; var p = audio.play(); if (p) p.catch(function () { }); } catch (e) { }
    };

    PA.tts = function (text, o) {
        o = o || {};
        return post('/api/tts', JSON.stringify({ text: text, voice: o.voice || null, speed: o.speed || null }), 'application/json');
    };

    /** جمله‌ها، تکه‌های کوتاه به هم چسبیده (هر تکه ≤ max نویسه) — تکهٔ اول زود می‌رسد. */
    PA.splitSentences = function (text, max) {
        max = max || 220;
        var parts = String(text || '').split(/(?<=[.؟?!:؛\n])\s+/).filter(function (p) { return p.trim().length; });
        var out = [], cur = '';
        parts.forEach(function (p) {
            p = p.trim();
            while (p.length > max) {
                var cut = p.lastIndexOf(' ', max); if (cut < max / 2) cut = max;
                if (cur) { out.push(cur); cur = ''; }
                out.push(p.slice(0, cut).trim()); p = p.slice(cut).trim();
            }
            if (cur && (cur + ' ' + p).length > max) { out.push(cur); cur = p; } else cur = cur ? cur + ' ' + p : p;
        });
        if (cur) out.push(cur);
        return out;
    };

    /** پخش؛ Promise وقتی تمام شد (یا با stopSpeaking قطع شد). تکهٔ بعد هم‌زمان با پخشِ تکهٔ فعلی ساخته می‌شود. */
    PA.speak = function (text, o) {
        PA.stopSpeaking();
        var my = ++token, parts = PA.splitSentences(text), i = 0;
        audio = audio || new Audio();
        if (!parts.length) return Promise.resolve();
        function load(k) { return PA.tts(parts[k], o).then(function (b) { return URL.createObjectURL(b); }); }
        var next = load(0);
        return new Promise(function (resolve, reject) {
            function play() {
                if (my !== token || i >= parts.length) { resolve(); return; }
                var cur = next; i++;
                if (i < parts.length) next = load(i);
                cur.then(function (u) {
                    if (my !== token) { resolve(); return; }
                    audio.onended = function () { URL.revokeObjectURL(u); play(); };
                    audio.onerror = function () { play(); };
                    audio.src = u;
                    var p = audio.play();
                    if (p) p.catch(function (e) { reject(e); });
                }).catch(reject);
            }
            play();
        });
    };
    PA.stopSpeaking = function () { token++; if (audio) { try { audio.pause(); } catch (e) { } } };

    // ═════════ گفتار ⇒ متن ═════════
    var rec = null;

    /**
     * ضبط از میکروفون تا سکوت ⇒ Blobِ WAVِ ۱۶kHz (همان چیزی که سرور می‌خواهد). null اگر حرفی زده نشد.
     * o: silenceMs (۱۸۰۰ — پایان بعد از این مقدار سکوت)، noSpeechMs (۸۰۰۰)، maxMs (۶۰۰۰۰)، threshold (۰٫۰۲)، onLevel(0..1)
     *    rate (۱۶۰۰۰)، raw (false — true: بی حذفِ نویز و تنظیمِ خودکارِ بلندیِ مرورگر؛ برای کلونِ صدا با rate: 24000)
     */
    PA.record = function (o) {
        o = o || {};
        if (!global.isSecureContext) return Promise.reject(new Error('میکروفون فقط روی https یا localhost کار می‌کند.'));
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return Promise.reject(new Error('این مرورگر میکروفون ندارد.'));
        PA.stopRecording(false);
        PA.stopSpeaking();
        var silenceMs = o.silenceMs || 1800, noSpeechMs = o.noSpeechMs || 8000, maxMs = o.maxMs || 60000, threshold = o.threshold || 0.02;
        var target = o.rate || 16000, proc = !o.raw;
        return navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: proc, noiseSuppression: proc, autoGainControl: proc } })
            .then(function (stream) {
                return new Promise(function (resolve) {
                    var AC = global.AudioContext || global.webkitAudioContext;
                    var ctx = new AC(), src = ctx.createMediaStreamSource(stream), proc = ctx.createScriptProcessor(4096, 1, 1);
                    var r = { stream: stream, ctx: ctx, src: src, proc: proc, chunks: [], rate: ctx.sampleRate, target: target, spoke: false, last: 0, t0: Date.now(), resolve: resolve };
                    rec = r;
                    proc.onaudioprocess = function (e) {
                        var d = e.inputBuffer.getChannelData(0);
                        r.chunks.push(new Float32Array(d));
                        var sum = 0; for (var k = 0; k < d.length; k += 4) sum += d[k] * d[k];
                        var rms = Math.sqrt(sum / (d.length / 4));
                        if (rms > threshold) { r.spoke = true; r.last = Date.now(); }
                        if (o.onLevel) try { o.onLevel(Math.min(1, rms * 8)); } catch (x) { }
                    };
                    src.connect(proc); proc.connect(ctx.destination);
                    if (ctx.resume) ctx.resume();
                    r.timer = setInterval(function () {
                        if (rec !== r) return;
                        var now = Date.now();
                        if ((r.spoke && now - r.last > silenceMs) || (!r.spoke && now - r.t0 > noSpeechMs) || now - r.t0 > maxMs) PA.stopRecording(true);
                    }, 200);
                });
            });
    };

    /** پایانِ ضبط (دکمهٔ «بس است»). keep=false ⇒ دور ریخته شود. */
    PA.stopRecording = function (keep) {
        if (!rec) return;
        var r = rec; rec = null;
        clearInterval(r.timer);
        try { r.proc.disconnect(); r.src.disconnect(); } catch (e) { }
        try { r.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) { }
        try { r.ctx.close(); } catch (e) { }
        r.resolve(keep !== false && r.spoke ? PA.encodeWav(r.chunks, r.rate, Math.min(r.target, r.rate)) : null);
    };
    PA.recording = function () { return !!rec; };

    /** Float32 با نرخِ دستگاه ⇒ WAVِ PCMِ ۱۶بیتی با نرخِ target (میانگینِ هر پنجره = پایین‌گذرِ ساده). */
    PA.encodeWav = function (chunks, rate, target) {
        var n = 0; chunks.forEach(function (c) { n += c.length; });
        var all = new Float32Array(n), off = 0;
        chunks.forEach(function (c) { all.set(c, off); off += c.length; });
        var ratio = rate / target, m = Math.floor(n / ratio), out = new Int16Array(m);
        for (var i = 0; i < m; i++) {
            var a = Math.floor(i * ratio), b = Math.min(n, Math.floor((i + 1) * ratio)), s = 0, k = 0;
            for (var j = a; j < b; j++) { s += all[j]; k++; }
            var v = Math.max(-1, Math.min(1, k ? s / k : 0));
            out[i] = v < 0 ? v * 0x8000 : v * 0x7FFF;
        }
        var buf = new ArrayBuffer(44 + out.length * 2), dv = new DataView(buf);
        function str(o2, t) { for (var q = 0; q < t.length; q++) dv.setUint8(o2 + q, t.charCodeAt(q)); }
        str(0, 'RIFF'); dv.setUint32(4, 36 + out.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
        dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
        dv.setUint32(24, target, true); dv.setUint32(28, target * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
        str(36, 'data'); dv.setUint32(40, out.length * 2, true);
        for (var p = 0; p < out.length; p++) dv.setInt16(44 + p * 2, out[p], true);
        return new Blob([buf], { type: 'audio/wav' });
    };

    /**
     * WAV ⇒ { text, digits, numbers, phrase, words, seconds }.
     * o.phrases: فرمان‌ها — متن آزاد شنیده می‌شود و فرمانی که در آن گفته شد در phrase می‌آید (حرفِ بی‌ربط ⇒ null).
     * o.strict:  فقط همین واژه‌ها شنیده شوند (هر صدایی به یکی از آن‌ها می‌خورد) — فقط برای پاسخِ کوتاهِ بله/نه.
     */
    PA.recognize = function (wav, o) {
        o = o || {};
        var q = [];
        if (o.phrases && o.phrases.length) q.push('phrases=' + encodeURIComponent(o.phrases.join('|')));
        if (o.strict && o.strict.length) q.push('strict=' + encodeURIComponent(o.strict.join('|')));
        return post('/api/asr' + (q.length ? '?' + q.join('&') : ''), wav, 'audio/wav');
    };

    /** ضبط تا سکوت + فهمیدن. حرفی زده نشد ⇒ { text: '', empty: true }. */
    PA.listen = function (o) {
        return PA.record(o).then(function (wav) { return wav ? PA.recognize(wav, o) : { text: '', empty: true }; });
    };

    // ═════════ صدای طبیعی، کلونِ صدا، صدای هر چیز ═════════
    function postJson(path, body) { return post(path, JSON.stringify(body), 'application/json'); }
    /** مثلِ call ولی Blob + سرآیندهای X-* را هم برمی‌گرداند. */
    function audioCall(path, body) {
        var h = { 'Content-Type': 'application/json' };
        if (cfg.apiKey) h['X-Api-Key'] = cfg.apiKey;
        return fetch(url(path), { method: 'POST', headers: h, body: JSON.stringify(body) }).then(function (r) {
            if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) {
                var e = new Error(b.error || ('HTTP ' + r.status)); e.status = r.status; throw e;
            });
            return r.blob().then(function (b) {
                var hd = function (k) { return r.headers.get(k); };
                return { blob: b, engine: hd('X-Voice-Engine'), seconds: +hd('X-Voice-Seconds') || null, took: +hd('X-Voice-Took') || null,
                    seed: hd('X-Seed'), cached: hd('X-Voice-Cache') === 'hit',
                    check: hd('X-Voice-Check') == null ? null : +hd('X-Voice-Check'),   // خطای واژه با گفتار‌به‌متن (۰ = کامل)
                    promptEn: hd('X-Prompt-En') ? decodeURIComponent(hd('X-Prompt-En')) : null, promptMethod: hd('X-Prompt-Method') };
            });
        });
    }
    PA.voice = {
        engines: function () { return call('/api/voice/engines'); },
        voices: function () { return call('/api/voice/voices').then(function (r) { return r.voices; }); },
        sampleUrl: function (id) { return url('/api/voice/voices/' + encodeURIComponent(id) + '/sample') + (cfg.apiKey ? '?key=' + encodeURIComponent(cfg.apiKey) : ''); },
        /** متن ⇒ { blob, engine, seconds, took, seed }. o: voice, engine, seed (عددِ دیگر = ساختِ دوباره با همان صدا) */
        synth: function (text, o) { o = o || {}; return audioCall('/api/voice/tts', { text: text, voice: o.voice || null, engine: o.engine || null, seed: o.seed == null ? null : String(o.seed) }); },
        tts: function (text, o) { return PA.voice.synth(text, o).then(function (r) { return r.blob; }); },
        /** پخش (منتظر تا پایان). */
        speak: function (text, o) {
            PA.stopSpeaking();
            var my = ++token;
            audio = audio || new Audio();
            return PA.voice.tts(text, o).then(function (b) {
                if (my !== token) return;
                var u = URL.createObjectURL(b);
                return new Promise(function (res, rej) {
                    audio.onended = function () { URL.revokeObjectURL(u); res(); };
                    audio.onerror = function () { res(); };
                    audio.src = u;
                    var p = audio.play(); if (p) p.catch(rej);
                });
            });
        },
        /** توصیف (فارسی یا انگلیسی) ⇒ { blob, promptEn, seed }. o: seconds (۱ تا ۴۷)، seed، promptEn (ترجمهٔ درست‌شده) */
        sfx: function (prompt, o) { o = o || {}; return audioCall('/api/voice/sfx', { prompt: prompt, seconds: o.seconds || 8, seed: o.seed == null ? null : String(o.seed), promptEn: o.promptEn || null }); },
        translate: function (prompt) { return postJson('/api/voice/sfx/translate', { prompt: prompt }); },
        remove: function (id) { return call('/api/voice/voices/' + encodeURIComponent(id), { method: 'DELETE' }); },
        clone: {
            script: function () { return call('/api/voice/script').then(function (r) { return r.sentences; }); },
            /** o: name، person (صاحبِ صدا)، purpose — فقط با رضایتِ خودش */
            create: function (o) { return postJson('/api/voice/clone', { name: o.name, person: o.person, purpose: o.purpose, consent: true }); },
            /** یک جملهٔ ضبط‌شده ⇒ { ok, message, heard, wer, snr, clips, minutes } */
            clip: function (id, index, text, wav) {
                return post('/api/voice/clone/clip?voice=' + encodeURIComponent(id) + '&index=' + index + '&text=' + encodeURIComponent(text), wav, 'audio/wav');
            },
        },
    };

    global.PersianVoice = PA;
})(window);
