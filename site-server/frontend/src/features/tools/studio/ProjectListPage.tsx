import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, Chip, EmptyState } from "../../../components/ui";
import { api, BASE, fa, fmtDate, pUrl, studioError, truncate } from "./api";
import { Loading, statusTone } from "./common";
import type { ProjectListItem } from "./types";

/** فهرستِ پروژه‌ها — صفحهٔ اولِ سایت‌ساز */
export default function ProjectListPage() {
  const [items, setItems] = useState<ProjectListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ProjectListItem[]>("/studio/projects/")
      .then((r) => setItems(r.data))
      .catch((err) => setError(studioError(err)));
  }, []);

  if (!items) return <Loading error={error} />;

  return (
    <div className="space-y-5">
      <Card>
        <h2 className="text-xl font-extrabold" style={{ color: "var(--text)" }}>
          فروشگاهِ جنگوی خودت را بساز
        </h2>
        <p className="mt-2 max-w-3xl text-sm leading-7" style={{ color: "var(--text-2)" }}>
          تنظیمات، اپ‌ها، مدل‌ها، ویوها و نشانی‌ها را گرافیکی تعریف کن؛ فرانت را با هوشِ مصنوعی بساز و
          صفحه‌به‌صفحه ویرایش کن؛ و یک پروژهٔ واقعیِ Django تحویل بگیر که بدونِ استودیو روی هر سروری اجرا
          می‌شود.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link to={`${BASE}/new`} className="no-underline">
            <Button>
              <Icon name="plus" size={15} />
              پروژهٔ تازه
            </Button>
          </Link>
          <Link to={`${BASE}/import`} className="no-underline">
            <Button variant="secondary">
              <Icon name="upload" size={15} />
              واردکردنِ پروژهٔ جنگوی موجود
            </Button>
          </Link>
        </div>
      </Card>

      {items.length === 0 ? (
        <Card>
          <EmptyState icon="box" title="هنوز پروژه‌ای نساخته‌ای">
            با «پروژهٔ تازه» شروع کن — با تیکِ «قالبِ استاندارد» یک فروشگاهِ کامل (کاتالوگ، سبد، تسویه‌حساب)
            ساخته می‌شود. یا یک پروژهٔ جنگوی قبلی را «وارد» کن.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((pr) => (
            <Link key={pr.id} to={pUrl(pr.slug)} className="no-underline" style={{ color: "inherit" }}>
              <Card hover className="h-full">
                <div className="mb-2 flex items-center gap-2">
                  <span
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-xl text-base font-black"
                    style={{ background: pr.brand_color, color: "#fff" }}
                  >
                    {pr.name.slice(0, 1)}
                  </span>
                  <h3 className="min-w-0 flex-1 truncate text-base font-bold" style={{ color: "var(--text)" }}>
                    {pr.name}
                  </h3>
                  <Badge tone={statusTone(pr.status)}>{truncate(pr.status_display, 14)}</Badge>
                </div>
                <p className="mb-3 min-h-[2.5rem] text-sm leading-6" style={{ color: "var(--text-3)" }}>
                  {truncate(pr.description || "بدونِ توضیح", 110)}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {pr.is_imported && <Badge tone="brand">واردشده</Badge>}
                  <Chip>{fa(pr.app_count)} اپ</Chip>
                  <Chip>
                    {fa(pr.page_count)} {pr.is_imported ? "قالب" : "صفحه"}
                  </Chip>
                  <Chip>
                    <span dir="ltr" className="font-mono">
                      {pr.slug}
                    </span>
                  </Chip>
                  {pr.preview_running && <Badge tone="ok">● پیش‌نمایش روشن</Badge>}
                </div>
                <div className="mt-3 text-xs" style={{ color: "var(--text-3)" }}>
                  آخرین تولید: {fmtDate(pr.generated_at)}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
