import { FormEvent, useEffect, useState } from "react";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, Field, Input, PageHeader, Select, Table } from "../../../components/ui";
import { g, useGet } from "../api";
import { LoadState } from "../components/bits";
import { ConfirmDialog } from "../components/Modal";
import Pagination from "../components/Pagination";
import { Flash, Ltr } from "../components/outreach/shared";
import { faDateTime } from "../format";
import { asList, countOf, fieldErrorsOf, useAction, useDebounced } from "../outreach/api";
import { SUPPRESSION_KIND, SUPPRESSION_REASONS, suppressionReason } from "../outreach/labels";
import type { SuppressionEntry } from "../outreach/types";
import type { Paged } from "../types";

const PAGE_SIZE = 25;

/**
 * «تماس نگیر»: identifiers (phone, e-mail, website, Instagram) that must never be queued or sent anything.
 * Adding a value here also blocks every lead that has that same identifier.
 */
export default function SuppressionPage() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebounced(q.trim(), 350);
  useEffect(() => setPage(1), [search]);
  const list = useGet<Paged<SuppressionEntry> | SuppressionEntry[]>("/compliance/suppression/", { q: search || undefined, page, page_size: PAGE_SIZE });

  const [value, setValue] = useState("");
  const [reason, setReason] = useState("asked_not_to_contact");
  const [note, setNote] = useState("");
  const [added, setAdded] = useState<string | null>(null);
  const add = useAction();
  const remove = useAction();
  const [removing, setRemoving] = useState<SuppressionEntry | null>(null);
  const errors = fieldErrorsOf(add.error);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    setAdded(null);
    const done = await add.run(() => g.post("/compliance/suppression/", { value: value.trim(), reason, note: note.trim() }));
    if (done !== undefined) {
      setAdded(value.trim());
      setValue("");
      setNote("");
      setPage(1);
      list.reload();
    }
  };

  const confirmRemove = async () => {
    if (!removing) return;
    const done = await remove.run(() => g.del(`/compliance/suppression/${removing.id}/`));
    if (done !== undefined) {
      setRemoving(null);
      list.reload();
    }
  };

  const rows = asList(list.data);
  const count = countOf(list.data);

  return (
    <div className="space-y-5" data-testid="suppression-page">
      <PageHeader title="فهرستِ «تماس نگیر»" subtitle="کسانی که نباید هیچ پیامی بگیرند" />
      <Alert tone="info" title="این فهرست چه می‌کند؟">
        هرکس یا هر راهِ تماسی که اینجا باشد، هرگز در صفِ پیام نمی‌رود و هیچ پیامی (نه خودکار، نه دستی) برایش فرستاده نمی‌شود. اگر شمارهٔ تلفن، ایمیل، آدرسِ سایت یا اینستاگرامِ یک لید اینجا باشد، خودِ لید هم مسدود است.
      </Alert>

      <Card>
        <form onSubmit={submit} className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1.2fr)_minmax(0,1.5fr)_auto] md:items-end" data-testid="suppression-add">
          <Field label="شماره، ایمیل، آدرسِ سایت یا @اینستاگرام" hint="هر چه را که پیدا کردید همین‌جا بچسبانید؛ نوعش خودکار تشخیص داده می‌شود.">
            <Input dir="ltr" value={value} onChange={(e) => setValue(e.target.value)} placeholder="0912… / info@shop.ir / @shop" data-testid="suppression-value" />
            {errors.value && (
              <span className="mt-1 block text-xs" style={{ color: "var(--bad)" }} role="alert">
                {errors.value}
              </span>
            )}
          </Field>
          <Field label="دلیل">
            <Select value={reason} onChange={(e) => setReason(e.target.value)}>
              {SUPPRESSION_REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="یادداشت (اختیاری)">
            <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} />
          </Field>
          <Button type="submit" disabled={add.busy || !value.trim()} data-testid="suppression-submit">
            <Icon name="plus" size={16} />
            {add.busy ? "…" : "افزودن"}
          </Button>
        </form>
        {add.error && !errors.value && (
          <div className="mt-3">
            <Flash tone="bad">{add.error.message}</Flash>
          </div>
        )}
        {added && (
          <div className="mt-3">
            <Flash tone="ok" onClose={() => setAdded(null)}>
              «<Ltr>{added}</Ltr>» به فهرستِ «تماس نگیر» اضافه شد.
            </Flash>
          </div>
        )}
      </Card>

      <Card padded={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4">
          <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>
            فهرست
          </h2>
          <div className="w-full sm:w-72">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جست‌وجو در فهرست…" aria-label="جست‌وجو" data-testid="suppression-search" />
          </div>
        </div>
        <div className="px-2 pb-2 pt-3">
          <LoadState loading={list.loading && !list.data} error={list.error} onRetry={list.reload}>
            {rows.length === 0 ? (
              <EmptyState icon="shield" title={search ? "چیزی پیدا نشد" : "فهرست خالی است"}>
                {search ? "عبارتِ دیگری را امتحان کنید." : "هنوز کسی را به «تماس نگیر» اضافه نکرده‌اید."}
              </EmptyState>
            ) : (
              <>
                <Table>
                  <thead>
                    <tr>
                      <th className="text-start">مقدار</th>
                      <th className="text-start">نوع</th>
                      <th className="text-start">دلیل</th>
                      <th className="text-start">یادداشت</th>
                      <th className="text-start">چه کسی / کی</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((entry) => (
                      <tr key={entry.id} data-testid="suppression-row">
                        <td>
                          <Ltr>{entry.value}</Ltr>
                        </td>
                        <td>
                          <Badge>{entry.kind_label || SUPPRESSION_KIND[entry.kind] || entry.kind}</Badge>
                        </td>
                        <td>{entry.reason_label || suppressionReason(entry.reason)}</td>
                        <td className="max-w-[16rem] break-words">{entry.note || "—"}</td>
                        <td className="whitespace-nowrap text-xs" style={{ color: "var(--text-3)" }}>
                          {entry.created_by_name ? `${entry.created_by_name} · ` : ""}
                          {faDateTime(entry.created_at)}
                        </td>
                        <td className="text-end">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              remove.clear();
                              setRemoving(entry);
                            }}
                            aria-label="برداشتن از فهرست"
                            data-testid="suppression-remove"
                          >
                            <Icon name="trash" size={15} />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                <Pagination page={page} pageSize={PAGE_SIZE} count={count} onPage={setPage} disabled={list.loading} />
              </>
            )}
          </LoadState>
        </div>
      </Card>

      <ConfirmDialog
        open={!!removing}
        title="از فهرستِ «تماس نگیر» برداشته شود؟"
        danger
        confirmLabel="بله، برداشته شود"
        busy={remove.busy}
        onConfirm={confirmRemove}
        onClose={() => setRemoving(null)}
        message={
          <div className="space-y-2">
            <p>
              «<Ltr>{removing?.value}</Ltr>» دوباره می‌تواند در صفِ پیام بیاید. فقط اگر مطمئنید که با این کار مشکلی پیش نمی‌آید این کار را بکنید (مثلاً خودش اجازه داده است).
            </p>
            {remove.error && <p style={{ color: "var(--bad)" }}>{remove.error.message}</p>}
          </div>
        }
      />
    </div>
  );
}
