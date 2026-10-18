import { ReactNode } from "react";

import { Button, Field, Select } from "../../../../components/ui";
import { clone, desc, fa, label } from "../api";
import type { Catalog, Issue, Item, Motion, SceneDoc, Track } from "../types";
import { DraftInput, DraftNumber, DraftRange, DraftTextArea, Details, Grid2, Hr } from "./fields";
import { CAT_FA, EXPRS, MOVES_FA, OVT, type Sel, byId, docDuration, sortTrack, speechSeconds, trackName } from "./model";

/**
 * بازرس: ویرایشِ قطعهٔ انتخاب‌شدهٔ خطِ زمان (حرکت، گفتار، دوربین، چهره، نگاه، نوشته).
 * هر تغییر از راهِ `changeItem` می‌رود که شیار را دوباره مرتب و همان قطعه را انتخاب نگه می‌دارد.
 */
export type ItemEditor = {
  cat: Catalog;
  doc: SceneDoc;
  issues: Issue[];
  sel: NonNullable<Sel>;
  setSel: (s: Sel) => void;
  change: (fn: (d: SceneDoc) => void) => void;
  changeItem: (track: Track, idx: number, fn: (it: Item, d: SceneDoc) => void) => void;
};

function Opt({ list }: { list: [string, string][] }) {
  return (
    <>
      {list.map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </>
  );
}

export default function Inspector({ ed }: { ed: ItemEditor }) {
  const { cat, doc, sel, issues } = ed;
  const tr = sel.track;
  const it = doc[tr][sel.idx];
  if (!it) return null;
  const total = docDuration(doc);
  const set = (fn: (it: Item, d: SceneDoc) => void) => ed.changeItem(tr, sel.idx, fn);
  const env = byId(cat, "environment", doc.environment.id);

  const actorOpts = (allowNone = false): [string, string][] => {
    const list: [string, string][] = doc.actors.map((a): [string, string] => [a.id, `${a.id} — ${label(byId(cat, "character", a.character))}`]);
    if (allowNone) list.unshift(["", "راوی (بی‌بازیگر)"]);
    return list;
  };

  const startField = (
    <Field label="شروع (ث)">
      <DraftNumber value={it.start} step={0.05} min={0} onCommit={(v) => set((x) => void (x.start = Math.max(0, v ?? 0)))} />
    </Field>
  );
  const durationField = (minDur: number, hint?: string) => (
    <Field label="مدت (ث)" hint={hint}>
      <DraftNumber
        value={it.duration}
        step={0.05}
        min={minDur}
        onCommit={(v) => set((x) => void (x.duration = Math.max(minDur, v ?? minDur)))}
      />
    </Field>
  );

  const setParam = (k: string, v: unknown) =>
    set((x) => {
      x.params = x.params || {};
      if (v === "" || v == null) delete x.params[k];
      else x.params[k] = v;
    });

  let body: ReactNode = null;

  if (tr === "actions") {
    const groups = new Map<string, Motion[]>();
    cat.motion.forEach((m) => groups.set(m.category, [...(groups.get(m.category) || []), m]));
    const m = byId(cat, "motion", it.motion);
    body = (
      <>
        <Field label="حرکت" hint={m ? desc(m) : undefined}>
          <Select
            value={it.motion || ""}
            onChange={(e) =>
              set((x) => {
                x.motion = e.target.value;
                const mm = byId(cat, "motion", e.target.value);
                if (mm) x.duration = mm.duration.default;
                x.params = x.params || {};
              })
            }
          >
            {[...groups.entries()].map(([g, list]) => (
              <optgroup key={g} label={CAT_FA[g] || g}>
                <Opt list={list.map((x): [string, string] => [x.id, label(x)])} />
              </optgroup>
            ))}
          </Select>
        </Field>
        <Field label="بازیگر">
          <Select value={it.actor || ""} onChange={(e) => set((x) => void (x.actor = e.target.value || null))}>
            <Opt list={actorOpts()} />
          </Select>
        </Field>
        <Grid2>
          {startField}
          {durationField(0.2, m ? `مجاز: ${fa(m.duration.min)} تا ${fa(m.duration.max)}` : undefined)}
        </Grid2>
        {m?.params &&
          Object.entries(m.params).map(([k, s]) => {
            const cur = (it.params || {})[k] != null ? (it.params || {})[k] : s.default;
            const lbl = s.label || k;
            if (s.type === "product_ref")
              return (
                <Field key={k} label={lbl}>
                  <Select value={String(cur ?? "")} onChange={(e) => setParam(k, e.target.value)}>
                    <Opt list={doc.products.map((p): [string, string] => [p.id, `${p.id} — ${p.name || p.asset}`])} />
                  </Select>
                </Field>
              );
            if (s.type === "surface_ref")
              return (
                <Field key={k} label={lbl}>
                  <Select value={String(cur ?? "")} onChange={(e) => setParam(k, e.target.value)}>
                    <option value="">جای قبلی</option>
                    <Opt list={Object.keys(env?.surfaces || {}).map((x): [string, string] => [x, x])} />
                  </Select>
                </Field>
              );
            if (s.type === "enum")
              return (
                <Field key={k} label={lbl}>
                  <Select value={String(cur ?? "")} onChange={(e) => setParam(k, e.target.value)}>
                    <option value="">—</option>
                    <Opt list={(s.values || []).map((v): [string, string] => [String(v), v === "R" ? "راست" : v === "L" ? "چپ" : String(v)])} />
                  </Select>
                </Field>
              );
            if (s.type === "bool")
              return (
                <label key={k} className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
                  <input type="checkbox" checked={Boolean(cur)} onChange={(e) => setParam(k, e.target.checked)} />
                  {lbl}
                </label>
              );
            return (
              <Field key={k} label={lbl}>
                <DraftInput value={cur == null ? "" : String(cur)} onCommit={(v) => setParam(k, v)} />
              </Field>
            );
          })}
      </>
    );
  } else if (tr === "speech") {
    const text = it.text || "";
    body = (
      <>
        <Field label="متن (فارسی)" hint={`${fa(text.length)} نویسه ≈ ${fa(speechSeconds(text).toFixed(1))} ثانیه گفتار`}>
          <DraftTextArea
            rows={3}
            value={text}
            onCommit={(v) =>
              set((x) => {
                x.text = v;
                x.duration = speechSeconds(v);
              })
            }
          />
        </Field>
        <Field label="گوینده">
          <Select value={it.actor || ""} onChange={(e) => set((x) => void (x.actor = e.target.value || null))}>
            <Opt list={actorOpts(true)} />
          </Select>
        </Field>
        <Grid2>
          {startField}
          <Field label="صدا">
            <Select value={it.voice || ""} onChange={(e) => set((x) => void (x.voice = e.target.value))}>
              <Opt list={cat.voice.map((v): [string, string] => [v.id, label(v)])} />
            </Select>
          </Field>
        </Grid2>
        <Field label="حس/لحن (اختیاری)">
          <DraftInput value={it.style || ""} onCommit={(v) => set((x) => void (x.style = v))} placeholder="گرم، پرانرژی…" />
        </Field>
      </>
    );
  } else if (tr === "shots") {
    const s = byId(cat, "shot", it.shot);
    const subjects: [string, string][] = [
      ...doc.actors.map((a): [string, string] => [a.id, `بازیگر: ${a.id}`]),
      ...doc.products.map((p): [string, string] => [p.id, `محصول: ${p.name || p.id}`]),
    ];
    const pr = it.params || {};
    const lens = (k: "lens" | "fstop" | "height") => (
      <DraftNumber
        value={typeof pr[k] === "number" ? (pr[k] as number) : null}
        step={k === "lens" ? 1 : k === "fstop" ? 0.1 : 0.05}
        placeholder={s ? String(s.framing[k]) : ""}
        onCommit={(v) => setParam(k, v)}
      />
    );
    body = (
      <>
        <Field label="نما" hint={s ? desc(s) : undefined}>
          <Select
            value={it.shot || ""}
            onChange={(e) =>
              set((x) => {
                x.shot = e.target.value;
                const ss = byId(cat, "shot", e.target.value);
                if (ss && !ss.moves.includes(x.move || "")) x.move = ss.moves[0];
              })
            }
          >
            <Opt list={cat.shot.map((x): [string, string] => [x.id, label(x)])} />
          </Select>
        </Field>
        <Field label="سوژه">
          <Select value={it.subject || ""} onChange={(e) => set((x) => void (x.subject = e.target.value))}>
            <Opt list={subjects} />
          </Select>
        </Field>
        <Field label="حرکتِ دوربین">
          <Select value={it.move || "static"} onChange={(e) => set((x) => void (x.move = e.target.value))}>
            <Opt list={(s ? s.moves : ["static"]).map((x): [string, string] => [x, MOVES_FA[x] || x])} />
          </Select>
        </Field>
        <Grid2>
          {startField}
          {durationField(0.3)}
        </Grid2>
        <Details summary="تنظیمِ پیشرفتهٔ لنز">
          <div className="grid grid-cols-3 gap-2">
            <Field label="لنز (mm)">{lens("lens")}</Field>
            <Field label="دیافراگم f">{lens("fstop")}</Field>
            <Field label="ارتفاعِ قاب (m)">{lens("height")}</Field>
          </div>
        </Details>
      </>
    );
  } else if (tr === "expressions") {
    body = (
      <>
        <Field label="حالت">
          <Select value={it.expression || "smile"} onChange={(e) => set((x) => void (x.expression = e.target.value))}>
            <Opt list={Object.entries(EXPRS)} />
          </Select>
        </Field>
        <Field label="بازیگر">
          <Select value={it.actor || ""} onChange={(e) => set((x) => void (x.actor = e.target.value || null))}>
            <Opt list={actorOpts()} />
          </Select>
        </Field>
        <Field label={`شدت: ${fa(it.intensity ?? 0.7)}`}>
          <DraftRange value={it.intensity ?? 0.7} min={0.1} max={1} step={0.05} onCommit={(v) => set((x) => void (x.intensity = v))} />
        </Field>
        <Grid2>
          {startField}
          {durationField(0.2)}
        </Grid2>
      </>
    );
  } else if (tr === "gaze") {
    const targets: [string, string][] = [
      ["camera", "دوربین (تماسِ چشمی)"],
      ["forward", "روبه‌رو"],
      ...doc.products.map((p): [string, string] => [`product:${p.id}`, `محصول: ${p.name || p.id}`]),
      ...doc.actors.map((a): [string, string] => [`actor:${a.id}`, `بازیگر: ${a.id}`]),
    ];
    body = (
      <>
        <Field label="نگاه به">
          <Select value={it.target || "camera"} onChange={(e) => set((x) => void (x.target = e.target.value))}>
            <Opt list={targets} />
          </Select>
        </Field>
        <Field label="بازیگر">
          <Select value={it.actor || ""} onChange={(e) => set((x) => void (x.actor = e.target.value || null))}>
            <Opt list={actorOpts()} />
          </Select>
        </Field>
        <Grid2>
          {startField}
          {durationField(0.2)}
        </Grid2>
      </>
    );
  } else if (tr === "overlays") {
    body = (
      <>
        <Field label="نوع">
          <Select value={it.type || "title"} onChange={(e) => set((x) => void (x.type = e.target.value))}>
            <Opt list={Object.entries(OVT)} />
          </Select>
        </Field>
        <Field label="متن">
          <DraftInput value={it.text || ""} onCommit={(v) => set((x) => void (x.text = v))} />
        </Field>
        <Field label="جا">
          <Select value={it.position || ""} onChange={(e) => set((x) => void (x.position = e.target.value || undefined))}>
            <Opt
              list={[
                ["", "پیش‌فرض"],
                ["top", "بالا"],
                ["center", "وسط"],
                ["bottom", "پایین"],
              ]}
            />
          </Select>
        </Field>
        <Grid2>
          {startField}
          {durationField(0.3)}
        </Grid2>
      </>
    );
  }

  const own = issues.filter((i) => i.path === `${tr}[${sel.idx}]`);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-bold" style={{ color: "var(--text)" }}>
          {trackName(tr)}
        </h3>
        <span className="flex gap-1">
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              ed.change((d) => {
                const c = clone(it);
                delete c.id;
                c.start = Math.min(total - 0.3, it.start + (it.duration || 1));
                d[tr].push(c);
                sortTrack(d[tr]);
                ed.setSel({ track: tr, idx: d[tr].indexOf(c) });
              })
            }
          >
            تکثیر
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={() => {
              ed.change((d) => void d[tr].splice(sel.idx, 1));
              ed.setSel(null);
            }}
          >
            حذف
          </Button>
          <Button variant="ghost" size="sm" onClick={() => ed.setSel(null)} title="بستن">
            ✕
          </Button>
        </span>
      </div>
      <Hr />
      {body}
      {own.length > 0 && (
        <ul className="u3d-issues">
          {own.map((i, k) => (
            <li key={k} className={i.level}>
              {i.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
