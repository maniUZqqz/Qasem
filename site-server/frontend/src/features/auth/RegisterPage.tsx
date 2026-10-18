import { FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { Button, Card, ErrorBox, Field, Input } from "../../components/ui";
import CodeField from "../../components/CodeField";
import { readCodeFromUrl, setPendingCode } from "../billing/pendingCode";
import { readPlanFromUrl, setPendingPlan } from "../billing/pendingPlan";
import { adoptSessionFromUrl, trackSignup } from "./track";
import { useAuth } from "./AuthContext";

/** Plan names, so the chosen package can be echoed back before the plans API
 *  is even reachable. Falls back to the raw slug for anything unknown. */
const PLAN_LABELS: Record<string, string> = {
  start: "استارت",
  pro: "حرفه‌ای",
  unlimited: "بی‌نهایت",
  trial: "آزمایشی",
};

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [plan, setPlan] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState("");

  // The public site links here as /register?plan=pro. Remember it now; the
  // store creation step applies it, because a subscription needs a store.
  useEffect(() => {
    // Continue the visit that started on the marketing site, so "saw pricing"
    // and "registered" belong to one session rather than two.
    adoptSessionFromUrl(location.search);
    trackSignup("signup_started");

    const slug = readPlanFromUrl(location.search);
    if (slug) {
      setPendingPlan(slug);
      setPlan(slug);
    }

    // `/register?ref=ALI-4821` — the code is spent when the first store is
    // created, because attribution hangs off a store.
    const ref = readCodeFromUrl(location.search);
    if (ref) setCode(ref);
  }, [location.search]);

  const submit = async (e: FormEvent) => {
    if (code.trim()) setPendingCode(code.trim());
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register(username, email, password);
      trackSignup("signup_completed");
      navigate("/");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <h1 className="mb-2 text-center text-2xl font-extrabold text-violet-700">ساخت حساب جدید</h1>

        {plan ? (
          <p className="mb-6 rounded-xl bg-violet-50 px-4 py-3 text-center text-sm text-violet-700">
            پکیج انتخابی شما: <strong>{PLAN_LABELS[plan] ?? plan}</strong>
            <br />
            <span className="text-violet-500">
              بعد از ساخت فروشگاه روی همان تنظیم می‌شود.
            </span>
          </p>
        ) : (
          <p className="mb-6 text-center text-sm text-slate-500">
            دو هفته رایگان، بدون کارت بانکی.
          </p>
        )}

        <ErrorBox message={error} />
        <form onSubmit={submit} className="space-y-4">
          <Field label="نام کاربری">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </Field>
          <CodeField value={code} onChange={setCode} />
          <Field label="ایمیل">
            <Input
              id="register-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              dir="ltr"
              placeholder="you@example.com"
              autoComplete="email"
            />
          </Field>
          {/* Said here, not only enforced on the server: someone who thinks
              the field is optional will skip it and lose the only way back
              into their account. */}
          <p className="-mt-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
            اگر رمزت را فراموش کنی، تنها راه برگشتن به حسابت همین ایمیل است.
          </p>
          <Field label="رمز عبور">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "در حال ساخت حساب…" : "ثبت‌نام"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-slate-500">
          حساب دارید؟{" "}
          <Link to="/login" className="font-semibold text-violet-600 hover:underline">
            ورود
          </Link>
        </p>
      </Card>
    </div>
  );
}
