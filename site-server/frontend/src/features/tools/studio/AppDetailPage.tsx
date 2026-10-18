import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Badge, Button, Card, Chip, EmptyState, ErrorBox, Field, Input, Select, Table } from "../../../components/ui";
import { api, fa, fieldErrors, pUrl, studioError, truncate } from "./api";
import { Check, confirmDo, Help, Loading, Mono, Pre, SectionHead, Tabs } from "./common";
import { useProject } from "./shell";
import type { AppDetailResp, AppT, ModelT, ViewT } from "./types";

type Tab = "models" | "views" | "code" | "props";
const NEEDS_MODEL = new Set(["list", "detail", "create", "update", "delete"]);
const CUSTOM_MARK = "# ── studio:custom";

/** یک اپ: مدل‌ها، ویوها و نشانی‌ها، کد، مشخصات */
export default function AppDetailPage() {
  const { slug, notify } = useProject();
  const { pk = "" } = useParams<{ pk: string }>();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = ((params.get("tab") as Tab | null) ?? "models") as Tab;
  const [data, setData] = useState<AppDetailResp | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<AppDetailResp>(`/studio/projects/${slug}/apps/${pk}/`);
      setData(d);
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug, pk]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!data) return <Loading error={error} />;
  const app = data.app;
  const setTab = (t: Tab) => setParams(t === "models" ? {} : { tab: t });

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <Icon name="box" size={22} />
          <div className="min-w-0">
            <h2 className="font-mono text-lg font-bold" dir="ltr" style={{ color: "var(--text)", textAlign: "left" }}>
              {app.dir}
            </h2>
            <div className="text-sm" style={{ color: "var(--text-3)" }}>
              {app.verbose_name_fa || "—"}
              {app.description ? ` · ${app.description}` : ""}
            </div>
          </div>
          <Badge>
            <Mono>/{app.effective_prefix || "?"}</Mono>
          </Badge>
          {app.is_core && <Badge tone="brand">پایهٔ فروشگاه</Badge>}
          {!app.managed && <Badge>واردشده · فقط نمایش</Badge>}
          <Link to={pUrl(slug, "backend")} className="u-back ms-auto">
            <Icon name="back" size={14} />
            اپ‌ها
          </Link>
        </div>
      </Card>

      <Tabs<Tab>
        tabs={[
          { key: "models", label: "مدل‌ها", count: data.models.length },
          { key: "views", label: "ویوها و نشانی‌ها", count: data.views.length },
          { key: "code", label: "کد" },
          ...(app.managed ? [{ key: "props" as Tab, label: "مشخصات" }] : []),
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === "models" && <ModelsTab data={data} slug={slug} onAdded={(m, msg) => { notify(msg); navigate(pUrl(slug, `model/${m.id}`)); }} />}
      {tab === "views" && <ViewsTab data={data} slug={slug} onAdded={(v, msg) => { notify(msg); navigate(pUrl(slug, `view/${v.id}`)); }} />}
      {tab === "code" && <CodeTab data={data} />}
      {tab === "props" && app.managed && (
        <PropsTab
          data={data}
          slug={slug}
          onSaved={(a, msg) => {
            notify(msg);
            setData({ ...data, app: a });
          }}
          onDeleted={(msg) => {
            notify(msg);
            navigate(pUrl(slug, "backend"));
          }}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------ مدل‌ها */
function ModelsTab({ data, slug, onAdded }: { data: AppDetailResp; slug: string; onAdded: (m: ModelT, msg: string) => void }) {
  const [name, setName] = useState("");
  const [faName, setFaName] = useState("");
  const [plural, setPlural] = useState("");
  const [starter, setStarter] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data: d } = await api.post<{ model: ModelT; message: string }>(`/studio/projects/${slug}/models/`, {
        app: data.app.id,
        name,
        fa: faName,
        fa_plural: plural,
        starter,
      });
      onAdded(d.model, d.message);
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-4">
        {data.models.length === 0 && (
          <Card>
            <EmptyState title="این اپ هنوز مدلی ندارد">{data.app.managed ? "از فرمِ کنار یک مدل (جدولِ دیتابیس) بساز." : "مدلی شناسایی نشد."}</EmptyState>
          </Card>
        )}
        {data.models.map((m) => (
          <Card key={m.id}>
            <SectionHead
              title={
                <Link to={pUrl(slug, `model/${m.id}`)} style={{ color: "var(--brand-strong)" }}>
                  {m.name}
                </Link>
              }
              hint={m.verbose_name_fa}
              action={
                <Link to={pUrl(slug, `model/${m.id}`)} className="no-underline">
                  <Button variant="ghost" size="sm">ویرایش</Button>
                </Link>
              }
            />
            <div className="flex flex-wrap gap-1.5">
              {(m.fields ?? []).length === 0 && (
                <span className="text-xs" style={{ color: "var(--text-3)" }}>
                  هنوز فیلدی ندارد
                </span>
              )}
              {(m.fields ?? []).map((f) => (
                <Chip key={f.id}>
                  <b className="font-mono" dir="ltr">
                    {f.name}
                  </b>{" "}
                  <span style={{ color: "var(--text-3)" }}>{f.field_type_display}</span>
                </Chip>
              ))}
            </div>
          </Card>
        ))}
      </div>
      {data.app.managed && (
        <Card className="self-start">
          <form onSubmit={submit} className="space-y-3">
            <SectionHead title="+ مدلِ تازه" hint="یک جدول" />
            <ErrorBox message={error} />
            <Field label="نامِ مدل (انگلیسی)">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Post" required dir="ltr" />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="نامِ فارسی">
                <Input value={faName} onChange={(e) => setFaName(e.target.value)} placeholder="نوشته" />
              </Field>
              <Field label="جمع">
                <Input value={plural} onChange={(e) => setPlural(e.target.value)} placeholder="نوشته‌ها" />
              </Field>
            </div>
            <Check label="با فیلدهای شروع (title، created_at)" checked={starter} onChange={setStarter} />
            <Button type="submit" className="w-full" disabled={busy || !name.trim()}>
              {busy ? "…" : "ساختِ مدل"}
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ ویوها */
function ViewsTab({ data, slug, onAdded }: { data: AppDetailResp; slug: string; onAdded: (v: ViewT, msg: string) => void }) {
  const [kind, setKind] = useState(data.kinds[0]?.[0] ?? "list");
  const own = data.all_models.filter((m) => m.app_id === data.app.id);
  const others = data.all_models.filter((m) => m.app_id !== data.app.id);
  const [model, setModel] = useState<string>(String(own[0]?.id ?? others[0]?.id ?? ""));
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [route, setRoute] = useState(true);
  const [login, setLogin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setErrors({});
    try {
      const { data: d } = await api.post<{ view: ViewT; message: string }>(`/studio/projects/${slug}/views/`, {
        app: data.app.id,
        kind,
        model: NEEDS_MODEL.has(kind) ? model : "",
        name,
        description,
        route,
        login_required: login,
      });
      onAdded(d.view, d.message);
    } catch (err) {
      setError(studioError(err));
      setErrors(fieldErrors(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card padded={false}>
        <div className="px-5 pt-5">
          <SectionHead
            title="ویوهای این اپ"
            action={
              <Link to={pUrl(slug, "urls")} className="no-underline">
                <Button variant="ghost" size="sm">نقشهٔ همهٔ نشانی‌ها</Button>
              </Link>
            }
          />
        </div>
        {data.views.length === 0 ? (
          <EmptyState title="هنوز ویویی نیست">از فرمِ کنار بساز — یا در صفحهٔ هر مدل «CRUD با یک کلیک».</EmptyState>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>ویو</th>
                <th>نوع</th>
                <th>مدل</th>
                <th>نشانی</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.views.map((v) => (
                <tr key={v.id}>
                  <td>
                    <Link to={pUrl(slug, `view/${v.id}`)} className="font-mono" dir="ltr" style={{ color: "var(--brand-strong)" }}>
                      {v.name}
                    </Link>
                    {v.login_required && (
                      <span className="ms-1">
                        <Badge>ورود</Badge>
                      </span>
                    )}
                    {v.description && (
                      <div className="text-xs" style={{ color: "var(--text-3)" }}>
                        {truncate(v.description, 60)}
                      </div>
                    )}
                  </td>
                  <td>{v.kind_display}</td>
                  <td>{v.model_name ? <Mono>{v.model_name}</Mono> : "—"}</td>
                  <td>
                    {(v.routes ?? []).length === 0 ? (
                      <span style={{ color: "var(--text-3)" }}>بی‌نشانی</span>
                    ) : (
                      (v.routes ?? []).map((r) => (
                        <div key={r.id} dir="ltr" className="font-mono text-xs" style={{ textAlign: "left" }}>
                          /{r.full_pattern}
                          {r.name && <span style={{ color: "var(--text-3)" }}> · {r.name}</span>}
                        </div>
                      ))
                    )}
                  </td>
                  <td>
                    <Link to={pUrl(slug, `view/${v.id}`)} className="no-underline">
                      <Button variant="ghost" size="sm">{v.managed ? "ویرایش" : "دیدن"}</Button>
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {!data.app.managed && data.routes.length > 0 && (
          <div className="px-5 pb-5">
            <SectionHead title={<span className="text-sm">نشانی‌های urls.py ِ این اپ</span>} />
            <Table>
              <tbody>
                {data.routes.map((r) => (
                  <tr key={r.id}>
                    <td dir="ltr" className="font-mono text-xs">
                      /{r.full_pattern}
                    </td>
                    <td dir="ltr" className="font-mono text-xs">
                      {r.view_text}
                    </td>
                    <td className="font-mono text-xs">{r.name}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </Card>

      {data.app.managed && (
        <Card className="self-start">
          <form onSubmit={submit} className="space-y-3">
            <SectionHead title="+ ویوِ تازه" hint="idea.md §۵.۴" />
            <ErrorBox message={error} />
            <Field label="نوع">
              <Select value={kind} onChange={(e) => setKind(e.target.value)}>
                {data.kinds.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </Select>
            </Field>
            {NEEDS_MODEL.has(kind) && (
              <Field label="مدل" hint={errors.model}>
                <Select value={model} onChange={(e) => setModel(e.target.value)}>
                  {own.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                  {others.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <Field label="نام (خالی = خودکار، مثلاً post_list)" hint={errors.name}>
              <Input value={name} onChange={(e) => setName(e.target.value)} dir="ltr" placeholder="post_list" />
            </Field>
            <Field label="توضیح">
              <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="فهرستِ نوشته‌ها" />
            </Field>
            <div className="flex flex-wrap gap-4">
              <Check label="نشانی هم بساز" checked={route} onChange={setRoute} />
              <Check label="فقط با ورود" checked={login} onChange={setLogin} />
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "…" : "ساختِ ویو"}
            </Button>
            <Help>
              ویوهای استاندارد کلاس‌محورِ خودِ جنگو هستند (ListView، DetailView…) و قالبِ پیش‌فرض هم می‌گیرند. «دستی» = کدِ
              پایتونِ خودت.
            </Help>
          </form>
        </Card>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ کد */
function CodeTab({ data }: { data: AppDetailResp }) {
  const [file, setFile] = useState(data.code_keys[0] ?? "");
  if (!data.code_keys.length) {
    return (
      <Card>
        <EmptyState title="کدی نیست" />
      </Card>
    );
  }
  return (
    <Card>
      <Tabs<string> tabs={data.code_keys.map((k) => ({ key: k, label: k }))} active={file} onChange={setFile} mono />
      <Pre text={data.code[file] ?? ""} mark={CUSTOM_MARK} maxHeight="calc(100vh - 300px)" />
      <Help>
        {data.app.managed ? (
          <>
            این دقیقاً همان کدی است که با «تولیدِ کد» روی دیسک نوشته می‌شود. کدِ دستیِ خودت را در فایل، زیرِ خطِ{" "}
            <Mono>studio:custom</Mono> بنویس — با تولیدِ دوباره پاک نمی‌شود.
          </>
        ) : (
          "کدِ اصلیِ پروژهٔ واردشده (دست‌نخورده)."
        )}
      </Help>
    </Card>
  );
}

/* ------------------------------------------------------------ مشخصات */
function PropsTab({
  data,
  slug,
  onSaved,
  onDeleted,
}: {
  data: AppDetailResp;
  slug: string;
  onSaved: (a: AppT, msg: string) => void;
  onDeleted: (msg: string) => void;
}) {
  const app = data.app;
  const [faName, setFaName] = useState(app.verbose_name_fa);
  const [description, setDescription] = useState(app.description);
  const [prefix, setPrefix] = useState(app.url_prefix);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data: d } = await api.put<{ app: AppT; message: string }>(`/studio/projects/${slug}/apps/${app.id}/`, {
        fa: faName,
        description,
        url_prefix: prefix,
      });
      onSaved(d.app, d.message);
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirmDo(`اپِ ${app.name} با همهٔ مدل‌ها، ویوها و نشانی‌هایش از تعریف‌ها حذف شود؟`)) return;
    setError(null);
    try {
      const { data: d } = await api.delete<{ message: string }>(`/studio/projects/${slug}/apps/${app.id}/`);
      onDeleted(d.message);
    } catch (err) {
      setError(studioError(err));
    }
  }

  return (
    <div className="max-w-3xl space-y-4">
      <Card>
        <form onSubmit={save} className="space-y-3">
          <SectionHead title="مشخصاتِ اپ" />
          <ErrorBox message={error} />
          <Field label="نامِ انگلیسی" hint="نامِ اپ بعد از ساخت عوض نمی‌شود (جدول‌های دیتابیس به آن گره خورده‌اند).">
            <Input value={app.name} disabled dir="ltr" />
          </Field>
          <Field label="نامِ فارسی">
            <Input value={faName} onChange={(e) => setFaName(e.target.value)} />
          </Field>
          <Field label="مسئولیت">
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <Field label="پیشوندِ نشانی">
            <Input value={prefix} onChange={(e) => setPrefix(e.target.value)} dir="ltr" placeholder={`${app.name}/`} />
          </Field>
          <Button type="submit" disabled={busy}>
            {busy ? "…" : "ذخیره"}
          </Button>
        </form>
      </Card>
      <Card>
        <SectionHead tone="bad" title="حذفِ اپ" />
        <p className="mb-3 text-sm" style={{ color: "var(--text-3)" }}>
          مدل‌ها، ویوها و نشانی‌های این اپ از تعریف‌ها پاک می‌شوند. پوشه‌اش روی دیسک برای احتیاط می‌ماند.
        </p>
        <Button variant="danger" onClick={remove}>
          <Icon name="trash" size={14} />
          حذفِ اپ
        </Button>
      </Card>
      <p className="text-xs" style={{ color: "var(--text-3)" }}>
        {fa(data.models.length)} مدل · {fa(data.views.length)} ویو در این اپ
      </p>
    </div>
  );
}
