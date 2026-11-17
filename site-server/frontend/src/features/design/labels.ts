import type { BlockCatalog, SiteInfo } from "./api";

type Node = Record<string, any>;

const PRIM_FA: Record<string, string> = { frame: "قاب Auto Layout", text: "متن", button: "دکمه", image: "تصویر", rect: "مستطیل", input: "فیلد", spacer: "فاصله", icon: "نماد" };

/** نامِ یک لایه در فهرست. فرزندِ یک «بخش» فقط «type» دارد و «t» ندارد؛ پس هر دو شکل پشتیبانی می‌شود و هرگز «undefined» نشان داده نمی‌شود. */
export function nodeLabel(n: Node, catalog: BlockCatalog | null): string {
  const kind = n.type != null ? String(n.type) : "";
  if (kind === "c21") return "قطعهٔ 21st.dev";                                   // قطعهٔ آمادهٔ 21st.dev (منبعِ طراحی)
  if (n.t === "block" || (n.t == null && kind)) return catalog?.blocks.find((b) => b.type === kind)?.label ?? PRIM_FA[kind] ?? (kind || "لایه");
  return n.name || PRIM_FA[String(n.t)] || "لایه";
}

/** پیوندِ «بازکردن در سایت‌ساز»: ویرایشگرِ صفحهٔ اصلی (نیازمندِ شناسهٔ صفحه)، یا اگر نبود نمای کلیِ پروژه. */
export function siteBuilderPath(site: SiteInfo): string {
  const pid = site.pages?.[0]?.page_id;
  return pid ? `/tools/studio/p/${site.slug}/builder/page/${pid}` : `/tools/studio/p/${site.slug}`;
}
