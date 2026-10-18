import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Input,
  PageHeader,
  SectionTitle,
  Spinner,
  Table,
  fa,
} from "../../components/ui";

type Key = {
  id: number;
  name: string;
  prefix: string;
  scopes: string[];
  is_active: boolean;
  usable: boolean;
  is_test: boolean;
  is_expired: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  call_count: number;
  created_at: string;
};

type Endpoint = {
  scope: string;
  title: string;
  method: string;
  path: string;
  sync: boolean;
  body: Record<string, unknown> | null;
  note: string;
};

type Sandbox = { how: string; note: string; marker: string };

type Payload = {
  keys: Key[];
  endpoints: Endpoint[];
  base_url: string;
  header: string;
  sandbox: Sandbox;
};

type Call = {
  endpoint: string;
  status: number;
  ms: number;
  error: string;
  key: string;
  at: string;
};

function when(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("fa-IR", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

/** A copyable cURL for one endpoint, with this shop's real base URL in it. */
function curlFor(endpoint: Endpoint, baseUrl: string, header: string): string {
  const origin = baseUrl.replace(/\/api\/v1\/public\/?$/, "");
  const lines = [
    `curl -X ${endpoint.method} '${origin}${endpoint.path}'`,
    `  -H '${header}: YOUR_KEY'`,
  ];
  if (endpoint.body) {
    lines.push("  -H 'Content-Type: application/json'");
    lines.push(`  -d '${JSON.stringify(endpoint.body)}'`);
  }
  return lines.join(" \\\n");
}

/**
 * Keys, documentation and the call log, on one page.
 *
 * The documentation is rendered from what the server sends rather than written
 * here, for the same reason it lives next to the views: a copy drifts, and a
 * shop debugging at midnight against stale docs concludes our API is broken.
 *
 * The new key's plaintext is shown in a panel that has to be dismissed on
 * purpose. It genuinely cannot be recovered — we keep only a hash — so a toast
 * that disappears after four seconds would be a design that loses credentials.
 */
export default function ApiKeysPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Payload | null>(null);
  const [calls, setCalls] = useState<Call[] | null>(null);
  const [failedCount, setFailedCount] = useState(0);
  const [name, setName] = useState("");
  const [isTest, setIsTest] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [warning, setWarning] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openDoc, setOpenDoc] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: body } = await api.get(`/stores/${id}/api-keys/`);
      setData(body);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function loadCalls() {
    try {
      const { data: body } = await api.get(`/stores/${id}/api-usage/`);
      setCalls(body.calls);
      setFailedCount(body.failed);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function create() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const { data: body } = await api.post(`/stores/${id}/api-keys/`, {
        name: name.trim(),
        test: isTest,
      });
      setSecret(body.secret);
      setWarning(body.warning);
      setName("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function revoke(key: Key) {
    // Irreversible for anything using it, so it gets a confirmation naming the
    // key — "کلید ۳" is not enough to know what breaks.
    const ok = window.confirm(
      `کلید «${key.name}» باطل شود؟ هر سیستمی که با آن کار می‌کند بلافاصله قطع می‌شود.`,
    );
    if (!ok) return;
    setError(null);
    try {
      await api.delete(`/stores/${id}/api-keys/${key.id}/`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      window.setTimeout(() => setCopied(null), 2000);
    } catch {
      // Clipboard is blocked on insecure origins; the text is on screen anyway.
      setCopied(null);
    }
  }

  if (data === null && error === null) return <Spinner />;

  return (
    <>
      <PageHeader
        title="API و اتصال به سیستم خودتان"
        subtitle="همان موتوری که پنل استفاده می‌کند، از کد خودتان"
        actions={
          <Link to={`/stores/${id}`}>
            <Button variant="secondary">بازگشت</Button>
          </Link>
        }
      />

      <ErrorBox message={error} />

      {secret && (
        <div className="mb-6">
          <Alert tone="warn" title="کلید تازه — همین حالا ذخیره‌اش کنید">
            <p className="mb-2">{warning}</p>
            <div
              className="mb-2 rounded-lg p-2 font-mono text-xs"
              style={{ background: "var(--surface-2)", color: "var(--text)" }}
              dir="ltr"
            >
              <span className="break-all">{secret}</span>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => copy(secret, "secret")}>
                {copied === "secret" ? "کپی شد ✓" : "کپی"}
              </Button>
              <Button variant="ghost" onClick={() => setSecret(null)}>
                ذخیره‌اش کردم، ببند
              </Button>
            </div>
          </Alert>
        </div>
      )}

      <Card>
        <SectionTitle>کلید تازه</SectionTitle>
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[14rem] flex-1">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="این کلید برای کجاست؟ مثلاً «سایت فروشگاه»"
            />
          </div>
          <Button onClick={create} disabled={busy || !name.trim()}>
            {busy ? "…" : "بساز"}
          </Button>
        </div>

        <label className="mt-3 flex cursor-pointer items-start gap-2">
          <input
            type="checkbox"
            className="mt-1"
            checked={isTest}
            onChange={(e) => setIsTest(e.target.checked)}
          />
          <span className="text-sm" style={{ color: "var(--text-2)" }}>
            کلید تست — هیچ پردازشی انجام نمی‌دهد و از سهمیه‌ی شما چیزی کم
            نمی‌کند.{" "}
            {data?.sandbox && (
              <span style={{ color: "var(--text-3)" }}>{data.sandbox.note}</span>
            )}
          </span>
        </label>

        <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
          برای هر سیستمی یک کلید جدا بسازید. آن‌وقت اگر یکی لو رفت، فقط همان را
          باطل می‌کنید و بقیه کار می‌کنند.
        </p>
      </Card>

      <div className="mt-6">
        <SectionTitle>کلیدهای شما</SectionTitle>
        {!data?.keys.length ? (
          <Card>
            <EmptyState
              icon="key"
              title="هنوز کلیدی نساخته‌اید"
              description="با یک کلید، سایت یا اپ خودتان می‌تواند مستقیم از همین امکانات استفاده کند."
            />
          </Card>
        ) : (
          <Card>
            <Table>
              <thead>
                <tr>
                  <th>نام</th>
                  <th>کلید</th>
                  <th>وضعیت</th>
                  <th>آخرین استفاده</th>
                  <th>تعداد فراخوانی</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.keys.map((key) => (
                  <tr key={key.id}>
                    <td>{key.name}</td>
                    <td dir="ltr" className="font-mono text-xs">
                      {key.prefix}…
                    </td>
                    <td>
                      {key.is_test ? (
                        <Badge tone="brand">تست</Badge>
                      ) : key.usable ? (
                        <Badge tone="ok">فعال</Badge>
                      ) : key.is_expired ? (
                        <Badge tone="warn">منقضی</Badge>
                      ) : (
                        <Badge tone="bad">باطل‌شده</Badge>
                      )}
                    </td>
                    <td>{when(key.last_used_at)}</td>
                    <td>{fa(key.call_count)}</td>
                    <td>
                      {key.is_active && (
                        <Button variant="ghost" onClick={() => revoke(key)}>
                          باطل کن
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <p className="mt-3 text-xs" style={{ color: "var(--text-3)" }}>
              کلید باطل‌شده پاک نمی‌شود تا بعداً بتوانید بفهمید کدام کلید چه
              درخواستی فرستاده بود.
            </p>
          </Card>
        )}
      </div>

      <div className="mt-8">
        <SectionTitle>چطور صدا بزنیم</SectionTitle>
        <Card>
          <div className="mb-4 text-sm leading-7" style={{ color: "var(--text-2)" }}>
            کلید را در هدر <code dir="ltr">{data?.header}</code> بفرستید. آدرس
            پایه:{" "}
            <code dir="ltr" className="break-all">
              {data?.base_url}
            </code>
          </div>
          <Alert tone="info" title="هزینه‌اش با پنل یکی است">
            یک کپشن از طریق API دقیقاً همان سهمیه‌ای را خرج می‌کند که همان کپشن
            از داخل پنل خرج می‌کرد — چون همان پردازش را می‌برد.
          </Alert>

          <div className="mt-4 flex flex-col gap-2">
            {data?.endpoints.map((endpoint) => (
              <div
                key={endpoint.scope}
                className="rounded-xl p-3"
                style={{ border: "1px solid var(--line)" }}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="brand">{endpoint.method}</Badge>
                    <span className="font-bold" style={{ color: "var(--text)" }}>
                      {endpoint.title}
                    </span>
                    <code dir="ltr" className="text-xs" style={{ color: "var(--text-3)" }}>
                      {endpoint.path}
                    </code>
                    <Badge tone={endpoint.sync ? "ok" : "neutral"}>
                      {endpoint.sync ? "جواب فوری" : "job_id می‌دهد"}
                    </Badge>
                  </div>
                  <Button
                    variant="ghost"
                    onClick={() =>
                      setOpenDoc(openDoc === endpoint.scope ? null : endpoint.scope)
                    }
                  >
                    {openDoc === endpoint.scope ? "بستن" : "نمونه کد"}
                  </Button>
                </div>
                <p className="mt-1 text-sm leading-7" style={{ color: "var(--text-2)" }}>
                  {endpoint.note}
                </p>
                {openDoc === endpoint.scope && data && (
                  <div className="mt-2">
                    <pre
                      dir="ltr"
                      className="overflow-x-auto rounded-lg p-3 text-xs"
                      style={{ background: "var(--surface-2)", color: "var(--text)" }}
                    >
                      {curlFor(endpoint, data.base_url, data.header)}
                    </pre>
                    <Button
                      variant="ghost"
                      onClick={() =>
                        copy(curlFor(endpoint, data.base_url, data.header), endpoint.scope)
                      }
                    >
                      {copied === endpoint.scope ? "کپی شد ✓" : "کپی دستور"}
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="mt-8">
        <SectionTitle>آخرین درخواست‌ها</SectionTitle>
        <Card>
          {calls === null ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm" style={{ color: "var(--text-2)" }}>
                اگر اتصالتان کار نمی‌کند، اینجا می‌بینید دقیقاً چه جوابی گرفته است.
              </p>
              <Button variant="secondary" onClick={loadCalls}>
                نشان بده
              </Button>
            </div>
          ) : calls.length === 0 ? (
            <EmptyState
              icon="empty"
              title="هنوز درخواستی نیامده"
              description="تا وقتی سیستم شما اولین درخواست را نفرستد، اینجا خالی است."
            />
          ) : (
            <>
              {failedCount > 0 && (
                <div className="mb-3">
                  <Alert tone="warn">
                    {fa(failedCount)} درخواست از {fa(calls.length)} تای اخیر خطا
                    گرفته است.
                  </Alert>
                </div>
              )}
              <Table>
                <thead>
                  <tr>
                    <th>زمان</th>
                    <th>سرویس</th>
                    <th>کلید</th>
                    <th>کد</th>
                    <th>مدت</th>
                    <th>خطا</th>
                  </tr>
                </thead>
                <tbody>
                  {calls.map((call, index) => (
                    <tr key={index}>
                      <td>{when(call.at)}</td>
                      <td dir="ltr" className="font-mono text-xs">
                        {call.endpoint}
                      </td>
                      <td>{call.key}</td>
                      <td>
                        <Badge tone={call.status >= 400 ? "bad" : "ok"}>
                          {fa(call.status)}
                        </Badge>
                      </td>
                      <td>{fa(call.ms)} ms</td>
                      <td className="text-xs" style={{ color: "var(--text-3)" }}>
                        {call.error || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </>
          )}
        </Card>
      </div>
    </>
  );
}
