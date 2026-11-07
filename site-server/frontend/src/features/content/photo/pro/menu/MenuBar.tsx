import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { MENUS, type Command, type Host, type MenuId } from "./registry";
import "./menu.css";

/** منوی کامل: پرونده / ویرایش / تصویر / لایه / انتخاب / فیلتر / نما / پنجره / راهنما — از روی فهرستِ یگانهٔ دستورها ساخته می‌شود. */
export default function MenuBar({ cmds, host, run }: { cmds: Command[]; host: Host; run: (c: Command) => void }) {
  const [open, setOpen] = useState<MenuId | null>(null);
  const [grp, setGrp] = useState<string>("");
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const btns = useRef<Partial<Record<MenuId, HTMLButtonElement | null>>>({});

  const byMenu = useMemo(() => {
    const m = new Map<MenuId, Command[]>();
    for (const c of cmds) m.set(c.menu, [...(m.get(c.menu) ?? []), c]);
    return m;
  }, [cmds]);

  const groupsOf = (id: MenuId) => {
    const gs: string[] = [];
    for (const c of byMenu.get(id) ?? []) if (!gs.includes(c.group)) gs.push(c.group);
    return gs;
  };
  const big = (id: MenuId) => (byMenu.get(id)?.length ?? 0) > 22 && groupsOf(id).length > 2;

  const openMenu = useCallback(
    (id: MenuId) => {
      setOpen(id);
      setGrp(groupsOf(id)[0] ?? "");
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [byMenu],
  );

  // جای بازشو: زیرِ دکمه، داخلِ صفحه
  useLayoutEffect(() => {
    if (!open) return setPos(null);
    const b = btns.current[open];
    if (!b) return;
    const r = b.getBoundingClientRect();
    const vw = window.innerWidth;
    const width = Math.min(big(open) ? 420 : 320, vw - 16);
    const left = Math.max(8, Math.min(r.right - width, vw - width - 8));
    setPos({ top: r.bottom + 4, left, width });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, grp]);

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => {
      const t = e.target as Node;
      if (pop.current?.contains(t) || bar.current?.contains(t)) return;
      setOpen(null);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(null);
        btns.current[open]?.focus();
      }
    };
    const resize = () => setOpen(null);
    document.addEventListener("mousedown", down);
    window.addEventListener("keydown", key, true);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("mousedown", down);
      window.removeEventListener("keydown", key, true);
      window.removeEventListener("resize", resize);
    };
  }, [open]);

  // با باز شدنِ منو روی اولین مورد فوکوس
  useEffect(() => {
    if (open) pop.current?.querySelector<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')?.focus();
  }, [open, grp]);

  const onBarKey = (e: React.KeyboardEvent) => {
    const ids = MENUS.map((m) => m.id);
    const i = open ? ids.indexOf(open) : ids.findIndex((id) => btns.current[id] === document.activeElement);
    if (i < 0) return;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      // راست‌به‌چپ: فلشِ راست = منوی قبلی (سمتِ راست)
      const step = e.key === "ArrowRight" ? -1 : 1;
      const n = ids[(i + step + ids.length) % ids.length];
      e.preventDefault();
      if (open) openMenu(n);
      btns.current[n]?.focus();
    } else if (e.key === "ArrowDown" && !open) {
      e.preventDefault();
      openMenu(ids[i]);
    }
  };

  const onPopKey = (e: React.KeyboardEvent) => {
    const items = Array.from(pop.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])') ?? []);
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      items[(i + 1) % items.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      items[(i - 1 + items.length) % items.length]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      items[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      items[items.length - 1]?.focus();
    }
  };

  const fire = (c: Command) => {
    if (c.enabled?.(host)) return;
    setOpen(null);
    run(c);
  };

  const list = open ? (byMenu.get(open) ?? []) : [];
  const isBig = open ? big(open) : false;
  const shown = isBig ? list.filter((c) => c.group === grp) : list;
  const groups = open ? groupsOf(open) : [];

  return (
    <div className="mn-bar" role="menubar" aria-label="منوی کامل" ref={bar} onKeyDown={onBarKey} data-testid="menubar">
      {MENUS.map((m) => (
        <button
          key={m.id}
          ref={(el) => {
            btns.current[m.id] = el;
          }}
          type="button"
          role="menuitem"
          aria-haspopup="menu"
          aria-expanded={open === m.id}
          className={`mn-top ${open === m.id ? "is-open" : ""}`}
          data-menu={m.id}
          onClick={() => (open === m.id ? setOpen(null) : openMenu(m.id))}
          onMouseEnter={() => open && open !== m.id && openMenu(m.id)}
        >
          {m.title}
        </button>
      ))}
      {open && pos && (
        <div ref={pop} className="mn-pop" role="menu" aria-label={MENUS.find((m) => m.id === open)?.title} style={{ top: pos.top, left: pos.left, width: pos.width }} onKeyDown={onPopKey} dir="rtl" data-testid={`menu-${open}`}>
          {isBig && (
            <div className="mn-groups" role="tablist" aria-label="گروه‌ها">
              {groups.map((g) => (
                <button key={g} type="button" role="tab" aria-selected={g === grp} className={`mn-grp ${g === grp ? "is-on" : ""}`} onClick={() => setGrp(g)}>
                  {g}
                </button>
              ))}
            </div>
          )}
          <div className="mn-items">
            {shown.map((c, i) => {
              const why = c.enabled?.(host) ?? null;
              const head = !isBig && (i === 0 || shown[i - 1].group !== c.group) ? <div className="mn-head" key={`h-${c.group}`}>{c.group}</div> : null;
              return (
                <div key={c.id} className="mn-row">
                  {head}
                  <button type="button" role="menuitem" className="mn-item" aria-disabled={!!why} data-cmd={c.id} title={why ? `${why} — ${c.tip}` : c.tip} onClick={() => fire(c)}>
                    <span className="mn-t">{c.title}</span>
                    {c.key && <kbd className="mn-k" dir="ltr">{c.key}</kbd>}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
