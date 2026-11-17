import { useCallback, useEffect, useMemo, useState } from "react";

import { Alert, Badge, Button, ErrorBox, Input, Select, Spinner, TextArea, fa } from "../../components/ui";
import { PersonaData, PersonaDraft, PersonaInfo, bcApi } from "./api";
import { useBrandChar } from "./BrandCharLayout";
import { ListEditor, Section, fmtDate, useNotice } from "./common";

const KINDS = [
  { key: "caption", fa: "کپشن" },
  { key: "sales", fa: "ایجنتِ فروش و صندوقِ پیام" },
  { key: "ideas", fa: "بانکِ ایده" },
  { key: "thumbnail", fa: "عنوانِ تامنیل" },
  { key: "motion", fa: "متنِ موشن" },
  { key: "site", fa: "متنِ سایت" },
];

export default function PersonaPage() {
  const { id, reload } = useBrandChar();
  const [info, setInfo] = useState<PersonaInfo | null>(null);
  const [draft, setDraft] = useState<PersonaData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [brief, setBrief] = useState("");
  const [useAi, setUseAi] = useState(true);
  const [wiz, setWiz] = useState<PersonaDraft | null>(null);
  const [kind, setKind] = useState("caption");
  const [prompt, setPrompt] = useState<string>("");
  const [versions, setVersions] = useState<{ version: number; source: string; note: string; created_at: string; name: string }[]>([]);
  const n = useNotice();

  const load = useCallback(async () => {
    try {
      const p = await bcApi.persona(id);
      setInfo(p);
      setDraft(p.data);
      setLoadError(null);
      setVersions(await bcApi.personaVersions(id));
    } catch (e) {
      setLoadError(String((e as Error).message || e));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = useMemo(() => !!info && !!draft && JSON.stringify(info.data) !== JSON.stringify(draft), [info, draft]);
  const locked = !!info?.locked;

  useEffect(() => {
    if (!info?.exists) {
      setPrompt("");
      return;
    }
    bcApi.personaPrompt(id, kind).then((r) => setPrompt(r.text)).catch(() => setPrompt(""));
  }, [id, kind, info?.version, info?.updated_at, info?.exists]);

  if (loadError) return <ErrorBox message={loadError} />;
  if (!info || !draft) return <div className="bc-center"><Spinner /></div>;

  const set = <K extends keyof PersonaData>(k: K, v: PersonaData[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const L = info.limits;
  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    try {
      await fn();
    } catch (e) {
      n.fail(e);
    } finally {
      setBusy(null);
    }
  };

  const save = () =>
    run("save", async () => {
      const p = await bcApi.savePersona(id, draft, wiz && JSON.stringify(wiz.persona) === JSON.stringify(draft) ? (wiz.origin === "ai" ? "ai" : wiz.origin === "facts" ? "facts" : "rule") : "manual");
      setInfo((cur) => (cur ? { ...cur, ...p } : cur));
      setDraft(p.data);
      n.ok("شخصیتِ گفتار ذخیره شد و از این به بعد در تولیدکننده‌های متنِ برند به کار می‌رود.");
      await reload();
      await load();
    });

  const wizard = () =>
    run("wizard", async () => {
      const r = await bcApi.personaDraft(id, brief, useAi);
      setWiz(r);
      setDraft(r.persona);
      const skipped = r.brief?.given && !r.brief.used_by_ai;
      const briefNote = !skipped ? "" : r.brief?.applied?.length ? ` لحنِ توضیحِ شما اعمال شد (${r.brief.applied.join("، ")}).` : " توضیحِ شما استفاده نشد (هوش مصنوعی در دسترس نیست).";
      n.ok((r.ai.used ? "پیش‌نویس با هوش مصنوعی ساخته شد؛ مرور کنید و «ذخیره» را بزنید." : "پیش‌نویسِ قاعده‌محور ساخته شد؛ مرور کنید و «ذخیره» را بزنید.") + briefNote);
    });

  const pickArch = (key: string, asSecond: boolean) => {
    if (locked) return;
    if (asSecond) {
      set("secondary", draft.secondary === key ? "" : key);
      return;
    }
    set("archetype", key);
    if (draft.secondary === key) set("secondary", "");
  };
  const toneFromArch = () => {
    const a = info.archetypes.find((x) => x.key === draft.archetype);
    if (a) set("tone", { ...a.tone });
  };

  return (
    <div className="bc-root" data-testid="persona-page">
      {n.error ? <ErrorBox message={n.error} /> : null}
      {n.notice ? <Alert tone="ok">{n.notice}</Alert> : null}

      <Section
        title="جادوگرِ شخصیت"
        hint="از پروفایلِ فروشگاه (و واقعیت‌های تأییدشدهٔ برند، اگر سندش هست) یک پیش‌نویسِ لحن می‌سازد. هیچ قیمت، آمار یا ادعایی نمی‌سازد. اگر هوش مصنوعی در دسترس نباشد، پیش‌نویسِ قاعده‌محور می‌دهد."
        action={<Badge tone={info.exists ? "ok" : "neutral"}>{info.exists ? `کامل‌بودن: ${fa(info.score.done)} از ${fa(info.score.total)}` : "هنوز ذخیره نشده"}</Badge>}
      >
        <label className="bc-label">
          توضیحِ دلخواه برای جادوگر (اختیاری)
          <TextArea rows={2} value={brief} maxLength={400} placeholder="مثلاً: مثلِ یک همکارِ مربی حرف بزند، کوتاه و صمیمی" onChange={(e) => setBrief(e.target.value)} />
        </label>
        <div className="bc-row">
          <label className="bc-row" style={{ gap: 6 }}>
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} /> با هوش مصنوعی هم بهتر شود
          </label>
          <Button type="button" onClick={() => void wizard()} disabled={busy !== null || locked}>
            {busy === "wizard" ? <Spinner size={14} /> : null} پیش‌نویس بساز
          </Button>
          {locked ? <span className="bc-muted">برای تغییر، اول قفل را باز کنید.</span> : null}
        </div>
        {wiz ? (
          <div className="bc-note" data-testid="wizard-result">
            <b>{wiz.origin === "facts" ? "از واقعیت‌های تأییدشدهٔ برند" : wiz.origin === "ai" ? "با کمکِ هوش مصنوعی" : "قاعده‌محور"}</b>
            {wiz.ai.used ? ` (${wiz.ai.label || "هوش مصنوعی"})` : wiz.ai.reason ? ` — هوش مصنوعی: ${wiz.ai.reason}` : ""}
            <ul className="bc-sources">
              {wiz.notes.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
            {wiz.sources.length ? (
              <details>
                <summary>منبعِ هر واقعیت ({fa(wiz.sources.length)})</summary>
                <ul className="bc-sources">
                  {wiz.sources.map((s) => (
                    <li key={s.fact}>
                      {s.fact} <span className="bc-muted">[{s.source}]</span>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}
      </Section>

      <Section title="هویت" hint="نام و یک توصیفِ کوتاه؛ همین‌ها در سلام، برگهٔ مدل و پرامپتِ تولیدکننده‌ها می‌آید.">
        <div className="bc-fields">
          <label className="bc-label">
            نامِ شخصیت
            <Input value={draft.name} maxLength={L.name} disabled={locked} onChange={(e) => set("name", e.target.value)} />
          </label>
          <label className="bc-label">
            شعارِ برند (اختیاری)
            <Input value={draft.tagline} maxLength={L.tagline} disabled={locked} onChange={(e) => set("tagline", e.target.value)} />
          </label>
          <label className="bc-label wide">
            توصیفِ کوتاهِ شخصیت
            <TextArea rows={2} value={draft.summary} maxLength={L.summary} disabled={locked} onChange={(e) => set("summary", e.target.value)} />
          </label>
          <label className="bc-label wide">
            مخاطب
            <Input value={draft.audience} maxLength={L.audience} disabled={locked} onChange={(e) => set("audience", e.target.value)} />
          </label>
        </div>
      </Section>

      <Section title="کهن‌الگو" hint="یکی از ۱۲ شخصیتِ پایه را به‌عنوانِ اصلی انتخاب کنید؛ با «دومی» می‌توانید رنگِ دیگری هم اضافه کنید.">
        <div className="bc-arch" role="group" aria-label="کهن‌الگو">
          {info.archetypes.map((a) => (
            <button key={a.key} type="button" aria-pressed={draft.archetype === a.key} className={draft.secondary === a.key ? "is-second" : ""} disabled={locked} onClick={() => pickArch(a.key, false)} onContextMenu={(e) => { e.preventDefault(); pickArch(a.key, true); }}>
              <b>
                {a.fa} {draft.secondary === a.key ? "· دوم" : ""}
              </b>
              <span>{a.about}</span>
              <span className="bc-row" style={{ gap: 4 }}>
                <span className="bc-chip" role="button" tabIndex={0} onClick={(e) => { e.stopPropagation(); pickArch(a.key, true); }} onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); pickArch(a.key, true); } }}>
                  {draft.secondary === a.key ? "برداشتنِ «دوم»" : "به‌عنوانِ دوم"}
                </span>
              </span>
            </button>
          ))}
        </div>
        <p className="bc-muted">{info.archetypes.find((x) => x.key === draft.archetype)?.about}</p>
      </Section>

      <Section title="لحن" hint="پنج لغزنده؛ مقدارهای دور از وسط در پرامپتِ تولیدکننده‌ها به کلمه تبدیل می‌شود." action={<Button type="button" variant="secondary" size="sm" disabled={locked} onClick={toneFromArch}>لحن را از کهن‌الگو بگیر</Button>}>
        {info.sliders.map((s) => (
          <div className="bc-slider" key={s.key}>
            <span className="lo">{s.low}</span>
            <input type="range" min={0} max={100} step={5} value={draft.tone[s.key] ?? 50} disabled={locked} aria-label={s.label} onChange={(e) => set("tone", { ...draft.tone, [s.key]: Number(e.target.value) })} />
            <span className="hi">{s.high}</span>
            <b>
              {s.label}: {fa(draft.tone[s.key] ?? 50)}
            </b>
          </div>
        ))}
      </Section>

      <div className="bc-grid two">
        <Section title="ارزش‌ها" hint={`تا ${fa(L.values)} مورد`}>
          <ListEditor items={draft.values} max={L.values} maxLen={L.value_len} disabled={locked} placeholder="مثلاً: شفافیت" onChange={(v) => set("values", v)} />
        </Section>
        <Section title="شعار و جملهٔ امضا" hint="جمله‌های دارایِ قیمت، آمار یا وعده خودکار حذف می‌شوند.">
          <ListEditor items={draft.catchphrases} max={L.catch} maxLen={L.catch_len} disabled={locked} placeholder="مثلاً: با ما شروع کن" onChange={(v) => set("catchphrases", v)} />
        </Section>
        <Section title="واژه‌هایی که بگو">
          <ListEditor items={draft.do_words} max={L.words} maxLen={L.word_len} disabled={locked} placeholder="واژه یا عبارت" onChange={(v) => set("do_words", v)} />
        </Section>
        <Section title="واژه‌هایی که نگو">
          <ListEditor items={draft.dont_words} max={L.words} maxLen={L.word_len} disabled={locked} placeholder="واژه یا عبارت" onChange={(v) => set("dont_words", v)} />
        </Section>
      </div>

      <Section title="شیوهٔ گفتن">
        <div className="bc-fields">
          <label className="bc-label">
            مخاطب‌گیری
            <Select value={draft.address} disabled={locked} onChange={(e) => set("address", e.target.value)}>
              {info.address.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.fa}
                </option>
              ))}
            </Select>
          </label>
          <label className="bc-label">
            ایموجی
            <Select value={draft.emoji} disabled={locked} onChange={(e) => set("emoji", e.target.value)}>
              {info.emoji_policies.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.fa}
                </option>
              ))}
            </Select>
          </label>
          <label className="bc-label wide">
            سلام (اولین پیام)
            <Input value={draft.greeting} maxLength={L.greeting} disabled={locked} onChange={(e) => set("greeting", e.target.value)} />
          </label>
          <label className="bc-label wide">
            خداحافظی
            <Input value={draft.signoff} maxLength={L.signoff} disabled={locked} onChange={(e) => set("signoff", e.target.value)} />
          </label>
        </div>
      </Section>

      <Section
        title="جمله‌های نمونه"
        hint={`تا ${fa(L.samples)} جمله برای موقعیت‌های مختلف؛ در قالب‌های پست و پاسخ‌ها نمونهٔ لحن‌اند.`}
        action={
          <Button type="button" variant="secondary" size="sm" disabled={locked || draft.sample_lines.length >= L.samples} onClick={() => set("sample_lines", [...draft.sample_lines, { situation: "explain", text: "" }])}>
            جملهٔ تازه
          </Button>
        }
      >
        {draft.sample_lines.map((row, i) => (
          <div className="bc-row" key={i} style={{ flexWrap: "nowrap" }}>
            <Select style={{ maxWidth: 170 }} value={row.situation} disabled={locked} aria-label="موقعیت" onChange={(e) => set("sample_lines", draft.sample_lines.map((r, j) => (j === i ? { ...r, situation: e.target.value } : r)))}>
              {info.situations.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.fa}
                </option>
              ))}
            </Select>
            <Input style={{ flex: 1, minWidth: 0 }} value={row.text} maxLength={L.sample_len} disabled={locked} aria-label="جمله" onChange={(e) => set("sample_lines", draft.sample_lines.map((r, j) => (j === i ? { ...r, text: e.target.value } : r)))} />
            <Button type="button" variant="ghost" size="sm" disabled={locked} aria-label="حذفِ جمله" onClick={() => set("sample_lines", draft.sample_lines.filter((_, j) => j !== i))}>
              ×
            </Button>
          </div>
        ))}
        {!draft.sample_lines.length ? <span className="bc-muted">هنوز جمله‌ای نیست.</span> : null}
      </Section>

      <Section title="صدا" hint="گوینده و سرعتِ پیش‌فرضِ این شخصیت (در استودیوی صدا و موشن).">
        <div className="bc-fields">
          <label className="bc-label">
            گوینده
            {info.voices.length ? (
              <Select value={draft.voice.voice_id} disabled={locked} onChange={(e) => set("voice", { ...draft.voice, voice_id: e.target.value })} data-testid="voice-select">
                <option value="">پیش‌فرضِ فروشگاه</option>
                {Array.from(new Set(info.voices.map((v) => v.group || "صداها"))).map((g) => (
                  <optgroup key={g} label={g}>
                    {info.voices
                      .filter((v) => (v.group || "صداها") === g)
                      .map((v) => (
                        <option key={String(v.id)} value={String(v.id)} disabled={v.available === false && v.id !== draft.voice.voice_id}>
                          {v.name}
                          {v.available === false ? " (الان آماده نیست)" : ""}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </Select>
            ) : (
              <Input value={draft.voice.voice_id} maxLength={60} placeholder="شناسهٔ گوینده (اختیاری)" disabled={locked} onChange={(e) => set("voice", { ...draft.voice, voice_id: e.target.value })} />
            )}
          </label>
          <label className="bc-label">
            جنسیتِ صدا
            <Select value={draft.voice.gender} disabled={locked} onChange={(e) => set("voice", { ...draft.voice, gender: e.target.value })}>
              <option value="">فرقی ندارد</option>
              <option value="female">زنانه</option>
              <option value="male">مردانه</option>
            </Select>
          </label>
          <label className="bc-label wide">
            سرعتِ گفتار: {fa(draft.voice.speed)}
            <input type="range" min={0.6} max={1.6} step={0.05} value={draft.voice.speed} disabled={locked} onChange={(e) => set("voice", { ...draft.voice, speed: Number(e.target.value) })} style={{ accentColor: "var(--brand)" }} />
          </label>
        </div>
      </Section>

      <Section title="چه چیزی به تولیدکننده‌ها می‌رسد؟" hint="همین بلوکِ کوتاه (حداکثر ۹۰۰ نویسه) به پرامپتِ هر تولیدکننده‌ای که به نامِ برند می‌نویسد اضافه می‌شود. فقط لحن است؛ هیچ واقعیتِ تازه‌ای نمی‌سازد.">
        <div className="bc-chips" role="group" aria-label="تولیدکننده">
          {KINDS.map((k) => (
            <button key={k.key} type="button" className="bc-chip" aria-pressed={kind === k.key} onClick={() => setKind(k.key)}>
              {k.fa}
            </button>
          ))}
        </div>
        {info.exists ? <pre className="bc-pre" data-testid="persona-prompt">{prompt || "…"}</pre> : <span className="bc-muted">اول شخصیت را ذخیره کنید.</span>}
      </Section>

      <Section title="ذخیره و نسخه" hint="«تأیید» نسخه را قفل می‌کند و یک عکسِ فوری می‌گیرد؛ تا باز کردنِ قفل چیزی عوض نمی‌شود.">
        <div className="bc-row">
          <Button type="button" onClick={() => void save()} disabled={busy !== null || locked || !draft.name.trim()}>
            {busy === "save" ? <Spinner size={14} /> : null} ذخیره
          </Button>
          {locked ? (
            <Button type="button" variant="secondary" onClick={() => void run("unlock", async () => { const p = await bcApi.personaUnlock(id); setInfo((c) => (c ? { ...c, ...p } : c)); await reload(); })} disabled={busy !== null}>
              بازکردنِ قفل
            </Button>
          ) : (
            <Button type="button" variant="secondary" onClick={() => void run("lock", async () => { if (dirty) await bcApi.savePersona(id, draft); const p = await bcApi.personaLock(id); setInfo((c) => (c ? { ...c, ...p } : c)); n.ok(`شخصیتِ گفتار تأیید شد (نسخهٔ ${fa(p.version)}).`); await reload(); await load(); })} disabled={busy !== null || !info.exists && !draft.name.trim()}>
              تأیید و قفل
            </Button>
          )}
          {info.exists ? (
            <label className="bc-row" style={{ gap: 6 }}>
              <input type="checkbox" checked={info.active} onChange={(e) => void run("active", async () => { const p = await bcApi.personaActive(id, e.target.checked); setInfo((c) => (c ? { ...c, ...p } : c)); await reload(); })} /> در تولیدکننده‌ها به کار برود
            </label>
          ) : null}
          {dirty ? <Badge tone="warn">ذخیره‌نشده</Badge> : null}
          {info.locked ? <Badge tone="ok">نسخهٔ {fa(info.version)} · {fmtDate(info.locked_at)}</Badge> : null}
        </div>
        {versions.length ? (
          <div className="bc-list">
            <span className="bc-sub">نسخه‌های تأییدشده</span>
            {versions.map((v) => (
              <div className="bc-row" key={v.version}>
                <Badge tone="info">v{fa(v.version)}</Badge>
                <span>{v.name || "—"}</span>
                <span className="bc-muted">{fmtDate(v.created_at)}</span>
                <Button type="button" variant="ghost" size="sm" disabled={locked || busy !== null} onClick={() => void run("restore", async () => { const p = await bcApi.personaRestore(id, v.version); setInfo((c) => (c ? { ...c, ...p } : c)); setDraft(p.data); n.ok("نسخه بازگردانده شد؛ برای تأیید «تأیید و قفل» را بزنید."); await load(); })}>
                  بازگرداندن
                </Button>
              </div>
            ))}
          </div>
        ) : null}
      </Section>
    </div>
  );
}
