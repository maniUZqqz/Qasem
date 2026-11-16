import { useMemo, useState } from "react";

import Icon from "../../../components/Icon";
import { Input, fa } from "../../../components/ui";
import { Catalog, StyleDef, thumbUrl } from "./api";
import { ownerLabel, styleMatches } from "./ownerNames";

function Swatch({ s }: { s: StyleDef }) {
  const p = s.palette;
  return (
    <div className="flex h-full w-full flex-col justify-end p-3" style={{ background: `linear-gradient(150deg, ${p.bg}, ${p.bg2})`, color: p.ink }}>
      <div className="text-lg font-extrabold">{s.name_fa}</div>
      <div className="mt-2 flex gap-1">
        {[p.accent, p.accent2, p.accent3].map((c) => (
          <span key={c} className="h-3 w-6 rounded-full" style={{ background: c }} />
        ))}
      </div>
    </div>
  );
}

function Card({ s, active, onPick }: { s: StyleDef; active: boolean; onPick: () => void }) {
  const [broken, setBroken] = useState(false);
  return (
    <button
      type="button"
      onClick={onPick}
      className="group overflow-hidden rounded-xl text-start transition"
      style={{
        background: "var(--surface)",
        border: `2px solid ${active ? "var(--brand)" : "var(--line)"}`,
        boxShadow: active ? "0 0 0 3px color-mix(in srgb, var(--brand) 22%, transparent)" : undefined,
      }}
      aria-pressed={active}
    >
      <div className="relative w-full overflow-hidden" style={{ aspectRatio: "4 / 5" }}>
        {broken ? (
          <Swatch s={s} />
        ) : (
          <img src={s.thumb_url || thumbUrl(s.id)} alt={s.name_fa} loading="lazy" className="h-full w-full object-cover" onError={() => setBroken(true)} />
        )}
        {s.custom ? (
          <span className="absolute right-2 top-2 rounded-full px-2 py-0.5 text-[11px] font-bold" style={{ background: "var(--brand)", color: "#fff" }}>
            {s.scope === "global" ? "همگانی" : "سبکِ من"}
          </span>
        ) : null}
        {active && (
          <span className="absolute left-2 top-2 flex h-6 w-6 items-center justify-center rounded-full" style={{ background: "var(--brand)", color: "#fff" }}>
            <Icon name="check" size={14} />
          </span>
        )}
      </div>
      <div className="p-2.5">
        <div className="text-sm font-bold" style={{ color: "var(--text)" }}>
          {s.name_fa}
        </div>
        <div className="text-xs" style={{ color: "var(--text-3)", direction: "ltr", textAlign: "start" }}>
          {s.name_en}
          {ownerLabel(s) ? ` · ${ownerLabel(s)}` : ""}
        </div>
        {s.inspired ? (
          <div className="mt-1 text-[11px] leading-5" style={{ color: "var(--text-3)" }}>
            الهام‌گرفته از {s.inspired}
          </div>
        ) : null}
      </div>
    </button>
  );
}

export type CustomActions = {
  onNew: () => void;
  onEdit: (s: StyleDef) => void;
  onDuplicate: (s: StyleDef) => void;
  onDelete: (s: StyleDef) => void;
  onExport: (s: StyleDef) => void;
  canGlobal: boolean;
};

export default function StyleGallery({
  catalog,
  value,
  onChange,
  compact = false,
  custom,
}: {
  catalog: Catalog;
  value: string;
  onChange: (id: string) => void;
  compact?: boolean;
  custom?: CustomActions;
}) {
  const [group, setGroup] = useState<string>("");
  const [q, setQ] = useState("");
  const list = useMemo(() => {
    return catalog.styles.filter((s) => (!group || (group === "__mine" ? !!s.custom : s.group === group)) && styleMatches(s, q));
  }, [catalog, group, q]);
  const current = catalog.styles.find((s) => s.id === value);
  const mine = catalog.styles.filter((s) => s.custom).length;
  const canEdit = (s: StyleDef) => !!s.custom && (s.scope !== "global" || !!custom?.canGlobal);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="min-w-[200px] flex-1">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجوی سبک (نام، برچسب، نوعِ فروشگاه…)" />
        </div>
        {custom ? (
          <button type="button" className="u-btn u-btn-sm u-btn-primary" onClick={custom.onNew} data-testid="new-style">
            <Icon name="plus" size={14} /> سبکِ تازه
          </button>
        ) : null}
        <button type="button" className={`u-btn u-btn-sm ${group === "" ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setGroup("")}>
          همه ({fa(catalog.styles.length)})
        </button>
        {mine ? (
          <button type="button" className={`u-btn u-btn-sm ${group === "__mine" ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setGroup("__mine")}>
            سبک‌های من ({fa(mine)})
          </button>
        ) : null}
        {Object.entries(catalog.groups).map(([k, label]) => (
          <button key={k} type="button" className={`u-btn u-btn-sm ${group === k ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setGroup(k)}>
            {label}
          </button>
        ))}
      </div>
      {current ? (
        <div className="mb-3 rounded-xl p-3 text-sm leading-7" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>
          <b style={{ color: "var(--text)" }}>{current.name_fa}</b> — {current.about}
          {current.fits ? (
            <div className="mt-1" style={{ color: "var(--text-3)" }}>
              مناسبِ: {current.fits}
            </div>
          ) : null}
          {current.custom && current.qa?.summary ? (
            <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
              کنترلِ کیفیت: {current.qa.summary}
            </div>
          ) : null}
          {custom ? (
            <div className="mt-2 flex flex-wrap gap-2">
              <button type="button" className="u-btn u-btn-sm u-btn-secondary" onClick={() => custom.onDuplicate(current)}>
                <Icon name="copy" size={13} /> ساختِ سبکِ تازه از روی این
              </button>
              {canEdit(current) ? (
                <>
                  <button type="button" className="u-btn u-btn-sm u-btn-secondary" onClick={() => custom.onEdit(current)}>
                    <Icon name="edit" size={13} /> ویرایش
                  </button>
                  <button type="button" className="u-btn u-btn-sm u-btn-ghost" onClick={() => custom.onExport(current)}>
                    <Icon name="download" size={13} /> خروجیِ JSON
                  </button>
                  <button type="button" className="u-btn u-btn-sm u-btn-ghost" onClick={() => custom.onDelete(current)}>
                    <Icon name="trash" size={13} /> حذف
                  </button>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${compact ? 120 : 150}px, 1fr))`, maxHeight: compact ? 420 : undefined, overflowY: compact ? "auto" : undefined }}>
        {list.map((s) => (
          <Card key={s.id} s={s} active={s.id === value} onPick={() => onChange(s.id)} />
        ))}
      </div>
      {!list.length ? (
        <div className="py-8 text-center text-sm" style={{ color: "var(--text-3)" }}>
          سبکی با این جستجو پیدا نشد.
        </div>
      ) : null}
    </div>
  );
}
