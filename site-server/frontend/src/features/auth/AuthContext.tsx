import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { AxiosError } from "axios";

import { api } from "../../api/client";
import { User } from "../../types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * آیا این خطا یعنی «نشست تمام شده» یا یعنی «الان نشد، دوباره بپرس»؟
 *
 * تفاوتش را قبلاً نمی‌گذاشتیم و هر خطایی کاربر را بیرون می‌انداخت. یعنی
 * یک ۴۲۹ از محدودکننده‌ی نرخ — یا حتی یک قطعی دو ثانیه‌ای وای‌فای — کسی
 * را که توکن کاملاً معتبرش در مرورگر نشسته بود، به صفحه‌ی ورود پرت
 * می‌کرد. این در تست با مرورگر واقعی دیده شد: کلیک سریع بین صفحه‌ها،
 * محدودکننده را فعال می‌کرد و کاربر لاگ‌اوت می‌شد.
 *
 * ۴۰۱ تنها جوابی است که واقعاً می‌گوید اعتبارنامه بد است — و حتی آن هم
 * قبلاً از فیلتر `api` رد شده و یک بار refresh را امتحان کرده. بقیه‌ی
 * حالت‌ها گذرا هستند.
 */
function sessionIsOver(error: unknown): boolean {
  const status = (error as AxiosError)?.response?.status;
  return status === 401 || status === 403;
}

/** ثانیه‌هایی که سرور گفته صبر کن، یا عقب‌نشینی پیش‌فرض. */
function retryAfter(error: unknown, fallback: number): number {
  const header = (error as AxiosError)?.response?.headers?.["retry-after"];
  const seconds = Number(header);
  // سقف می‌گذاریم: یک هدر عجیب نباید صفحه را نیم‌ساعت روی «در حال
  // بارگذاری» نگه دارد.
  return Number.isFinite(seconds) && seconds > 0 ? Math.min(seconds * 1000, 8000) : fallback;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      if (!localStorage.getItem("access")) {
        setLoading(false);
        return;
      }
      // تا سه تلاش برای خطاهای گذرا؛ نشست فقط با جواب صریح سرور تمام
      // می‌شود.
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const { data } = await api.get<User>("/auth/me/");
          if (!cancelled) {
            setUser(data);
            setLoading(false);
          }
          return;
        } catch (err) {
          if (cancelled) return;
          if (sessionIsOver(err)) {
            setUser(null);
            setLoading(false);
            return;
          }
          if (attempt === 2) break;
          await sleep(retryAfter(err, 600 * (attempt + 1)));
        }
      }
      // سرور قابل دسترس نشد. توکن پاک نمی‌شود — همان‌جا می‌ماند تا
      // رفرش بعدی دوباره امتحان کند؛ پاک کردنش یعنی کسی که فقط
      // اینترنتش قطع بوده، باید دوباره رمز بزند.
      if (!cancelled) {
        setUser(null);
        setLoading(false);
      }
    };

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = async (username: string, password: string) => {
    const { data } = await api.post("/auth/login/", { username, password });
    localStorage.setItem("access", data.access);
    localStorage.setItem("refresh", data.refresh);
    const me = await api.get<User>("/auth/me/");
    setUser(me.data);
  };

  const register = async (username: string, email: string, password: string) => {
    await api.post("/auth/register/", { username, email, password });
    await login(username, password);
  };

  const logout = () => {
    localStorage.removeItem("access");
    localStorage.removeItem("refresh");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
