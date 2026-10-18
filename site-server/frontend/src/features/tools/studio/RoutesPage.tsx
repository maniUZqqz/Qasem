import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, Card, Chip, ErrorBox, Field, Input, Select, Table } from "../../../components/ui";
import { api, pUrl, studioError } from "./api";
import { confirmDo, Help, Loading, Mono, SectionHead } from "./common";
import { useProject } from "./shell";
import type { RouteRow, RoutesResp } from "./types";

function SourceBadge({ r }: { r: RouteRow }) {
  if (r.source === "core") return <Badge>پایه</Badge>;
  if (r.source === "cart") return <Badge tone="brand">سبدِ خرید</Badge>;
  if (r.source === "page") return <Badge tone="brand">صفحه</Badge>;
  if (r.source === "root") return <Badge tone="warn">ریشه</Badge>;
  return <Badge tone="ok">{r.source.slice(4)}</Badge>;
}

/** نقشهٔ کاملِ نشانی‌های سایت + افزودنِ نشانی */
export default function RoutesPage() {
  const { slug, notify } = useProject();
  const [data, setData] = useState<RoutesResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [app, setApp] = useState("");
  const [pattern, setPattern] = useState("");
  const [name, setName] = useState("");
  const [view, setView] = useState("");
  const [viewText, setViewText] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<RoutesResp>(`/studio/projects/${slug}/routes/`);
      setData(d);
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      const { data: d } = await api.post<{ message: string }>(`/studio/projects/${slug}/routes/`, {
        app,
        pattern,
        name,
        view,
        view_text: viewText,
      });
      notify(d.message);
      setPattern("");
      setName("");
      setView("");
      setViewText("");
      await load();
    } catch (err) {
      setFormError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(r: RouteRow) {
    if (!r.route_id || !confirmDo(`نشانیِ /${r.pattern} حذف شود؟`)) return;
    try {
      const { data: d } = await api.delete<{ message: string }>(`/studio/projects/${slug}/routes/${r.route_id}/`);
      notify(d.message);
      await load();
    } catch (err) {
      notify(studioError(err), "bad");
    }
  }

  if (!data) return <Loading error={error} />;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card padded={false}>
        <div className="px-5 pt-5">
          <SectionHead
            title="نقشهٔ کاملِ نشانی‌های سایت"
            hint={
              <>
                همان چیزی که در <Mono>config/urls.py</Mono> و urls.py ِ اپ‌ها نوشته می‌شود
              </>
            }
          />
        </div>
        <Table>
          <thead>
            <tr>
              <th>نشانی</th>
              <th>نام</th>
              <th>ویو</th>
              <th>منبع</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r, i) => (
              <tr key={i}>
                <td dir="ltr" className="whitespace-nowrap font-mono text-xs" style={{ textAlign: "left" }}>
                  {r.live ? (
                    <a href={r.live} target="_blank" rel="noreferrer" style={{ color: "var(--brand-strong)" }}>
                      /{r.pattern}
                    </a>
                  ) : (
                    `/${r.pattern}`
                  )}
                </td>
                <td className="font-mono text-xs">{r.name || "—"}</td>
                <td dir="ltr" className="font-mono text-xs" style={{ textAlign: "left" }}>
                  {r.route_view_id ? (
                    <Link to={pUrl(slug, `view/${r.route_view_id}`)} style={{ color: "var(--brand-strong)" }}>
                      {r.view}
                    </Link>
                  ) : (
                    r.view
                  )}
                </td>
                <td>
                  <span className="inline-flex flex-wrap gap-1">
                    {r.source === "page" && r.page_id ? (
                      <Link to={pUrl(slug, `page/${r.page_id}`)} className="no-underline">
                        <SourceBadge r={r} />
                      </Link>
                    ) : (
                      <SourceBadge r={r} />
                    )}
                    {r.route_id && r.route_managed === false && <Badge>واردشده</Badge>}
                  </span>
                </td>
                <td className="whitespace-nowrap">
                  {r.editable && r.route_id && (
                    <>
                      <Link to={pUrl(slug, `urls/${r.route_id}`)} className="no-underline">
                        <Button variant="ghost" size="sm">ویرایش</Button>
                      </Link>
                      <Button variant="ghost" size="sm" style={{ color: "var(--bad)" }} onClick={() => remove(r)}>
                        حذف
                      </Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
        <div className="px-5 pb-5">
          <Help>
            نشانی‌های «صفحه» از «فرانت» و نشانی‌های «سبدِ خرید» از قالبِ فروشگاه می‌آیند. اگر پیش‌نمایش روشن باشد، نشانی‌ها لینکِ
            زنده دارند.
          </Help>
        </div>
      </Card>

      <div className="space-y-4">
        <Card>
          <form onSubmit={add} className="space-y-3">
            <SectionHead title="+ نشانیِ تازه" />
            <ErrorBox message={formError} />
            <Field label="کجا">
              <Select value={app} onChange={(e) => setApp(e.target.value)}>
                <option value="">ریشه — config/urls.py</option>
                {data.apps.map((a) => (
                  <option key={a.id} value={a.id}>
                    اپِ {a.name} (/{a.effective_prefix}…)
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="الگو">
              <Input value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="about/  یا  post/<int:pk>/" dir="ltr" />
            </Field>
            <Help>
              مبدل‌های جنگو: <Mono>{"<int:pk>"}</Mono> <Mono>{"<slug:slug>"}</Mono> <Mono>{"<str:name>"}</Mono>
            </Help>
            <Field label={"نام (برای {% url %})"}>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="about" dir="ltr" />
            </Field>
            <Field label="ویو">
              <Select value={view} onChange={(e) => setView(e.target.value)}>
                <option value="">— ویوی متنی (پایین) —</option>
                {data.views.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label} — {v.kind_display}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="یا ویوی متنی">
              <Input value={viewText} onChange={(e) => setViewText(e.target.value)} placeholder="views.page_home" dir="ltr" />
            </Field>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "…" : "افزودنِ نشانی"}
            </Button>
          </form>
        </Card>
        <Card>
          <SectionHead title="ویوی تازه" />
          <p className="mb-2 text-sm" style={{ color: "var(--text-3)" }}>
            ویوها مالِ اپ‌ها هستند. سریع‌ترین راه: در صفحهٔ هر مدل «صفحه‌های CRUD با یک کلیک».
          </p>
          <div className="flex flex-wrap gap-1.5">
            {data.apps.length === 0 && (
              <span className="text-sm" style={{ color: "var(--text-3)" }}>
                اول یک اپ بساز.
              </span>
            )}
            {data.apps.map((a) => (
              <Link key={a.id} to={`${pUrl(slug, `app/${a.id}`)}?tab=views`} className="no-underline">
                <Chip>{a.name}</Chip>
              </Link>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
