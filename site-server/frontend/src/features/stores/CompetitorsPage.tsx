import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Input,
  PageHeader,
  SectionTitle,
  Select,
  Spinner,
  Table,
  fa,
  toman,
} from "../../components/ui";

type CompetitorProduct = {
  id: number;
  name: string;
  url: string;
  price_toman: number | null;
  observed_at: string | null;
  matches: number | null;
  source: string;
};

type Competitor = {
  id: number;
  name: string;
  kind: string;
  website: string;
  instagram: string;
  notes: string;
  revenue_model: string;
  positioning: string;
  strengths: string[];
  weaknesses: string[];
  analysed_at: string | null;
  is_stale: boolean;
  products: CompetitorProduct[];
};

const KIND_LABEL: Record<string, string> = {
  DIRECT: "رقیب مستقیم",
  ADJACENT: "رقیب غیرمستقیم",
  MARKETPLACE: "مارکت‌پلیس",
};

/**
 * Who else sells this, and for how much.
 *
 * Two things this page insists on, because both decide whether a shop can act
 * on what it sees: every recorded price shows **the day it was observed**, and
 * conclusions older than a month are marked stale. A price with no date is a
 * claim, and repricing against one is how a shop loses money confidently.
 */
export default function CompetitorsPage() {
  const { id } = useParams<{ id: string }>();
  const [rows, setRows] = useState<Competitor[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState("");
  const [kind, setKind] = useState("DIRECT");
  const [website, setWebsite] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/stores/${id}/competitors/`);
      setRows(data);
    } catch (err) {
      setError(errorMessage(err));
      setRows([]);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function add(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`/stores/${id}/competitors/`, { name, kind, website });
      setName("");
      setWebsite("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(competitor: Competitor) {
    setError(null);
    try {
      await api.delete(`/stores/${id}/competitors/${competitor.id}/`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (rows === null) return <Spinner />;

  return (
    <>
      <PageHeader
        title="رقبا"
        subtitle="چه کسی همین را می‌فروشد، و به چه قیمتی"
        actions={
          <Link to={`/stores/${id}`}>
            <Button variant="secondary">بازگشت به فروشگاه</Button>
          </Link>
        }
      />

      <ErrorBox message={error} />

      <Card>
        <SectionTitle>افزودن رقیب</SectionTitle>
        <form onSubmit={add} className="flex flex-wrap items-end gap-3">
          <div className="min-w-[12rem] flex-1">
            <Field label="نام">
              <Input
                id="competitor-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="مثلاً دیجی‌کالا یا نام یک فروشگاه اینستاگرامی"
                required
              />
            </Field>
          </div>
          <Field label="نوع">
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(KIND_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <div className="min-w-[12rem] flex-1">
            <Field label="سایت (اختیاری)">
              <Input
                id="competitor-site"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
                dir="ltr"
                placeholder="https://"
              />
            </Field>
          </div>
          <Button type="submit" disabled={busy || !name.trim()}>
            افزودن
          </Button>
        </form>
      </Card>

      <div className="mt-6 flex flex-col gap-4">
        {rows.length === 0 && (
          <EmptyState
            icon="search"
            title="هنوز رقیبی ثبت نشده"
            description="با ثبت رقبا، مقایسه‌ی قیمت و پیشنهادهای فروش از داده‌ی واقعی ساخته می‌شوند."
          />
        )}

        {rows.map((competitor) => (
          <Card key={competitor.id}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <SectionTitle>{competitor.name}</SectionTitle>
                <Badge tone="neutral">{KIND_LABEL[competitor.kind] ?? competitor.kind}</Badge>
                {competitor.is_stale && (
                  <Badge tone="warn">تحلیل قدیمی است</Badge>
                )}
              </div>
              <Button variant="ghost" onClick={() => remove(competitor)}>
                حذف
              </Button>
            </div>

            {competitor.positioning && (
              <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
                {competitor.positioning}
              </p>
            )}

            {competitor.products.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-3)" }}>
                هنوز محصولی از این رقیب ثبت نشده.
              </p>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <th>محصول</th>
                    <th>قیمت</th>
                    <th>دیده‌شده در</th>
                    <th>منبع</th>
                  </tr>
                </thead>
                <tbody>
                  {competitor.products.map((product) => (
                    <tr key={product.id}>
                      <td>{product.name}</td>
                      <td className="u-num">
                        {product.price_toman ? toman(product.price_toman) : "—"}
                      </td>
                      {/* The date is not decoration: it is what separates a
                          fact from a claim. */}
                      <td className="u-num" style={{ color: "var(--text-3)" }}>
                        {product.observed_at
                          ? new Date(product.observed_at).toLocaleDateString("fa-IR")
                          : "نامشخص"}
                      </td>
                      <td style={{ color: "var(--text-3)" }}>{product.source || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}

            <AddCompetitorProduct storeId={id!} competitorId={competitor.id} onAdded={load} />
          </Card>
        ))}
      </div>

      <div className="mt-6">
        <Alert tone="info" title="این داده کجا استفاده می‌شود">
          قیمت‌های ثبت‌شده مستقیماً در صفحه‌ی «فرصت‌های فروش» به کار می‌روند —
          اگر قیمت شما {fa(20)}٪ بالاتر از ارزان‌ترین رقیب باشد، همان‌جا با هر دو
          عدد به شما گفته می‌شود.
        </Alert>
      </div>
    </>
  );
}

function AddCompetitorProduct({
  storeId,
  competitorId,
  onAdded,
}: {
  storeId: string;
  competitorId: number;
  onAdded: () => void;
}) {
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`/stores/${storeId}/competitors/${competitorId}/products/`, {
        name,
        price_toman: price ? Number(price) : null,
        source: "دستی",
      });
      setName("");
      setPrice("");
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mt-3 flex flex-wrap items-end gap-2 border-t pt-3"
      style={{ borderColor: "var(--line)" }}
    >
      <div className="min-w-[10rem] flex-1">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="نام محصول رقیب"
        />
      </div>
      <div className="w-40">
        <Input
          type="number"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          placeholder="قیمت (تومان)"
        />
      </div>
      <Button type="submit" variant="secondary" disabled={busy || !name.trim()}>
        ثبت قیمت
      </Button>
      {error && <Alert tone="bad">{error}</Alert>}
    </form>
  );
}
