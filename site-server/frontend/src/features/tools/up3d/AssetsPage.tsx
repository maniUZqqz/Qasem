import { useState } from "react";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, EmptyState, ErrorBox, PageHeader, Spinner } from "../../../components/ui";
import { desc, errMsg, fa, label, previewUrl, thumbUrl, up3d } from "./api";
import PacksPanel from "./PacksPanel";
import { ButtonTabs, Muted, useCatalog, useToast } from "./shared";
import type { Asset, CatalogKind, Character, Environment, Motion, ProductAsset, RenderProfile, Shot, Voice } from "./types";

/** کتابخانهٔ دارایی‌ها: هر دسته یک تب، هر دارایی یک کارت با تصویر/پیش‌نمایش و مشخصاتِ کلیدی. */

const KINDS: { id: CatalogKind; name: string }[] = [
  { id: "character", name: "کاراکترها" },
  { id: "motion", name: "حرکت‌ها" },
  { id: "environment", name: "محیط‌ها" },
  { id: "product", name: "محصول‌ها" },
  { id: "shot", name: "نماهای دوربین" },
  { id: "lighting", name: "نورپردازی" },
  { id: "render_profile", name: "کیفیتِ رندر" },
  { id: "voice", name: "صداها" },
];

const THUMBABLE: CatalogKind[] = ["character", "motion", "environment", "product"];

function meta(kind: CatalogKind, a: Asset): string {
  switch (kind) {
    case "motion": {
      const m = a as Motion;
      const req = m.product?.requires;
      return `مدت ${fa(m.duration.min)}–${fa(m.duration.max)} ث · ${m.layer ? "لایه" : "بدن"}${
        req ? ` · نیاز: ${req === "in_hand" ? "محصول در دست" : "محصول روی میز"}` : ""
      }`;
    }
    case "environment": {
      const e = a as Environment;
      return `جایگاه‌ها: ${Object.keys(e.marks).join("، ")} · سطح‌ها: ${Object.keys(e.surfaces).join("، ")}`;
    }
    case "product": {
      const p = a as ProductAsset;
      return `ابعاد ${p.dimensions.map((x) => Math.round(x * 100)).join("×")} سانتی‌متر · گرفتن در ${Math.round(p.grasp.height * 100)}٪ ارتفاع`;
    }
    case "shot": {
      const s = a as Shot;
      return `قاب ${s.framing.height}m · لنز ${s.framing.lens}mm · f/${s.framing.fstop} · سوژه: ${s.subject}`;
    }
    case "render_profile": {
      const r = a as RenderProfile;
      return `${r.engine} · ${r.resolution.long}px · ${r.samples ? `${r.samples} نمونه` : ""} · ${r.recommended === "gpu" ? "GPU" : "CPU"}`;
    }
    case "character": {
      const c = a as Character;
      return `${c.gender === "female" ? "خانم" : "آقا"} · ${c.provider}`;
    }
    case "voice": {
      const v = a as Voice;
      return `${v.provider} · ${v.voice || ""} · ${v.gender}`;
    }
    default:
      return "";
  }
}

type View = "library" | "packs";

export default function AssetsPage() {
  const toast = useToast();
  const { cat, error, reload } = useCatalog();
  const [kind, setKind] = useState<CatalogKind>("character");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<View>("library");

  const makeThumbs = async () => {
    setBusy(true);
    try {
      const r = await up3d.thumbnails(kind);
      toast(r.message);
    } catch (e) {
      toast(errMsg(e), true);
    } finally {
      setBusy(false);
    }
  };

  if (!cat) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const list: Asset[] = cat[kind] || [];
  const fromPacks = Object.values(cat).reduce((n, arr) => n + (arr as Asset[]).filter((a) => a.pack).length, 0);

  if (view === "packs") {
    return (
      <div className="space-y-4">
        <PageHeader title="کتابخانهٔ دارایی‌ها" />
        <ButtonTabs
          tabs={[
            { id: "library" as View, label: "کتابخانه" },
            { id: "packs" as View, label: `بسته‌های دارایی${fromPacks ? ` (${fa(fromPacks)} دارایی)` : ""}` },
          ]}
          value={view}
          onChange={setView}
        />
        <PacksPanel onChanged={() => void reload()} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="کتابخانهٔ دارایی‌ها"
        actions={
          THUMBABLE.includes(kind) ? (
            <Button variant="secondary" onClick={() => void makeThumbs()} disabled={busy}>
              <Icon name="image" size={15} />
              {busy ? "در صف…" : "ساختِ تصویرِ این دسته با موتور"}
            </Button>
          ) : undefined
        }
      />
      <ButtonTabs
        tabs={[
          { id: "library" as View, label: "کتابخانه" },
          { id: "packs" as View, label: `بسته‌های دارایی${fromPacks ? ` (${fa(fromPacks)} دارایی)` : ""}` },
        ]}
        value={view}
        onChange={setView}
      />
      <Muted>
        هر دارایی یک پوشه است با فایلِ <code className="u3d-mono">manifest.json</code>. محیط/صحنه، شخص، حرکت (mocap)، محصول، نور و نمای
        دوربینِ تازه بی‌نوشتنِ کد اضافه می‌شود: در زبانهٔ «بسته‌های دارایی» یک zip بارگذاری کنید (glb/fbx/obj/blend، BVH/FBX، HDRI)؛ وارسی و
        نصب خودکار است و دارایی‌ها همین‌جا و در ویرایشگر می‌آیند.
      </Muted>

      <ButtonTabs
        tabs={KINDS.map((k) => ({ id: k.id, label: `${k.name} (${fa((cat[k.id] || []).length)})` }))}
        value={kind}
        onChange={setKind}
      />

      {list.length === 0 ? (
        <Card>
          <EmptyState title="چیزی نیست" />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {list.map((a) => {
            const th = THUMBABLE.includes(kind) ? thumbUrl(kind, a) : null;
            const pv = kind === "motion" ? previewUrl("motion", a) : null;
            return (
              <Card key={a.id} padded={false}>
                {pv ? (
                  <video
                    src={pv}
                    muted
                    loop
                    playsInline
                    preload="none"
                    poster={th || undefined}
                    onMouseEnter={(e) => void e.currentTarget.play().catch(() => undefined)}
                    onMouseLeave={(e) => e.currentTarget.pause()}
                    style={{ width: "100%", display: "block", background: "#000", aspectRatio: "9 / 12", objectFit: "cover" }}
                  />
                ) : (
                  <div className="u3d-poster" style={{ aspectRatio: "1", backgroundImage: th ? `url('${th}')` : undefined }}>
                    {!th && <Icon name="box" size={30} />}
                  </div>
                )}
                <div className="px-3 py-2.5">
                  <b className="text-sm" style={{ color: "var(--text)" }}>
                    {label(a)}
                  </b>{" "}
                  <span className="u3d-mono text-xs" style={{ color: "var(--text-3)" }}>
                    {a.id}
                  </span>{" "}
                  {a.pack && <Badge tone="brand">بسته: {a.pack}</Badge>}
                  <div className="mt-0.5 text-xs" style={{ color: "var(--text-2)" }}>
                    {desc(a)}
                  </div>
                  <div className="text-xs" style={{ color: "var(--text-3)" }}>
                    {meta(kind, a)}
                  </div>
                  {a.license && (
                    <div className="text-xs" style={{ color: "var(--text-3)" }}>
                      مجوز: {a.license}
                    </div>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
