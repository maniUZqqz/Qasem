import { useEffect } from "react";

/** عنوانِ تبِ مرورگر را روی `title` می‌گذارد (`null` = دست نزن). ساختنِ خودِ متن با `tabTitle.ts` است. */
export function usePageTitle(title: string | null): void {
  useEffect(() => {
    if (title) document.title = title;
  }, [title]);
}

/** همان هوک، برای صفحه‌هایی که بیرونِ قابِ پنل‌اند (ورود، ثبت‌نام، …): `<PageTitle title="ورود | NMarketing" />`. */
export default function PageTitle({ title }: { title: string }) {
  usePageTitle(title);
  return null;
}
