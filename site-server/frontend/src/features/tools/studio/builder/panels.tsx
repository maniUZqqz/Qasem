/** پنل‌های کناریِ ویرایشگر: کتابخانهٔ بلوک، ساختارِ صفحه، پوسته، منو، رسانه، نسخه‌ها و قالب‌های شروع. */
import { DragEvent, ReactNode, useEffect, useRef, useState } from "react";

import { api, studioError } from "../api";
import type { Block, Catalog, Doc } from "./doc";
import { contrastRatio, mix, readableOn, specOf } from "./doc";
import { ColorField, Svg } from "./fields";
import type { AssetT, MenuRow, PageRow, SectionT, StarterT, ThemeOptions, ThemeT, VersionT } from "./types";

/* ─────────── کتابخانهٔ بلوک ─────────── */
export function LibraryPanel({
  catalog,
  target,
  sections,
  onAdd,
  onDragStart,
  onAddSaved,
  onDragSaved,
  onDeleteSaved,
}: {
  catalog: Catalog;
  target: string;
  sections: SectionT[];
  onAdd: (type: string) => void;
  onDragStart: (type: string, x: number, y: number) => void;
  onAddSaved: (s: SectionT) => void;
  onDragSaved: (s: SectionT, x: number, y: number) => void;
  onDeleteSaved: (s: SectionT) => void;
}) {
  const [q, setQ] = useState("");
  const items = catalog.blocks.filter(
    (b) => !b.hidden && (!b.scope.length || b.scope.includes(target)) && (!q.trim() || b.label.includes(q.trim())),
  );
  const press = (e: React.PointerEvent, go: (x: number, y: number) => void) => {
    if (e.pointerType === "touch" || e.button !== 0) return;
    const sx = e.clientX;
    const sy = e.clientY;
    const move = (ev: PointerEvent) => {
      if (Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) > 6) {
        cleanup();
        go(ev.clientX, ev.clientY);
      }
    };
    const cleanup = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", cleanup);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", cleanup);
  };
  return (
    <div className="nbe-pane" data-testid="library">
      <input className="nbe-input" placeholder="جست‌وجوی بلوک…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="جست‌وجوی بلوک" />
      {catalog.groups.map((g) => {
        const rows = items.filter((b) => b.group === g.value);
        if (!rows.length) return null;
        return (
          <section key={g.value} className="nbe-libgroup">
            <h4>{g.label}</h4>
            <div className="nbe-libgrid">
              {rows.map((b) => (
                <button
                  key={b.type}
                  type="button"
                  className={`nbe-libitem ${b.advanced ? "adv" : ""}`}
                  data-block={b.type}
                  title={b.hint || b.label}
                  onPointerDown={(e) => press(e, (x, y) => onDragStart(b.type, x, y))}
                  onClick={() => onAdd(b.type)}
                >
                  <Svg body={catalog.icons[b.icon] ?? ""} size={22} />
                  <span>{b.label}</span>
                </button>
              ))}
            </div>
          </section>
        );
      })}
      {sections.length > 0 && !q && (
        <section className="nbe-libgroup">
          <h4>بخش‌های ذخیره‌شدهٔ من</h4>
          <div className="nbe-saved">
            {sections.map((s) => (
              <div key={s.id} className="nbe-saved-row">
                <button type="button" onPointerDown={(e) => press(e, (x, y) => onDragSaved(s, x, y))} onClick={() => onAddSaved(s)}>
                  {s.title}
                </button>
                <button type="button" className="nbe-x" aria-label={`حذفِ ${s.title}`} onClick={() => onDeleteSaved(s)}>
                  ×
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
      <p className="nbe-note">بلوک را بکش و روی صفحه بینداز، یا روی آن بزن تا بعد از بخشِ انتخاب‌شده بنشیند.</p>
    </div>
  );
}

/* ─────────── ساختارِ صفحه ─────────── */
export function OutlinePanel({ doc, catalog, selected, onSelect }: { doc: Doc; catalog: Catalog; selected: string | null; onSelect: (id: string) => void }) {
  const row = (b: Block, depth: number): ReactNode => (
    <div key={b.id}>
      <button type="button" className={`nbe-outline-row ${selected === b.id ? "on" : ""}`} style={{ paddingInlineStart: 8 + depth * 14 }} onClick={() => onSelect(b.id)}>
        <Svg body={catalog.icons[specOf(catalog, b.type)?.icon ?? "layout"] ?? ""} size={15} />
        <span>{specOf(catalog, b.type)?.label ?? b.type}</span>
        <small>{previewOf(b)}</small>
      </button>
      {(b.children ?? []).map((c) => row(c, depth + 1))}
    </div>
  );
  return (
    <div className="nbe-pane">
      {doc.blocks.length ? doc.blocks.map((b) => row(b, 0)) : <p className="nbe-note">هنوز بلوکی نگذاشته‌ای.</p>}
    </div>
  );
}

function previewOf(b: Block): string {
  const v = b.props?.text ?? b.props?.title ?? "";
  return typeof v === "string" ? v.slice(0, 22) : "";
}

/* ─────────── پوسته ─────────── */
export function ThemePanel({ theme, options, onChange }: { theme: ThemeT; options: ThemeOptions; onChange: (t: ThemeT) => void }) {
  const setColor = (key: keyof ThemeT["colors"], v: string) => {
    const colors = { ...theme.colors, [key]: v };
    if (key === "primary") colors.on_primary = readableOn(v);
    if (key === "text" || key === "bg") {
      colors.text2 = mix(colors.text, colors.bg, 0.15);
      colors.muted = mix(colors.text, colors.bg, 0.4);
      colors.line = mix(colors.bg, colors.text, 0.12);
    }
    onChange({ ...theme, colors });
  };
  const basic: [keyof ThemeT["colors"], string][] = [
    ["primary", "رنگِ اصلی (دکمه‌ها و لینک‌ها)"],
    ["bg", "زمینهٔ صفحه"],
    ["surface", "زمینهٔ کارت‌ها"],
    ["text", "رنگِ متن"],
  ];
  const lowContrast = contrastRatio(theme.colors.text, theme.colors.bg) < 4.5;
  return (
    <div className="nbe-pane" data-testid="theme">
      <h4 className="nbe-h">رنگ‌های آماده</h4>
      <div className="nbe-presets">
        {options.presets.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => {
              const c = { ...theme.colors, ...p.colors } as ThemeT["colors"];
              c.on_primary = p.colors.on_primary ?? readableOn(c.primary);
              c.text2 = p.colors.text2 ?? mix(c.text, c.bg, 0.15);
              c.muted = p.colors.muted ?? mix(c.text, c.bg, 0.4);
              c.line = p.colors.line ?? mix(c.bg, c.text, 0.12);
              onChange({ ...theme, colors: c });
            }}
          >
            <i style={{ background: p.colors.primary }} />
            <i style={{ background: p.colors.bg }} />
            <span>{p.label}</span>
          </button>
        ))}
      </div>
      <h4 className="nbe-h">رنگ‌ها</h4>
      {basic.map(([k, label]) => (
        <div className="nbe-field nbe-colorrow" key={k}>
          <label>
            <input type="color" value={theme.colors[k]} data-theme-color={k} onChange={(e) => setColor(k, e.target.value)} />
            <span>{label}</span>
          </label>
        </div>
      ))}
      {lowContrast && <p className="nbe-warn">رنگِ متن با زمینهٔ صفحه به‌سختی خوانده می‌شود.</p>}
      <h4 className="nbe-h">قلم</h4>
      <div className="nbe-field">
        <div className="nbe-label">قلمِ متن</div>
        <select className="nbe-input" data-testid="font-body" value={theme.font_body} onChange={(e) => onChange({ ...theme, font_body: e.target.value })}>
          {options.fonts.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </div>
      <div className="nbe-field">
        <div className="nbe-label">قلمِ تیترها</div>
        <select className="nbe-input" value={theme.font_head} onChange={(e) => onChange({ ...theme, font_head: e.target.value })}>
          {options.fonts.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </div>
      <h4 className="nbe-h">شکل‌ها</h4>
      <div className="nbe-field">
        <div className="nbe-label">شکلِ دکمه‌ها</div>
        <div className="nbe-seg">
          {options.buttons.map((b) => (
            <button key={b.value} type="button" className={theme.button === b.value ? "on" : ""} onClick={() => onChange({ ...theme, button: b.value })}>
              {b.label}
            </button>
          ))}
        </div>
      </div>
      <div className="nbe-field">
        <div className="nbe-label">
          <span>گردیِ کارت‌ها</span>
          <span className="nbe-num">{theme.radius}px</span>
        </div>
        <input className="nbe-range" dir="ltr" type="range" min={0} max={32} value={theme.radius} onChange={(e) => onChange({ ...theme, radius: Number(e.target.value) })} />
      </div>
      <p className="nbe-note">این تنظیم‌ها روی همهٔ صفحه‌ها اثر دارند و با «انتشار» به سایت می‌رسند.</p>
    </div>
  );
}

/* ─────────── منو ─────────── */
export function MenuPanel({ menu, pages, onChange }: { menu: MenuRow[]; pages: PageRow[]; onChange: (m: MenuRow[]) => void }) {
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  // تا وقتی چیزی چیده نشده، منوی فعلیِ سایت را نشان بده
  const rows: MenuRow[] = menu.length ? menu : pages.filter((p) => p.in_menu).map((p) => ({ id: `p${p.id}`, page: p.id, label: p.title }));
  const titleOf = (r: MenuRow) => pages.find((p) => p.id === r.page)?.title ?? r.url ?? "";
  const unused = pages.filter((p) => !rows.some((r) => r.page === p.id || r.children?.some((c) => c.page === p.id)));
  const set = (next: MenuRow[]) => onChange(next);
  const setChild = (i: number, fn: (kids: MenuRow[]) => MenuRow[]) => set(rows.map((x, j) => (j === i ? { ...x, children: fn(x.children ?? []) } : x)));
  const startDrag = (e: React.PointerEvent, index: number) => {
    e.preventDefault();
    const box = listRef.current;
    if (!box) return;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    let cur = index;
    const move = (ev: PointerEvent) => {
      const kids = Array.from(box.children) as HTMLElement[];
      for (let i = 0; i < kids.length; i += 1) {
        const r = kids[i].getBoundingClientRect();
        if (ev.clientY >= r.top && ev.clientY <= r.bottom && i !== cur) {
          const next = [...latest.current];
          const [m] = next.splice(cur, 1);
          next.splice(i, 0, m);
          cur = i;
          latest.current = next;
          set(next);
          break;
        }
      }
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const latest = useRef(rows);
  latest.current = rows;
  return (
    <div className="nbe-pane" data-testid="menu">
      <h4 className="nbe-h">منوی سایت</h4>
      <p className="nbe-note">با دستگیره جابه‌جا کن. نام را هم می‌توانی عوض کنی. با دکمهٔ ← هر ردیف زیرمنوی ردیفِ بالایی‌اش می‌شود (فقط دو سطح).</p>
      <div className="nbe-menu" ref={listRef}>
        {rows.map((r, i) => (
          <div className="nbe-menu-row" key={r.id} data-menu-row={r.id}>
            <span className="nbe-grip" role="button" aria-label="جابه‌جا کن" onPointerDown={(e) => startDrag(e, i)}>
              ⋮⋮
            </span>
            <input className="nbe-input" value={r.label} placeholder={titleOf(r)} onChange={(e) => set(rows.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} aria-label="نامِ گزینهٔ منو" />
            <button type="button" aria-label="بالاتر" disabled={i === 0} onClick={() => { const n = [...rows]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; set(n); }}>↑</button>
            <button type="button" aria-label="پایین‌تر" disabled={i === rows.length - 1} onClick={() => { const n = [...rows]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; set(n); }}>↓</button>
            <button
              type="button"
              aria-label="زیرمنوی ردیفِ بالایی شود"
              title="زیرمنوی ردیفِ بالایی شود"
              data-menu-indent={r.id}
              disabled={i === 0 || !!r.children?.length}
              onClick={() => {
                const n = rows.filter((_, j) => j !== i);
                const parent = n[i - 1];
                n[i - 1] = { ...parent, children: [...(parent.children ?? []), { id: r.id, page: r.page, url: r.url, label: r.label }] };
                set(n);
              }}
            >
              ←
            </button>
            <button type="button" aria-label="حذف از منو" onClick={() => set(rows.filter((_, j) => j !== i))}>×</button>
            {(r.children ?? []).map((c, k) => (
              <div className="nbe-menu-row nbe-menu-child" key={c.id} data-menu-child={c.id}>
                <input
                  className="nbe-input"
                  value={c.label}
                  placeholder={titleOf(c)}
                  aria-label="نامِ زیرمنو"
                  onChange={(e) => setChild(i, (kids) => kids.map((x, j) => (j === k ? { ...x, label: e.target.value } : x)))}
                />
                <button type="button" aria-label="بالاتر" disabled={k === 0} onClick={() => setChild(i, (kids) => { const n = [...kids]; [n[k - 1], n[k]] = [n[k], n[k - 1]]; return n; })}>↑</button>
                <button type="button" aria-label="پایین‌تر" disabled={k === (r.children?.length ?? 0) - 1} onClick={() => setChild(i, (kids) => { const n = [...kids]; [n[k + 1], n[k]] = [n[k], n[k + 1]]; return n; })}>↓</button>
                <button
                  type="button"
                  aria-label="برگرداندن به منوی اصلی"
                  title="برگرداندن به منوی اصلی"
                  data-menu-outdent={c.id}
                  onClick={() => {
                    const n = rows.map((x, j) => (j === i ? { ...x, children: (x.children ?? []).filter((_, m) => m !== k) } : x));
                    n.splice(i + 1, 0, { id: c.id, page: c.page, url: c.url, label: c.label });
                    set(n);
                  }}
                >
                  →
                </button>
                <button type="button" aria-label="حذف از منو" onClick={() => setChild(i, (kids) => kids.filter((_, j) => j !== k))}>×</button>
              </div>
            ))}
          </div>
        ))}
        {!rows.length && <p className="nbe-note">منو خالی است.</p>}
      </div>
      {unused.length > 0 && (
        <>
          <h4 className="nbe-h">افزودنِ صفحه</h4>
          <div className="nbe-chips">
            {unused.map((p) => (
              <button key={p.id} type="button" data-add-page={p.id} onClick={() => set([...rows, { id: `p${p.id}`, page: p.id, label: p.title }])}>
                + {p.title}
              </button>
            ))}
          </div>
        </>
      )}
      <h4 className="nbe-h">افزودنِ لینکِ دلخواه</h4>
      <input className="nbe-input" placeholder="نام، مثلاً اینستاگرام" value={label} onChange={(e) => setLabel(e.target.value)} aria-label="نامِ لینک" />
      <input className="nbe-input mt" dir="ltr" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="نشانیِ لینک" />
      <button
        type="button"
        className="nbe-add"
        disabled={!url.trim()}
        onClick={() => {
          set([...rows, { id: `u${Date.now().toString(36)}`, url: url.trim(), label: label.trim() || url.trim() }]);
          setUrl("");
          setLabel("");
        }}
      >
        + افزودنِ لینک
      </button>
    </div>
  );
}

/* ─────────── رسانه ─────────── */
export function MediaPanel({
  slug,
  media,
  setMedia,
  accept,
  onPick,
}: {
  slug: string;
  media: AssetT[];
  setMedia: (m: AssetT[]) => void;
  accept?: string;
  onPick?: (a: AssetT) => void;
}) {
  const [busy, setBusy] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [edit, setEdit] = useState<AssetT | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const list = media.filter((a) => !accept || a.kind === accept);
  async function upload(files: FileList | File[]) {
    setError(null);
    let cur = media;
    for (const file of Array.from(files)) {
      setBusy((n) => n + 1);
      try {
        const fd = new FormData();
        fd.append("file", file);
        const { data } = await api.post<{ asset: AssetT }>(`/studio/projects/${slug}/builder/media/`, fd);
        cur = [data.asset, ...cur.filter((x) => x.id !== data.asset.id)];
        setMedia(cur);
      } catch (err) {
        setError(`${file.name}: ${studioError(err)}`);
      } finally {
        setBusy((n) => n - 1);
      }
    }
  }
  async function remove(a: AssetT) {
    if (!window.confirm(`«${a.name}» حذف شود؟`)) return;
    try {
      await api.delete(`/studio/projects/${slug}/builder/media/${a.id}/`);
      setMedia(media.filter((x) => x.id !== a.id));
    } catch (err) {
      const msg = studioError(err);
      if (window.confirm(`${msg}\nبا این حال حذف شود؟ آن صفحه‌ها تصویرشان را از دست می‌دهند.`)) {
        await api.delete(`/studio/projects/${slug}/builder/media/${a.id}/?force=1`);
        setMedia(media.filter((x) => x.id !== a.id));
      }
    }
    setEdit(null);
  }
  async function saveAlt(a: AssetT, alt: string) {
    const { data } = await api.put<{ asset: AssetT }>(`/studio/projects/${slug}/builder/media/${a.id}/`, { alt });
    setMedia(media.map((x) => (x.id === a.id ? data.asset : x)));
    setEdit(null);
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) void upload(e.dataTransfer.files);
  };
  return (
    <div className="nbe-pane" data-testid="media" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <button type="button" className="nbe-upload" onClick={() => inputRef.current?.click()}>
        {busy ? "در حالِ فرستادن…" : "بارگذاریِ فایلِ تازه"}
        <small>JPG، PNG، WebP، GIF تا ۱۲ مگابایت؛ MP4 تا ۴۰ مگابایت. تصویرها خودکار کوچک و فشرده می‌شوند.</small>
      </button>
      <input
        ref={inputRef}
        type="file"
        data-testid="media-input"
        hidden
        multiple
        accept={accept === "video" ? "video/mp4,video/webm" : accept === "image" ? "image/*" : "image/*,video/mp4,video/webm"}
        onChange={(e) => {
          if (e.target.files?.length) void upload(e.target.files);
          e.target.value = "";
        }}
      />
      {error && <p className="nbe-warn">{error}</p>}
      <div className="nbe-medialist">
        {list.map((a) => (
          <figure key={a.id} className="nbe-mediaitem">
            <button type="button" onClick={() => (onPick ? onPick(a) : setEdit(a))} title={a.name} data-asset={a.id}>
              {a.kind === "image" ? <img src={a.thumb} alt={a.alt} loading="lazy" /> : <span className="nbe-videotag">ویدیو</span>}
            </button>
            <figcaption>
              <span>{a.name}</span>
              <button type="button" className="nbe-link" onClick={() => setEdit(a)}>
                ویرایش
              </button>
            </figcaption>
          </figure>
        ))}
        {!list.length && <p className="nbe-note">هنوز فایلی نیست. اولین تصویر را بارگذاری کن.</p>}
      </div>
      {edit && (
        <div className="nbe-mediaedit">
          <b>{edit.name}</b>
          <label className="nbe-label">توضیحِ تصویر (برای نابینایان و گوگل)</label>
          <textarea className="nbe-input" rows={2} defaultValue={edit.alt} id="nbe-alt" />
          <div className="nbe-row">
            <button type="button" className="nbe-add" onClick={() => void saveAlt(edit, (document.getElementById("nbe-alt") as HTMLTextAreaElement).value)}>
              ذخیره
            </button>
            <button type="button" className="nbe-link danger" onClick={() => void remove(edit)}>
              حذفِ فایل
            </button>
            <button type="button" className="nbe-link" onClick={() => setEdit(null)}>
              بستن
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─────────── نسخه‌ها ─────────── */
const VERSION_KIND: Record<string, string> = { publish: "انتشار", draft: "پیش‌نویس", external: "با هوشِ مصنوعی یا کد" };

export function VersionsPanel({ versions, onRestore }: { versions: VersionT[]; onRestore: (v: VersionT) => void }) {
  return (
    <div className="nbe-pane" data-testid="versions">
      <h4 className="nbe-h">نسخه‌های قبلی</h4>
      <p className="nbe-note">برگرداندنِ یک نسخه فقط پیش‌نویس را عوض می‌کند؛ سایت تا «انتشار» دست نمی‌خورد.</p>
      {versions.map((v) => (
        <div className="nbe-version" key={v.id}>
          <div>
            <b>{VERSION_KIND[v.kind] ?? v.label}</b>
            <small dir="ltr">{new Date(v.created_at).toLocaleString("fa-IR")}</small>
          </div>
          <button type="button" className="nbe-link" data-restore={v.id} onClick={() => onRestore(v)}>
            برگرداندن
          </button>
        </div>
      ))}
      {!versions.length && <p className="nbe-note">هنوز نسخه‌ای نیست؛ با هر انتشار یکی ساخته می‌شود.</p>}
    </div>
  );
}

/* ─────────── انتخابِ قالب ─────────── */
export function StarterGrid({ starters, icons, onPick, busy, hasCart }: { starters: StarterT[]; icons: Record<string, string>; onPick: (s: StarterT) => void; busy?: boolean; hasCart?: boolean }) {
  const list = starters.filter((s) => s.key !== "home_shop" || hasCart);
  return (
    <div className="nbe-starters">
      {list.map((s) => (
        <button key={s.key} type="button" disabled={busy} className="nbe-starter" data-starter={s.key} onClick={() => onPick(s)}>
          <span className="nbe-starter-icon">
            <Svg body={icons[s.icon] ?? icons.layout} size={26} />
          </span>
          <b>{s.title}</b>
          <small>{s.desc}</small>
        </button>
      ))}
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="nbe-modal-bg" onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`nbe-modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <h3>{title}</h3>
          <button type="button" aria-label="بستن" onClick={onClose}>
            ×
          </button>
        </header>
        <div className="nbe-modal-b">{children}</div>
      </div>
    </div>
  );
}

export { ColorField };
