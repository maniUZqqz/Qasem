import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useParams } from "react-router-dom";

import { errorMessage } from "../../api/client";
import Icon, { type IconName } from "../../components/Icon";
import { Alert, Badge, ErrorBox, PageHeader, Spinner } from "../../components/ui";
import { Character, Overview, bcApi } from "./api";
import "./brandchar.css";

type Ctx = {
  id: string;
  ov: Overview;
  reload: (keep?: number | null) => Promise<void>;
  /** شخصیتِ دیداریِ انتخاب‌شده (پیش‌فرض: «اصلی») */
  sel: Character | null;
  select: (id: number | null) => void;
};

const C = createContext<Ctx | null>(null);

export function useBrandChar(): Ctx {
  const c = useContext(C);
  if (!c) throw new Error("useBrandChar: outside BrandCharLayout");
  return c;
}

export const TABS: { to: string; end?: boolean; label: string; icon: IconName; key: string }[] = [
  { to: "", end: true, label: "نمای کلی", icon: "dashboard", key: "overview" },
  { to: "persona", label: "شخصیتِ گفتار", icon: "mic", key: "persona" },
  { to: "studio", label: "استودیوی شخصیت", icon: "sparkle", key: "studio" },
  { to: "scenes", label: "ژست و صحنه", icon: "image", key: "scenes" },
  { to: "gallery", label: "گالری و کاربرد", icon: "rocket", key: "gallery" },
  { to: "export", label: "خروجی", icon: "download", key: "export" },
];

export default function BrandCharLayout() {
  const { id = "" } = useParams<{ id: string }>();
  const [ov, setOv] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selId, setSelId] = useState<number | null>(null);

  const reload = useCallback(
    async (keep?: number | null) => {
      try {
        const o = await bcApi.overview(id);
        setOv(o);
        setError(null);
        setSelId((cur) => {
          const want = keep ?? cur;
          return o.characters.find((c) => c.id === want)?.id ?? o.characters.find((c) => c.is_primary)?.id ?? o.characters[0]?.id ?? null;
        });
      } catch (e) {
        setError(errorMessage(e));
      }
    },
    [id],
  );

  useEffect(() => {
    setOv(null);
    void reload();
  }, [reload]);

  // «کارت»ِ هر شخصیت همیشه نیم‌تنهٔ شفافِ تمیز است (نه آخرین پست یا برگه). اگر هنوز ساخته نشده یا با ویرایش کهنه شده، آرام و یکی‌یکی در پس‌زمینه ساخته می‌شود.
  const coverTried = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!ov) return;
    const todo = ov.characters.find((c) => c.cover_kind !== "bust" && !coverTried.current.has(`${id}:${c.id}:${c.updated_at}`));
    if (!todo) return;
    coverTried.current.add(`${id}:${todo.id}:${todo.updated_at}`);
    bcApi
      .cover(id, todo.id)
      .then((fresh) => setOv((cur) => (cur ? { ...cur, characters: cur.characters.map((c) => (c.id === fresh.id ? { ...c, cover: fresh.cover, cover_kind: fresh.cover_kind } : c)) } : cur)))
      .catch(() => undefined);
  }, [ov, id]);

  const value = useMemo<Ctx | null>(() => {
    if (!ov) return null;
    return { id, ov, reload, sel: ov.characters.find((c) => c.id === selId) ?? null, select: setSelId };
  }, [id, ov, reload, selId]);

  const base = `/stores/${id}/brand-character`;
  return (
    <div className="bc-root" data-testid="brandchar-root">
      <PageHeader
        title="شخصیتِ برند"
        subtitle="لحنِ گفتار و چهرهٔ دیداریِ برندتان را یک بار بسازید؛ در کپشن، موشن، تامنیل، پست، صندوقِ پیام، سایت و ویدیو همه‌جا همان می‌ماند."
        actions={value?.ov.persona.exists ? <Badge tone={value.ov.persona.locked ? "ok" : "info"}>{value.ov.persona.locked ? "گفتار تأییدشده" : "گفتار پیش‌نویس"}</Badge> : undefined}
      />
      <nav className="bc-tabs" aria-label="بخش‌های شخصیتِ برند">
        {TABS.map((t) => (
          <NavLink key={t.key} to={t.to ? `${base}/${t.to}` : base} end={t.end} className={({ isActive }) => `bc-tab${isActive ? " is-active" : ""}`}>
            <Icon name={t.icon} size={15} />
            <span>{t.label}</span>
          </NavLink>
        ))}
      </nav>
      {error ? <ErrorBox message={error} /> : null}
      {!value && !error ? (
        <div className="bc-center">
          <Spinner />
        </div>
      ) : null}
      {value ? (
        <C.Provider value={value}>
          {!value.ov.persona.exists && value.ov.characters.length === 0 ? (
            <Alert tone="brand" title="از اینجا شروع کنید">
              در «شخصیتِ گفتار» نام و لحن را بنویسید (یا جادوگر پیش‌نویس بسازد)، بعد در «استودیوی شخصیت» چهره را بسازید. همه‌چیز بدونِ هوش مصنوعی هم کار می‌کند.
            </Alert>
          ) : null}
          <Outlet />
        </C.Provider>
      ) : null}
    </div>
  );
}
