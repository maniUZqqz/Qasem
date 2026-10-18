import { FormEvent, useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../api/client";
import { Alert, Badge, Button, Card, Input, SectionTitle, Select, Skeleton } from "./ui";

type Member = {
  id: number | null;
  username: string;
  email: string;
  role: string;
  role_label: string;
  is_active: boolean;
  is_owner: boolean;
};

type Payload = {
  members: Member[];
  roles: { value: string; label: string }[];
  your_role: string;
};

/**
 * Who can get into this store.
 *
 * Hidden entirely when the API refuses: only OWNER and ADMIN may manage
 * members, and showing a card that always 403s is worse than not showing one.
 */
export default function MembersCard({ storeId }: { storeId: string | number }) {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [hidden, setHidden] = useState(false);
  const [identifier, setIdentifier] = useState("");
  const [role, setRole] = useState("VIEWER");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/stores/${storeId}/members/`);
      setPayload(data);
    } catch {
      setHidden(true);
    }
  }, [storeId]);

  useEffect(() => {
    load();
  }, [load]);

  async function add(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`/stores/${storeId}/members/`, { user: identifier, role });
      setIdentifier("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(member: Member, next: string) {
    setError(null);
    try {
      await api.patch(`/stores/${storeId}/members/${member.id}/`, { role: next });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove(member: Member) {
    setError(null);
    try {
      await api.delete(`/stores/${storeId}/members/${member.id}/`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (hidden) return null;
  if (payload === null) return <Skeleton className="h-48" />;

  return (
    <Card>
      <SectionTitle>اعضای فروشگاه</SectionTitle>

      <div className="flex flex-col gap-3">
        {payload.members.map((member) => (
          <div
            key={member.id ?? "owner"}
            className="flex flex-wrap items-center justify-between gap-3"
          >
            <div className="min-w-0">
              <div className="text-sm font-medium" style={{ color: "var(--text)" }}>
                {member.username}
              </div>
              <div className="truncate text-xs" style={{ color: "var(--text-3)" }}>
                {member.email || "—"}
              </div>
            </div>

            {member.is_owner ? (
              <Badge tone="brand">مالک</Badge>
            ) : (
              <div className="flex items-center gap-2">
                <Select
                  value={member.role}
                  onChange={(e) => changeRole(member, e.target.value)}
                >
                  {payload.roles
                    .filter((r) => r.value !== "OWNER")
                    .map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                </Select>
                <Button variant="ghost" onClick={() => remove(member)}>
                  حذف دسترسی
                </Button>
              </div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={add} className="mt-4 flex flex-wrap items-end gap-2 border-t pt-4"
            style={{ borderColor: "var(--line)" }}>
        <div className="min-w-[12rem] flex-1">
          <Input
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            placeholder="نام کاربری یا ایمیل همکار"
          />
        </div>
        <Select value={role} onChange={(e) => setRole(e.target.value)}>
          {payload.roles
            .filter((r) => r.value !== "OWNER")
            .map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
        </Select>
        <Button type="submit" disabled={busy || !identifier.trim()}>
          افزودن
        </Button>
      </form>
      <div className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
        همکارت باید اول خودش در آپ‌مارکت حساب بسازد؛ بعد با همان نام کاربری اضافه‌اش کن.
      </div>

      {error && (
        <div className="mt-3">
          <Alert tone="bad">{error}</Alert>
        </div>
      )}
    </Card>
  );
}
