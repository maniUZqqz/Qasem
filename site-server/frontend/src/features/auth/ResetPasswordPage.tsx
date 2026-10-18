import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, errorMessage } from "../../api/client";
import { Alert, Button, Card, ErrorBox, Field, Input, Spinner } from "../../components/ui";

/**
 * Setting a new password from an emailed link.
 *
 * The link is checked on load, before the form is shown. Letting someone type
 * a new password twice and *then* telling them the link expired is the kind of
 * small cruelty that makes people give up and email support instead.
 */
export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const uid = params.get("uid") ?? "";
  const token = params.get("token") ?? "";

  const [checking, setChecking] = useState(true);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);

  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .get("/auth/password-reset/check/", { params: { uid, token } })
      .then(({ data }) => {
        if (!alive) return;
        setUsername(data.username);
      })
      .catch((err) => {
        if (!alive) return;
        setLinkError(
          err?.response?.data?.message ??
            "این لینک معتبر نیست یا منقضی شده است."
        );
      })
      .finally(() => alive && setChecking(false));
    return () => {
      alive = false;
    };
  }, [uid, token]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== again) {
      // Checked here rather than on the server: it is not a security rule,
      // it is a typo guard, and the answer is instant.
      setError("دو رمز یکسان نیستند.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/password-reset/confirm/", { uid, token, password });
      setDone(true);
      // No session is handed back on purpose, so the next step is a normal login.
      setTimeout(() => navigate("/login"), 2500);
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
        <p className="mb-6 text-center text-sm text-slate-500">ساختن رمز جدید</p>

        {checking && (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        )}

        {!checking && linkError && (
          <div className="flex flex-col gap-4">
            <Alert tone="bad" title="این لینک کار نمی‌کند">
              {linkError}
            </Alert>
            <Link to="/forgot-password">
              <Button className="w-full">گرفتن لینک تازه</Button>
            </Link>
          </div>
        )}

        {!checking && !linkError && done && (
          <Alert tone="ok" title="رمز جدید ثبت شد">
            حالا با رمز تازه وارد شوید. در حال انتقال به صفحه‌ی ورود…
          </Alert>
        )}

        {!checking && !linkError && !done && (
          <>
            {username && (
              <p className="mb-4 text-sm" style={{ color: "var(--text-2)" }}>
                برای حساب <b dir="ltr">{username}</b> رمز جدید بگذارید.
              </p>
            )}
            <ErrorBox message={error} />
            <form onSubmit={submit} className="space-y-4">
              <Field label="رمز جدید">
                <Input
                  id="new-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoFocus
                  autoComplete="new-password"
                />
              </Field>
              <Field label="تکرار رمز جدید">
                <Input
                  id="new-password-again"
                  type="password"
                  value={again}
                  onChange={(e) => setAgain(e.target.value)}
                  required
                  autoComplete="new-password"
                />
              </Field>
              <Button type="submit" disabled={busy} className="w-full">
                {busy ? "در حال ثبت…" : "ثبت رمز جدید"}
              </Button>
            </form>
            <p className="mt-3 text-xs leading-6" style={{ color: "var(--text-3)" }}>
              رمز باید حداقل ۸ کاراکتر و شبیه نام کاربری‌تان نباشد. بعد از ثبت،
              همین لینک دیگر کار نمی‌کند.
            </p>
          </>
        )}
      </Card>
    </div>
  );
}
