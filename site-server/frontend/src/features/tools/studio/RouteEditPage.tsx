import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Badge, Button, Card, ErrorBox, Field, Input, Select } from "../../../components/ui";
import { api, pUrl, studioError } from "./api";
import { Loading, Pre, SectionHead } from "./common";
import { useProject } from "./shell";
import type { RouteResp, RouteT } from "./types";

/** ویرایشِ یک نشانی */
export default function RouteEditPage() {
  const { slug, notify } = useProject();
  const { pk = "" } = useParams<{ pk: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<RouteResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [app, setApp] = useState("");
  const [pattern, setPattern] = useState("");
  const [name, setName] = useState("");
  const [view, setView] = useState("");
  const [viewText, setViewText] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<RouteResp>(`/studio/projects/${slug}/routes/${pk}/`)
      .then((r) => {
        setData(r.data);
        const rt = r.data.route;
        setApp(rt.app ? String(rt.app) : "");
        setPattern(rt.pattern);
        setName(rt.name);
        setView(rt.view ? String(rt.view) : "");
        setViewText(rt.view_text);
      })
      .catch((err) => setError(studioError(err)));
  }, [slug, pk]);

  if (!data) return <Loading error={error} />;
  const r = data.route;

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data: d } = await api.put<{ route: RouteT; message: string }>(`/studio/projects/${slug}/routes/${pk}/`, {
        app,
        pattern,
        name,
        view,
        view_text: viewText,
      });
      notify(d.message);
      navigate(pUrl(slug, "urls"));
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="max-w-3xl">
      <form onSubmit={save} className="space-y-3">
        <SectionHead title="ویرایشِ نشانی" hint={<span dir="ltr" className="font-mono">/{r.full_pattern}</span>} action={!r.managed && <Badge>واردشده · فقط نمایش</Badge>} />
        <ErrorBox message={error} />
        <Field label="کجا">
          <Select value={app} onChange={(e) => setApp(e.target.value)} disabled={!r.managed}>
            <option value="">ریشه — config/urls.py</option>
            {data.apps.map((a) => (
              <option key={a.id} value={a.id}>
                اپِ {a.name} (/{a.effective_prefix}…)
              </option>
            ))}
          </Select>
        </Field>
        <Field label="الگو">
          <Input value={pattern} onChange={(e) => setPattern(e.target.value)} dir="ltr" disabled={!r.managed} />
        </Field>
        <Field label="نام">
          <Input value={name} onChange={(e) => setName(e.target.value)} dir="ltr" disabled={!r.managed} />
        </Field>
        <Field label="ویو">
          <Select value={view} onChange={(e) => setView(e.target.value)} disabled={!r.managed}>
            <option value="">— ویوی متنی —</option>
            {data.views.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label} — {v.kind_display}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="یا ویوی متنی">
          <Input value={viewText} onChange={(e) => setViewText(e.target.value)} dir="ltr" disabled={!r.managed} />
        </Field>
        <SectionHead title={<span className="text-sm">کد</span>} />
        <Pre text={r.code} />
        <div className="flex gap-2">
          {r.managed && (
            <Button type="submit" disabled={busy}>
              {busy ? "…" : "ذخیره"}
            </Button>
          )}
          <Link to={pUrl(slug, "urls")} className="no-underline">
            <Button type="button" variant="ghost">بازگشت</Button>
          </Link>
        </div>
      </form>
    </Card>
  );
}
