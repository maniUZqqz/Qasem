// «فعالیت»: a page of its own. Everything the engine does, each one apart — the job running now, the queue's tasks, the jobs that
// ended (with their saved logs) — in a list, and the full detail of the chosen one beside it. Model and rows: actmodel.js.
import { h, icon, ltr, bdi, mount } from "../core/dom.js";
import { api, avatarUrl, cancelJob, cleanUsername, runPictureUrl, shotUrl, submitCode } from "../core/api.js";
import { state, subscribe, pokePolling } from "../core/store.js";
import { avatar, button, chip, empty, field, pagedList, segmented, setBusy, skeleton, spinner, toast } from "../core/ui.js";
import { confirm } from "../core/overlay.js";
import { JOB_TITLE, STEP_TITLE, KIND } from "../core/jobs.js";
import { ago, clock, faDateTime, faNum, faTime, unit } from "../core/format.js";
import { enter } from "../core/motion.js";
import { liveWindow } from "../core/livewindow.js";
import { outcomeCard, resultSummary } from "./outcome.js";
import { FILTERS, MODE_IC, PILL, TASK_IC, TASK_TITLE, inFilter, isLive, items, overview, row, runState, taskProgress } from "./actmodel.js";
import { noticeList } from "./notify.js";

const FIN = new Set(["success", "failed", "cancelled"]);
const STEP_IC = { done: "check", failed: "x", waiting: "clock" };
const STEP_SR = { idle: "هنوز شروع نشده", active: "در حال انجام", done: "انجام شد", failed: "ناموفق", skipped: "رد شد", waiting: "منتظر تو" };
const TAG = { running: ["در حال اجرا"], need_code: ["منتظر کد", "warn"], need_manual: ["منتظر تو", "warn"],
  success: ["انجام شد", "ok"], failed: ["ناموفق", "danger"], cancelled: ["لغو شد", "warn"] };
const LEVEL = { ok: "موفق", warn: "هشدار", err: "خطا" };
const OFFLINE = "سرور محلی در دسترس نیست؛ برنامه را دوباره اجرا کن.";
const ISOLATES = new RegExp(`[${String.fromCharCode(0x2066)}-${String.fromCharCode(0x2069)}]`, "g");
const toLatin = (s) => s.replace(/[۰-۹]/g, (d) => d.charCodeAt(0) - 0x6f0).replace(/[٠-٩]/g, (d) => d.charCodeAt(0) - 0x660);

// Log times are "HH:MM:SS" (server clock = this PC); a run that crosses midnight still counts forward.
const secs = (t) => { const m = /^(\d+):(\d+):(\d+)/.exec(t || ""); return m ? +m[1] * 3600 + +m[2] * 60 + +m[3] : null; };
const nowSecs = (d = new Date()) => d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds();
const elapsed = (s, a = secs(state.log[0]?.t), b = s?.busy ? nowSecs() : secs(state.log.at(-1)?.t)) =>
  (a === null || b === null ? null : (b - a + 86400) % 86400);

const quote = (text) => (text ? h("blockquote", { class: "ac-q", dir: "auto", text }) : null);
// The browser window's screenshot opens large in the shared viewer (rule 16).
const shotButton = (n, src = shotUrl(n)) => h("button", { type: "button", class: "ac-shot", "data-zoom": "", "data-zoom-src": src,
  "data-zoom-title": "عکس پنجرهٔ مرورگر", "aria-label": "باز کردن عکس پنجرهٔ مرورگر در اندازهٔ بزرگ" },
h("img", { src, alt: "عکس صفحه‌ای که اینستاگرام در پنجرهٔ مرورگر نشان می‌دهد", loading: "lazy", decoding: "async" }));
// a finished run's own picture of its window: the moment it stopped, or (a crashed page takes none) the last one before it
const runPicture = (rec) => {
  if (!rec.picture_at) return null;
  const crashed = (rec.log || []).some((l) => /crashed/i.test(l.msg || ""));
  return h("figure", { class: "act-pic" }, shotButton(null, runPictureUrl(rec.id)),
    h("figcaption", { class: "act-pic-cap" }, `عکسِ پنجره، ${faTime(rec.picture_at)}`,
      crashed ? h("span", { text: " — صفحه بعد از این کرش کرد؛ بعد از کرش عکس گرفتن ممکن نیست، پس این آخرین عکس است." }) : null));
};
const badge = (ic) => h("span", { class: "ac-badge", "aria-hidden": "true" }, h("span", { class: "ac-badge-in" }, icon(ic, { size: "lg" })));

const stopJob = (btn) => { setBusy(btn, true); cancelJob().then((r) => r.ok || toast("لغو انجام نشد؛ دوباره امتحان کن.", { tone: "danger" }))
  .catch(() => toast(OFFLINE, { tone: "danger" })).finally(() => { setBusy(btn, false); pokePolling(); }); };
// The copy drops the hidden direction marks the server puts around Latin parts.
const copyLog = () => Promise.resolve().then(() => navigator.clipboard.writeText(state.log.map((l) => `${l.t}  ${l.msg}`).join("\n").replace(ISOLATES, "")))
  .then(() => toast("گزارش کپی شد", { tone: "ok" }), () => toast("کپی نشد؛ متن گزارش را دستی انتخاب کن.", { tone: "danger" }));

/** Steps on a thin line with 24px status discs, updated in place (the spinner never restarts on a poll); the newest
 * log line sits under the working step. */
function stepsBlock() {
  const list = h("ol", { class: "ac-steps", "aria-label": "مرحله‌های کار" }), last = h("p", { class: "ac-last", dir: "auto" });
  let keys = null;
  const disc = (st) => (st === "active" ? spinner(16) : STEP_IC[st] ? icon(STEP_IC[st], { size: "sm" }) : null);
  function update(s) {
    const steps = s?.steps || [], k = steps.map((x) => x.key).join();
    if (k !== keys) {
      keys = k; mount(list, steps.map((st) => h("li", { class: "ac-step", "data-k": st.key },
        h("span", { class: "ac-disc", "aria-hidden": "true" }),
        h("span", { class: "ac-step-body" }, h("span", { class: "ac-step-t", text: STEP_TITLE[st.key] || st.key }),
          h("span", { class: "sr-only" })))));
    }
    steps.forEach((st, i) => {
      const li = list.children[i];
      if (li.dataset.s === st.state) return;
      li.dataset.s = st.state; mount(li.firstChild, disc(st.state)); li.querySelector(".sr-only").textContent = `، ${STEP_SR[st.state] || ""}`;
    });
    const cur = s?.busy ? steps.findIndex((x) => x.state === "active" || x.state === "waiting") : -1;
    const line = state.log.at(-1), body = cur < 0 ? null : list.children[cur].lastChild;
    if (!body || !line) { last.remove(); return; }
    if (last.textContent !== line.msg) last.textContent = line.msg;
    last.dataset.l = line.level || "info";
    if (last.parentNode !== body) body.append(last);
  }
  return { el: list, update };
}

/** The current run: whose job, which job, its state and time, the steps, and the way out (cancel + close the browser). */
function runCard() {
  const face = h("span", { class: "ac-face" }), title = h("h3", { class: "ac-run-t" }), who = h("span", { class: "ac-who" });
  const tag = h("span", { class: "ac-tag" }), time = h("span", { class: "ac-time", title: "زمان سپری‌شده", hidden: true },
    icon("clock", { size: "sm" }), h("span", { class: "sr-only", text: "زمان سپری‌شده: " }), h("bdi", { class: "num" }));
  const steps = stepsBlock();
  const stop = button({ label: "لغو و بستن مرورگر", icon: "x", kind: "danger", full: true, cls: "ac-stop", onClick: () => stopJob(stop) });
  const el = h("section", { class: "ac-run", "aria-label": "کار فعلی" },
    h("div", { class: "ac-run-head" }, face, h("div", { class: "ac-run-text" }, title, h("p", { class: "ac-run-sub" }, who, time)), tag),
    steps.el, stop);
  let faceKey = null, tagKey = null;
  el.tick = (s) => { const sec = elapsed(s); time.hidden = sec === null; if (sec !== null) time.lastChild.textContent = clock(sec); };
  el.update = (s) => {
    const u = s.username || "", name = cleanUsername(u);
    const ring = s.state === "running" ? "loading" : s.busy ? "story" : null;   // the ring turns only while it works
    if (`${u}|${ring}` !== faceKey) {
      faceKey = `${u}|${ring}`;
      mount(face, u ? avatar({ u, src: name ? avatarUrl(name) : null, size: 44, ring })
        : h("span", { class: "ac-face-ic" }, icon(s.mode ? "user" : "window")));
      mount(who, name ? h("a", { class: "ac-who-a", href: `#/u/${name}` }, ltr(`@${name}`)) : u ? ltr(u) : null);
    }
    title.textContent = s.state === "idle" ? "پنجرهٔ مرورگر باز است" : JOB_TITLE[s.mode] || "کار";
    if (tagKey !== s.state) { tagKey = s.state; const t = TAG[s.state]; mount(tag, t ? chip({ text: t[0], tone: t[1] }) : null); }
    steps.update(s);
    // A failed run's outcome card has its own «بستن مرورگر»; everywhere else the way out lives here.
    stop.hidden = !(s.busy || (s.browser_open && s.state !== "failed"));
    stop.querySelector("span").textContent = s.busy ? "لغو و بستن مرورگر" : "بستن مرورگر";
    el.tick(s);
  };
  return el;
}

/** need_code: Instagram sent a code (SMS, email or an authenticator app); it is typed into the open window. */
function codeCard() {
  const input = h("input", { class: "input ac-code-in", type: "text", dir: "ltr", name: "code", inputmode: "numeric",
    autocomplete: "one-time-code", maxlength: "8", enterkeyhint: "done", spellcheck: "false" });
  const f = field({ label: "کد ۶ تا ۸ رقمی", input });
  const hint = h("p", { class: "ac-hint", dir: "auto" });
  const go = button({ label: "تأیید کد", kind: "primary", full: true, type: "submit", disabled: true });
  const clean = () => toLatin(input.value).replace(/\D/g, "");
  let sentAt = -1;
  input.addEventListener("input", () => { go.disabled = clean().length < 6; f.setError(""); });
  const el = h("form", { class: "ac-wait", novalidate: true, "aria-label": "کد تأیید", onsubmit: async (e) => {
    e.preventDefault();
    const code = clean();
    if (code.length < 6 || code.length > 8) { f.setError("کد ۶ تا ۸ رقم است؛ کامل بنویس."); input.focus(); return; }
    setBusy(go, true);
    const r = await submitCode(code).catch(() => null);
    if (!r?.ok) {
      setBusy(go, false); input.focus();
      return f.setError(!r ? OFFLINE : typeof r.data?.detail === "string" ? r.data.detail : "کد فرستاده نشد؛ دوباره امتحان کن.");
    }
    sentAt = state.log.length; pokePolling();
  } }, badge("key"), h("h3", { class: "ac-wait-h", text: "کد تأیید را وارد کن" }), hint, f, go);
  el.focusFirst = () => input.focus();
  el.update = (s) => {
    const o = s.outcome || {};
    hint.textContent = o.page_text || "کدی را که اینستاگرام با پیامک، ایمیل یا اپ احراز هویت فرستاده بنویس.";
    // A wrong code keeps the job waiting; wait for a new log line before trusting the outcome again.
    if (sentAt < 0 || state.log.length <= sentAt) return;
    sentAt = -1; setBusy(go, false);
    if (o.kind === "bad_code") { f.setError(`${KIND.bad_code.title}. ${KIND.bad_code.text}`); input.select(); }
  };
  return el;
}

/** need_manual: Instagram asked for something only a person can do in the open window. */
function manualCard() {
  const q = h("div", { class: "ac-q-box" });
  const shot = h("div", { class: "ac-shot-box" });
  let shown, pressedAt = 0;
  const done = button({ label: "انجام دادم", kind: "primary", full: true,
    onClick: () => { pressedAt = Date.now(); setBusy(done, true); pokePolling(); } });
  const el = h("section", { class: "ac-wait", "aria-label": "کار دستی در مرورگر" }, badge("window"),
    h("h3", { class: "ac-wait-h", text: "اینستاگرام یک کار از خودت خواسته" }),
    h("p", { class: "ac-hint", text: "مثلاً «I'm not a robot» یا «این تو بودی؟». صفحه‌اش همین‌جا باز می‌شود؛ همان‌جا انجامش بده، بعد «انجام دادم» را بزن." }),
    q, liveWindow(), shot, done);
  el.update = (s) => {
    const o = s.outcome || {};
    mount(q, quote(o.ig_message));
    // only a picture that was really taken (a crashed page gives false: the shared file then holds an older job's picture)
    if (o.shot !== shown) { shown = o.shot; mount(shot, Number.isFinite(o.shot) ? shotButton(o.shot) : null); }
    if (pressedAt && Date.now() - pressedAt > 1200) { pressedAt = 0; setBusy(done, false); }
  };
  return el;
}

/** The full log of this run: a fixed 240px box, newest at the bottom; it follows new lines unless scrolled up. */
function logBox() {
  const rows = h("ol", { class: "ac-lines" });
  const box = h("div", { class: "ac-log-box", role: "log", tabindex: "0", "aria-label": "گزارش کامل این کار" }, rows);
  const count = h("span", { class: "ac-count num" });
  const copy = button({ label: "کپی گزارش", icon: "copy", size: "sm", cls: "ac-copy", onClick: copyLog });
  const el = h("section", { class: "ac-log", "aria-label": "گزارش" },
    h("div", { class: "ac-sec-head" }, h("h3", { class: "ac-sec-t", text: "گزارش" }), count, copy), box);
  const line = (l) => h("li", { class: "ac-line", "data-l": l.level || "info" }, h("span", { class: "ac-ldot", "aria-hidden": "true" }),
    h("span", { class: "ac-lmsg" }, LEVEL[l.level] ? h("span", { class: "sr-only", text: `${LEVEL[l.level]}: ` }) : null, l.msg),
    h("bdi", { class: "ac-ltime num", dir: "ltr", text: l.t || "" }));
  let shown = 0, run;
  el.update = (s) => {
    if (s.run !== run || state.log.length < shown) { run = s.run; shown = 0; rows.replaceChildren(); }
    const near = box.scrollHeight - box.scrollTop - box.clientHeight < 40, add = state.log.slice(shown);
    rows.append(...add.map(line));
    shown = state.log.length;
    if (add.length && near) box.scrollTop = box.scrollHeight;
    count.textContent = unit(shown, "خط"); copy.disabled = !shown;
  };
  return el;
}

// ---- the detail of one activity ----
const qAct = (id, action) => api(`/api/queue/${id}/${action}`, {}).then((r) => { if (!r?.ok) toast("انجام نشد.", { tone: "danger" }); pokePolling(); });
const pill = (st) => { const [t, tone] = PILL[st] || [st, "idle"]; return h("span", { class: ["act-pill", `is-${tone}`], text: t }); };
const metaRow = (rows) => h("dl", { class: "act-meta" }, rows.filter((r) => r && r[1] != null && r[1] !== "").map(([k, v]) => h("div", { class: "act-meta-i" },
  h("dt", { text: k }), h("dd", {}, v))));
function head(ic, tone, title, user, st, sub) {
  return h("header", { class: "act-d-head" }, h("span", { class: ["act-ic", "act-ic-lg", `is-${tone}`], "aria-hidden": "true" }, icon(ic)),
    h("div", { class: "act-d-text" }, h("h2", { class: "act-d-t", text: title }),
      h("p", { class: "act-d-sub" }, user ? h("a", { class: "act-d-user", href: `#/u/${encodeURIComponent(user)}` }, ltr(`@${user}`)) : null, sub || null)),
    pill(st));
}
const progressBlock = (p) => (p ? h("div", { class: "act-prog" },
  h("div", { class: "act-prog-top" }, h("b", {}, bdi(`${faNum(p.done)} از ${faNum(p.total)} ${p.unit}`)),
    h("span", { text: `${faNum(Math.floor((100 * p.done) / p.total))}٪` + (p.eta ? `، ${p.eta.text}` : "") })),
  h("span", { class: "pj-bar", "aria-hidden": "true" }, h("i", { style: `--p:${Math.min(1, p.done / p.total)}` }))) : null);

/** The job running now (or waiting for him): the old live card, the code / captcha box, the outcome and the live log. */
function liveDetail(pick) {
  const run = runCard(), log = logBox(), wait = h("div", { class: "ac-slot" }), out = h("div", { class: "ac-slot" });
  const from = h("p", { class: "act-from" });
  const el = h("div", { class: "act-d act-d-live" }, run, from, wait, out, log);
  let waitKey = "", outKey = "", card = null;
  el.update = (s) => {
    run.update(s);
    const t = s.queued && (s.queue?.tasks || []).find((x) => x.id === s.queued);
    mount(from, t ? ["بخشی از کار صف: ", h("button", { type: "button", class: "act-link", onclick: () => pick(`t:${t.id}`),
      text: `${TASK_TITLE[t.kind] || t.kind} @${t.username}` })] : null);
    from.hidden = !t;
    const make = s.busy && { need_code: codeCard, need_manual: manualCard }[s.state], wk = make ? `${s.run}:${s.state}` : "";
    if (wk !== waitKey) { waitKey = wk; card = make ? make() : null; mount(wait, card); if (card) { enter(card, "rise"); card.focusFirst?.(); } }
    card?.update(s);
    const ok = !s.busy && FIN.has(s.state) ? `${s.run}:${s.state}:${s.outcome?.kind || ""}` : "";
    if (ok !== outKey) { outKey = ok; mount(out, ok ? outcomeCard(s) : null); }
    log.update(s);
  };
  el.tick = (s) => run.tick(s);
  return el;
}

/** A queue task: how far it is, its steps, what it waits for, the buttons, and the runs it has made so far. */
function taskDetail(t, pick) {
  const p = taskProgress(t);
  const steps = h("ol", { class: "act-steps" }, t.steps.map((s) => h("li", { class: ["act-step", `is-${s.state}`] },
    h("span", { class: "act-step-dot", "aria-hidden": "true" }, s.state === "active" ? spinner(14) : s.state === "done" ? icon("check", { size: "sm" })
      : s.state === "failed" ? icon("x", { size: "sm" }) : null),
    h("span", { class: "act-step-t" }, s.title, s.total != null ? h("bdi", { class: "act-step-n", text: ` ${faNum(s.done)} از ${faNum(s.total)}` }) : null),
    s.note ? h("small", { text: s.note }) : null)));
  const btns = [
    t.state === "waiting" && t.next_at * 1000 > Date.now() ? button({ label: "الان انجام بده", icon: "play", onClick: () => qAct(t.id, "now") }) : null,
    t.state === "waiting" ? button({ label: "توقف", kind: "ghost", onClick: () => qAct(t.id, "pause") }) : null,
    t.state === "paused" ? button({ label: "ادامه", kind: "primary", icon: "play", onClick: () => qAct(t.id, "resume") }) : null,
    ["waiting", "paused"].includes(t.state) ? button({ label: "لغو این کار", kind: "danger", onClick: async () => {
      if (await confirm({ title: "این کار لغو شود؟", text: "آنچه تا الان خوانده شده سر جایش می‌ماند.", cta: "لغو", danger: true })) qAct(t.id, "cancel");
    } }) : null,
  ].filter(Boolean);
  const runs = h("div", { class: "act-runs" }, ...skeleton("line", 2));
  api(`/api/runs?task=${encodeURIComponent(t.id)}&limit=20`).then((r) => {
    const list = r?.data?.items || [];
    mount(runs, list.length ? h("ul", { class: "act-runs-l" }, list.map((x) => h("li", {}, h("button", { type: "button", class: "act-run-row", onclick: () => pick(`r:${x.id}`) },
      pill(runState(x)), h("span", { text: STEP_TITLE[x.step] || TASK_TITLE[t.kind] }), h("span", { class: "act-run-when", text: ago(x.ended_at) }))))) :
      h("p", { class: "act-muted", text: "این کار هنوز نوبتی اجرا نکرده." }));
  }).catch(() => mount(runs, null));
  return h("div", { class: "act-d" },
    head(TASK_IC[t.kind] || "list", (PILL[t.state] || [])[1] || "idle", TASK_TITLE[t.kind] || t.kind, t.username, t.state, "کار صف"),
    metaRow([["ساخته شد", faDateTime(t.created_at)], ["آخرین تغییر", ago(t.updated_at)],
      t.state === "waiting" && t.next_at * 1000 > Date.now() ? ["نوبت بعد", bdi(`ساعت ${faTime(t.next_at)}`)] : null]),
    progressBlock(p), t.note ? h("p", { class: "act-note", dir: "auto" }, icon("info", { size: "sm" }), h("span", { text: t.note })) : null,
    h("h3", { class: "act-sec", text: "مرحله‌ها" }), steps,
    btns.length ? h("div", { class: "act-btns" }, btns) : null,
    h("h3", { class: "act-sec", text: "نوبت‌های این کار" }), runs);
}

/** A saved log, the same look as the live one, with its copy button. */
function staticLog(lines) {
  const copy = button({ label: "کپی گزارش", icon: "copy", size: "sm", cls: "ac-copy", disabled: !lines.length,
    onClick: () => navigator.clipboard.writeText(lines.map((l) => `${l.t}  ${l.msg}`).join("\n").replace(ISOLATES, ""))
      .then(() => toast("گزارش کپی شد", { tone: "ok" }), () => toast("کپی نشد.", { tone: "danger" })) });
  return h("section", { class: "ac-log", "aria-label": "گزارش" },
    h("div", { class: "ac-sec-head" }, h("h3", { class: "ac-sec-t", text: "گزارش کامل" }), h("span", { class: "ac-count num", text: unit(lines.length, "خط") }), copy),
    h("div", { class: "ac-log-box act-log-tall", role: "log", tabindex: "0", "aria-label": "گزارش کامل این کار" },
      h("ol", { class: "ac-lines" }, lines.map((l) => h("li", { class: "ac-line", "data-l": l.level || "info" }, h("span", { class: "ac-ldot", "aria-hidden": "true" }),
        h("span", { class: "ac-lmsg" }, LEVEL[l.level] ? h("span", { class: "sr-only", text: `${LEVEL[l.level]}: ` }) : null, l.msg),
        h("bdi", { class: "ac-ltime num", dir: "ltr", text: l.t || "" }))))));
}

/** A job that ended: when, how long, how it went (Instagram's own sentence kept), its steps and its whole log. */
function runDetail(sum, pick) {
  const st = runState(sum);
  const el = h("div", { class: "act-d" }, head(MODE_IC[sum.mode] || "activity", (PILL[st] || [])[1] || "idle", JOB_TITLE[sum.mode] || sum.mode,
    sum.username, st, sum.queued ? "نوبتی از کار صف" : "کار دستی"), h("div", { class: "act-d-body" }, ...skeleton("line", 4)));
  api(`/api/runs/${encodeURIComponent(sum.id)}`).then((r) => {
    const rec = r?.ok ? r.data : null, body = el.lastChild;
    if (!rec) { mount(body, h("p", { class: "act-muted", text: "جزئیات این کار پیدا نشد." })); return; }
    const k = KIND[rec.kind] || (rec.state === "success" ? KIND.ok : { tone: "bad", icon: "alert", title: rec.kind || "ناموفق", text: "" });
    const task = rec.queued && (state.status?.queue?.tasks || []).find((t) => t.id === rec.queued);
    mount(body,
      metaRow([["شروع", faDateTime(rec.started_at)], ["پایان", faDateTime(rec.ended_at)],
        ["مدت", bdi(clock((rec.ended_at || rec.started_at) - rec.started_at))], rec.step ? ["مرحلهٔ صف", STEP_TITLE[rec.step] || rec.step] : null]),
      task ? h("p", { class: "act-from" }, "بخشی از کار صف: ", h("button", { type: "button", class: "act-link", onclick: () => pick(`t:${task.id}`),
        text: `${TASK_TITLE[task.kind] || task.kind} @${task.username}` })) : null,
      h("div", { class: ["act-out", `is-${k.tone || "idle"}`] }, icon(k.icon || "info"), h("div", {}, h("b", { text: k.title }),
        k.text ? h("p", { text: k.text }) : null, rec.message ? quote(rec.message) : null)),
      runPicture(rec),
      rec.steps?.length ? [h("h3", { class: "act-sec", text: "مرحله‌ها" }), h("ol", { class: "act-steps" }, rec.steps.map((s) => h("li", { class: ["act-step", `is-${s.state}`] },
        h("span", { class: "act-step-dot", "aria-hidden": "true" }, s.state === "done" ? icon("check", { size: "sm" }) : s.state === "failed" ? icon("x", { size: "sm" }) : null),
        h("span", { class: "act-step-t", text: STEP_TITLE[s.key] || s.key }))))] : null,
      staticLog(rec.log || []));
  }).catch(() => mount(el.lastChild, h("p", { class: "act-muted", text: "سرور جواب نداد." })));
  return el;
}

// ---- the page: the strip, then the list (right) and the detail of the chosen activity (left) ----
export function render(params, ctx) {
  let runs = [], filter = "all", sel = null, dead = false, listKey = "", detailKey = "", pane = null;
  const tiles = h("div", { class: "act-tiles-box" }), news = noticeList({ compact: true });
  const seg = h("div", { class: "act-filter" }), listBox = h("div", { class: "act-list-box" });
  const detail = h("div", { class: "act-detail" });
  const back = button({ label: "همهٔ فعالیت‌ها", icon: "chev-r", kind: "ghost", size: "sm", cls: "act-back", onClick: () => { el.classList.remove("is-open"); enter(side, "fade"); } });
  const side = h("aside", { class: "act-side", "aria-label": "فهرست فعالیت‌ها" }, seg, listBox);
  const main = h("section", { class: "act-main", "aria-label": "جزئیات فعالیت" }, back, detail);
  const el = h("div", { class: "act" },
    h("header", { class: "act-head" }, h("h1", { class: "act-title", text: "فعالیت" }),
      h("p", { class: "act-lede", text: "هر کاری که موتور انجام می‌دهد، جدا: آنچه همین حالا اجرا می‌شود، کارهای صف و کارهای تمام‌شده. روی هر کدام بزن تا همهٔ جزئیات و گزارشش را ببینی." })),
    tiles, news, h("div", { class: "act-md" }, side, main));

  const all = () => items(runs);
  function pick(id, byHand = true) {
    sel = id; detailKey = ""; drawList(); drawDetail();
    if (byHand) { el.classList.add("is-open"); enter(main, "fade"); if (matchMedia("(max-width: 959px)").matches) main.scrollIntoView({ block: "start" }); }
  }
  let tileKey = "";
  function drawTiles() {   // only when something it shows changed (a poll every second must not rebuild it)
    const s = state.status || {}, b = s.budget || {};
    const k = JSON.stringify([s.state, s.busy, s.mode, s.username, s.queue?.signed_in, (s.queue?.tasks || []).map((t) => [t.state, t.next_at]),
      b.used?.page, b.limits?.pages_hour, b.cooldown, runs.length, runs[0]?.id, new Date().getDate()]);
    if (k === tileKey) return;
    tileKey = k;
    mount(tiles, overview(runs, (f) => { filter = f; listKey = ""; drawList(); }));
  }
  function drawList() {
    const list = all(), shown = list.filter((it) => inFilter(it, filter));
    if (!sel || !list.some((it) => it.id === sel)) sel = list[0]?.id || null;   // the first one: what runs now, else the queue, else the newest
    const key = JSON.stringify([filter, sel, shown.map((it) => [it.id, it.state, it.progress?.done, Math.floor(it.at / 60000)])]);
    if (key === listKey) return;
    listKey = key;
    mount(seg, segmented({ label: "کدام فعالیت‌ها", value: filter, options: FILTERS.map(([v, l]) => ({ value: v, label: `${l} (${faNum(list.filter((it) => inFilter(it, v)).length)})` })),
      onChange: (v) => { filter = v; listKey = ""; drawList(); } }));
    mount(listBox, pagedList({ key: "activity-items", items: shown, row: (it) => row(it, it.id === sel, pick), cls: "act-list", label: "فعالیت‌ها",
      emptyEl: empty({ icon: "activity", title: "فعالیتی در این دسته نیست", text: filter === "all" ? "یک پروفایل را باز کن و «خواندن از اینستاگرام» را بزن." : "دستهٔ دیگری را انتخاب کن." }) }));
  }
  function drawDetail() {
    const it = all().find((x) => x.id === sel);
    if (!it) { pane = null; detailKey = ""; mount(detail, empty({ icon: "activity", title: "هنوز کاری نیست", text: "وقتی کاری شروع شود، همهٔ جزئیاتش اینجا دیده می‌شود.",
      action: button({ label: "جستجوی یک پروفایل", icon: "search", kind: "primary", onClick: () => ctx.navigate("/search") }) })); return; }
    const key = it.type === "live" ? `live:${it.src.run}` : it.type === "task" ? JSON.stringify([it.id, it.state, it.src.note, it.src.next_at, it.src.steps.map((s) => s.state + s.done)]) : it.id;
    if (key !== detailKey) {
      detailKey = key;
      pane = it.type === "live" ? liveDetail(pick) : it.type === "task" ? taskDetail(it.src, pick) : runDetail(it.src, pick);
      mount(detail, pane);
    }
    if (it.type === "live") pane.update(state.status);
  }
  async function loadRuns() {
    const r = await api("/api/runs?limit=300").catch(() => null);
    if (dead) return;
    runs = r?.ok ? r.data.items || [] : runs;
    if (sel === "now" && !isLive(state.status) && runs[0]) sel = `r:${runs[0].id}`;   // the run that just ended: keep showing it
    listKey = ""; drawTiles(); drawList(); drawDetail();
  }
  const offs = [
    subscribe("status", () => { drawTiles(); drawList(); drawDetail(); }),
    subscribe("job-end", () => loadRuns()),
  ];
  const timer = setInterval(() => { const s = state.status; if (s?.busy && pane?.tick) pane.tick(s); }, 1000);
  loadRuns();
  return { el, update: () => { drawList(); drawDetail(); }, destroy() { dead = true; offs.forEach((off) => off()); clearInterval(timer); news.destroy(); } };
}


/** The login page's compact step list: the steps, then the result line when the run ends. Returns {el, destroy}. */
export function renderInto(target) {
  const steps = stepsBlock(), sum = h("div", { class: "ac-sum" }), box = h("div", { class: "ac ac-compact" }, steps.el, sum);
  let key = "";
  const sync = () => {
    const s = state.status; if (!s) return;
    steps.update(s);
    const k = !s.busy && FIN.has(s.state) ? `${s.run}:${s.state}` : "";
    if (k !== key) { key = k; mount(sum, k ? resultSummary(s) : null); }
  };
  mount(target, box);
  const off = subscribe("status", sync); sync();
  return { el: box, destroy: off };
}
