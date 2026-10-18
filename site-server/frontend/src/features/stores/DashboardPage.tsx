import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage, fetchAllPages } from "../../api/client";
import { clearPendingCode, getPendingCode } from "../billing/pendingCode";
import { clearPendingPlan, getPendingPlan } from "../billing/pendingPlan";
import {
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Input,
  SectionTitle,
  Spinner,
  TextArea,
} from "../../components/ui";
import { Store } from "../../types";
import { Feature } from "../panel/FlagsContext";

export default function DashboardPage() {
  const [stores, setStores] = useState<Store[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [description, setDescription] = useState("");
  const [audience, setAudience] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setStores(await fetchAllPages<Store>("/stores/"));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const createStore = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // The referral / discount code, if the visitor arrived with one.
      // `POST /stores/` has always accepted it and written an attribution
      // row; nothing in the panel used to send it, so the whole referral
      // loop could never fire.
      const code = getPendingCode();

      const created = await api.post("/stores/", {
        name,
        business_type: businessType,
        description,
        target_audience: audience,
        ...(code ? { code } : {}),
      });
      // Spent either way: a code that failed to attribute must not silently
      // attach itself to the next store this person makes.
      if (code) clearPendingCode();

      // Apply the plan the visitor picked on the public site, if any. A
      // subscription needs a store, so this is the first moment it can be
      // recorded. A failure here must not fail store creation - the store is
      // what the user asked for, and the plan page can set it again.
      const pending = getPendingPlan();
      if (pending && created?.data?.id) {
        try {
          await api.post(`/stores/${created.data.id}/subscription/`, { plan: pending });
        } catch {
          /* plan stays unset; recoverable from the plan page */
        } finally {
          clearPendingPlan();
        }
      }
      setName("");
      setBusinessType("");
      setDescription("");
      setAudience("");
      setShowForm(false);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <SectionTitle>فروشگاه‌های من</SectionTitle>
        <Feature k="dashboard.new_store">
          <Button onClick={() => setShowForm((v) => !v)} variant={showForm ? "secondary" : "primary"}>
            {showForm ? "بستن فرم" : "+ فروشگاه جدید"}
          </Button>
        </Feature>
      </div>
      <ErrorBox message={error} />

      {showForm && (
        <Card>
          <form onSubmit={createStore} className="grid gap-4 sm:grid-cols-2">
            <Field label="نام فروشگاه *">
              <Input value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="حوزه فعالیت">
              <Input
                value={businessType}
                onChange={(e) => setBusinessType(e.target.value)}
                placeholder="مثلاً پوشاک، الکترونیک…"
              />
            </Field>
            <div className="sm:col-span-2">
              <Field label="توضیحات">
                <TextArea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
              </Field>
            </div>
            <Field label="مخاطب هدف">
              <Input value={audience} onChange={(e) => setAudience(e.target.value)} />
            </Field>
            <div className="flex items-end">
              <Button type="submit" disabled={busy}>
                {busy ? "در حال ساخت…" : "ساخت فروشگاه"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {stores === null ? (
        <div className="py-10 text-center">
          <Spinner />
        </div>
      ) : stores.length === 0 ? (
        <EmptyState>هنوز فروشگاهی نساخته‌اید. اولین فروشگاه را بسازید!</EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {stores.map((store) => (
            <Link key={store.id} to={`/stores/${store.id}`}>
              <Card className="transition hover:border-violet-300 hover:shadow-md">
                <h3 className="font-bold text-slate-800">{store.name}</h3>
                {store.business_type && (
                  <p className="mt-1 text-xs text-violet-600">{store.business_type}</p>
                )}
                <p className="mt-2 line-clamp-2 text-sm text-slate-500">{store.description || "—"}</p>
                <p className="mt-3 text-xs text-slate-400">{store.product_count} محصول</p>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
