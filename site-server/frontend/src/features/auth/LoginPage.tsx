import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { errorMessage } from "../../api/client";
import { Button, Card, ErrorBox, Field, Input } from "../../components/ui";
import { useAuth } from "./AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
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
        <h1 className="mb-1 text-center text-2xl font-extrabold text-violet-700">آپ‌مارکت</h1>
        <p className="mb-6 text-center text-sm text-slate-500">کارمند فروش و مارکتینگ هوش مصنوعی</p>
        <ErrorBox message={error} />
        <form onSubmit={submit} className="space-y-4">
          <Field label="نام کاربری">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </Field>
          <Field label="رمز عبور">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "در حال ورود…" : "ورود"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-slate-500">
          <Link to="/forgot-password" className="font-semibold text-violet-600 hover:underline">
            رمزم را فراموش کردم
          </Link>
        </p>
        <p className="mt-2 text-center text-sm text-slate-500">
          حساب ندارید؟{" "}
          <Link to="/register" className="font-semibold text-violet-600 hover:underline">
            ثبت‌نام
          </Link>
        </p>
      </Card>
    </div>
  );
}
