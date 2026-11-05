import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { Keymap, prettyCombo } from "./keymap";
import { FeatureDef, MENUS, MenuId, WorkspaceApi } from "./types";
import "./registry.css";

type Props = {
  features: FeatureDef[];
  km: Keymap;
  getApi: () => WorkspaceApi;
  run: (f: FeatureDef) => void;
  onSearch: () => void;
};

type Pos = { top: number; right: number; maxH: number };

/** منوی کاملِ فارسی: پرونده / ویرایش / کلیپ / سکانس / نشانگر / گرافیک / رنگ / صدا / نما / پنجره / راهنما. هر ورودی از «ثبتِ ویژگی‌ها» می‌آید. */
function MenuBarBase({ features, km, getApi, run, onSearch }: Props) {
  const [open, setOpen] = useState<MenuId | null>(null);
  const [pos, setPos] = useState<Pos>({ top: 40, right: 8, maxH: 400 });
  const bar = useRef<HTMLDivElement>(null);
  const drop = useRef<HTMLDivElement>(null);
  const btns = useRef<Partial<Record<MenuId, HTMLButtonElement | null>>>({});

  const byMenu = useMemo(() => {
    const m = new Map<MenuId, { group: string; items: FeatureDef[] }[]>();
    for (const f of features) {
      const groups = m.get(f.menu) ?? [];
      let g = groups.find((x) => x.group === f.group);
      if (!g) {
        g = { group: f.group, items: [] };
        groups.push(g);
      }
      g.items.push(f);
      m.set(f.menu, groups);
    }
    return m;
  }, [features]);

  const place = useCallback((id: MenuId) => {
    const b = btns.current[id];
    if (!b) return;
    const r = b.getBoundingClientRect();
    const narrow = window.innerWidth < 640;
    const right = narrow ? 8 : Math.max(8, Math.min(window.innerWidth - r.right, window.innerWidth - 300));
    setPos({ top: r.bottom + 2, right, maxH: Math.max(160, window.innerHeight - r.bottom - 16) });
  }, []);

  useLayoutEffect(() => {
    if (open) place(open);
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      const t = e.target as Node;
      if (bar.current?.contains(t) || drop.current?.contains(t)) return;
      setOpen(null);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(null);
        e.stopPropagation();
      }
    };
    const resize = () => setOpen(null);
    document.addEventListener("pointerdown", away, true);
    document.addEventListener("keydown", esc, true);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("pointerdown", away, true);
      document.removeEventListener("keydown", esc, true);
      window.removeEventListener("resize", resize);
    };
  }, [open]);

  const api = open ? getApi() : null;

  const pick = (f: FeatureDef, reason: string | null) => {
    setOpen(null);
    if (reason) {
      getApi().notice(reason);
      return;
    }
    window.setTimeout(() => run(f), 0);
  };

  /** ↑/↓ میانِ ورودی‌ها، ←/→ میانِ منوها */
  const onDropKey = (e: React.KeyboardEvent) => {
    const items = Array.from(drop.current?.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]') ?? []);
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      items[(i + 1) % items.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      items[(i - 1 + items.length) % items.length]?.focus();
    } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const ids = MENUS.map((m) => m.id);
      const at = ids.indexOf(open as MenuId);
      // صفحه راست‌به‌چپ است: فلشِ راست = منوی قبلی
      const nxt = ids[(at + (e.key === "ArrowLeft" ? 1 : -1) + ids.length) % ids.length];
      setOpen(nxt);
    }
  };

  return (
    <div className="rg-bar" dir="rtl" role="menubar" aria-label="منوی کامل" ref={bar} data-testid="menubar">
      {MENUS.map((m) => (
        <button
          key={m.id} type="button" role="menuitem" aria-haspopup="menu" aria-expanded={open === m.id}
          ref={(el) => { btns.current[m.id] = el; }}
          className={`rg-menu ${open === m.id ? "is-open" : ""}`} data-menu={m.id}
          onClick={() => setOpen((cur) => (cur === m.id ? null : m.id))}
          onMouseEnter={() => open && open !== m.id && setOpen(m.id)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setOpen(m.id);
              window.setTimeout(() => drop.current?.querySelector<HTMLButtonElement>('button[role="menuitem"]:not([aria-disabled="true"])')?.focus(), 30);
            }
          }}
        >
          {m.title}
        </button>
      ))}
      <span className="rg-bar-spacer" />
      <button type="button" className="rg-find" onClick={onSearch} data-testid="menubar-search" title="جستجوی هر ابزار با نامِ فارسی یا انگلیسی (Ctrl+K)">
        جستجوی ابزار <kbd dir="ltr">Ctrl+K</kbd>
      </button>
      {open && api && (
        <div
          ref={drop} className="rg-drop" role="menu" aria-label={MENUS.find((m) => m.id === open)?.title} data-testid={`menu-${open}`}
          style={{ top: pos.top, right: pos.right, maxHeight: pos.maxH }} onKeyDown={onDropKey}
        >
          {(byMenu.get(open) ?? []).map((g, gi) => (
            <div key={g.group} className="rg-grp" role="group" aria-label={g.group}>
              {gi > 0 && <div className="rg-div" role="separator" />}
              <div className="rg-grp-t">{g.group}</div>
              {g.items.map((f) => {
                const reason = f.when ? f.when(api) : null;
                const on = f.on ? f.on(api) : false;
                const combo = km.effective(f.id);
                return (
                  <button
                    key={f.id} type="button" role={f.on ? "menuitemcheckbox" : "menuitem"} aria-checked={f.on ? on : undefined}
                    aria-disabled={reason ? true : undefined} className={`rg-item ${reason ? "is-off" : ""}`}
                    title={reason ? `${reason}\n${f.tip}` : f.tip} data-feature={f.id}
                    onClick={() => pick(f, reason)}
                  >
                    <span className="rg-chk" aria-hidden>{on ? "✓" : ""}</span>
                    <span className="rg-name">{f.title}</span>
                    {combo && <kbd className="rg-key" dir="ltr">{prettyCombo(combo)}</kbd>}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default memo(MenuBarBase);
