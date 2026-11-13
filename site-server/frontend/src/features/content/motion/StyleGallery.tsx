import { useMemo, useState } from "react";

import Icon from "../../../components/Icon";
import { Input, fa } from "../../../components/ui";
import { Catalog, StyleDef, thumbUrl } from "./api";

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
          <img src={thumbUrl(s.id)} alt={s.name_fa} loading="lazy" className="h-full w-full object-cover" onError={() => setBroken(true)} />
        )}
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

export default function StyleGallery({
  catalog,
  value,
  onChange,
  compact = false,
}: {
  catalog: Catalog;
  value: string;
  onChange: (id: string) => void;
  compact?: boolean;
}) {
  const [group, setGroup] = useState<string>("");
  const [q, setQ] = useState("");
  const list = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return catalog.styles.filter(
      (s) =>
        (!group || s.group === group) &&
        (!needle ||
          s.name_fa.includes(q.trim()) ||
          s.name_en.toLowerCase().includes(needle) ||
          s.tags.some((t) => t.includes(q.trim())) ||
          (s.inspired || "").toLowerCase().includes(needle)),
    );
  }, [catalog, group, q]);
  const current = catalog.styles.find((s) => s.id === value);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="min-w-[200px] flex-1">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجوی سبک (نام، برچسب…)" />
        </div>
        <button type="button" className={`u-btn u-btn-sm ${group === "" ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setGroup("")}>
          همه ({fa(catalog.styles.length)})
        </button>
        {Object.entries(catalog.groups).map(([k, label]) => (
          <button key={k} type="button" className={`u-btn u-btn-sm ${group === k ? "u-btn-primary" : "u-btn-secondary"}`} onClick={() => setGroup(k)}>
            {label}
          </button>
        ))}
      </div>
      {current ? (
        <div className="mb-3 rounded-xl p-3 text-sm leading-7" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>
          <b style={{ color: "var(--text)" }}>{current.name_fa}</b> — {current.about}
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
