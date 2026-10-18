import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import { Alert, Button, Card, ErrorBox, Field, Input } from "../../components/ui";

/**
 * "I forgot my password."
 *
 * The confirmation is deliberately vague about whether the address is
 * registered — the API answers the same either way, and a page that said
 * "no such account" would undo that. It is specific about what to do next
 * instead, which is what the person actually needs.
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post("/auth/password-reset/", { email });
      setSent(data.detail);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <h1 className="mb-1 text-center text-2xl font-extrabold text-violet-700">آپ‌مارکت</h1>
        <p className="mb-6 text-center text-sm text-slate-500">بازیابی رمز عبور</p>

        {sent ? (
          <div className="flex flex-col gap-4">
            <Alert tone="ok" title="ایمیل فرستاده شد">
              {sent}
            </Alert>
            <p className="text-sm leading-7" style={{ color: "var(--text-2)" }}>
              لینک تا ۲۴ ساعت کار می‌کند و بعد از یک‌بار استفاده باطل می‌شود.
              اگر ایمیل نرسید، ممکن است با آدرس دیگری ثبت‌نام کرده باشید.
            </p>
            <Button variant="secondary" onClick={() => setSent(null)}>
              با ایمیل دیگری امتحان کن
            </Button>
          </div>
        ) : (
          <>
            <p className="mb-4 text-sm leading-7" style={{ color: "var(--text-2)" }}>
              ایمیلی که با آن ثبت‌نام کرده‌اید را بنویسید. لینک ساختن رمز جدید
              برایتان فرستاده می‌شود.
            </p>
            <ErrorBox message={error} />
            <form onSubmit={submit} className="space-y-4">
              <Field label="ایمیل">
                <Input
                  id="reset-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                  dir="ltr"
                  placeholder="you@example.com"
                />
              </Field>
              <Button type="submit" disabled={busy} className="w-full">
                {busy ? "در حال فرستادن…" : "فرستادن لینک بازیابی"}
              </Button>
            </form>
          </>
        )}

        <p className="mt-4 text-center text-sm text-slate-500">
          <Link to="/login" className="font-semibold text-violet-600 hover:underline">
            بازگشت به ورود
          </Link>
        </p>
      </Card>
    </div>
  );
}
