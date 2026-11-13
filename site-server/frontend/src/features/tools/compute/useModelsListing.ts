import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../../api/client";
import { activePulls, type ModelsListing } from "./nodeModels";

/**
 * GET /compute/models/ — بسته‌های هر سرور + مدل‌های Ollama + تنظیمِ دانلودِ خودکار، در یک درخواست.
 * وقتی دانلودی در جریان است (بسته‌ای یا Ollama) هر ۱۰ ثانیه تازه می‌شود تا درصد جلو برود؛ وگرنه هر دقیقه.
 */
export function useModelsListing() {
  const [data, setData] = useState<ModelsListing | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<ModelsListing>("/compute/models/");
      setData(d);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const live = Boolean(data && (data.nodes.some((n) => n.running || n.waiting) || activePulls(data.ollama).length > 0));
  useEffect(() => {
    const t = window.setInterval(() => void load(), live ? 10000 : 60000);
    return () => window.clearInterval(t);
  }, [live, load]);

  return { data, error, reload: load };
}
