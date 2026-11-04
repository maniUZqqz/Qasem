import Icon from "../../../components/Icon";
import { Button, fa } from "../../../components/ui";

/** «۱ تا ۲۵ از ۱٬۲۴۰» with previous / next. `page` starts at 1. */
export default function Pagination({
  page,
  pageSize,
  count,
  onPage,
  disabled = false,
}: {
  page: number;
  pageSize: number;
  count: number;
  onPage: (page: number) => void;
  disabled?: boolean;
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  const from = count === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(count, page * pageSize);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 px-1 py-2 text-sm" style={{ color: "var(--text-3)" }} data-testid="pagination">
      <span>
        {fa(from)} تا {fa(to)} از {fa(count.toLocaleString("en-US")).replace(/,/g, "٬")}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" onClick={() => onPage(page - 1)} disabled={disabled || page <= 1} aria-label="صفحهٔ قبل">
          <Icon name="back" size={14} />
          قبلی
        </Button>
        <span className="u-num" style={{ color: "var(--text-2)" }}>
          {fa(page)} / {fa(pages)}
        </span>
        <Button variant="secondary" size="sm" onClick={() => onPage(page + 1)} disabled={disabled || page >= pages} aria-label="صفحهٔ بعد">
          بعدی
          <Icon name="next" size={14} />
        </Button>
      </div>
    </div>
  );
}
