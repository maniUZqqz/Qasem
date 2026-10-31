import { Link } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Button, Card } from "../../../components/ui";
import { pUrl } from "./api";

/** نشانیِ ویرایشگرِ دیداریِ یک صفحه */
export function openVisual(slug: string, pageId: number): string {
  return pUrl(slug, `builder/page/${pageId}`);
}

/** کارتِ نمای کلی: راهِ مستقیم به ویرایشگرِ دیداری */
export function VisualCta({ slug }: { slug: string }) {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <b style={{ color: "var(--text)" }}>ظاهرِ سایت را با کشیدن و زدن بساز</b>
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            صفحه‌ها، سربرگ، منو، رنگ‌ها و تصویرها؛ بی‌هیچ کدی.
          </p>
        </div>
        <Link to={pUrl(slug, "frontend")} className="no-underline">
          <Button>
            <Icon name="image" size={15} />
            بازکردنِ صفحه‌ها
          </Button>
        </Link>
      </div>
    </Card>
  );
}
