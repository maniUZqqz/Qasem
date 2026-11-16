import { useCallback, useEffect, useRef, useState } from "react";

import { Doc, Op, Overview, Scene, apiError, designApi, isConflict, previewBlob } from "./api";

/** سند + صحنه + ذخیره با rev. هر ویرایش (ops) یک درخواست است؛ ناهمخوانیِ rev (۴۰۹) ⇒ تازه‌سازیِ خودکار و پیام. */
export function useDocEditor(storeId: string, docId: number, mode?: string) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [scene, setScene] = useState<Scene | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const docRef = useRef<Doc | null>(null);
  const chain = useRef<Promise<unknown>>(Promise.resolve());

  const loadScene = useCallback(async (d: Doc) => {
    try {
      setScene(await designApi.scene(storeId, d.id, mode));
    } catch (e) {
      setError(apiError(e));
    }
  }, [storeId, mode]);

  const reload = useCallback(async () => {
    try {
      const d = await designApi.doc(storeId, docId);
      docRef.current = d;
      setDoc(d);
      await loadScene(d);
      setError(null);
    } catch (e) {
      setError(apiError(e));
    }
  }, [storeId, docId, loadScene]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** ویرایش‌ها پشتِ‌هم (صف) اجرا می‌شوند تا rev همیشه تازه باشد. */
  const apply = useCallback((ops: Op[]): Promise<Doc | null> => {
    const run = async (): Promise<Doc | null> => {
      const cur = docRef.current;
      if (!cur) return null;
      setBusy(true);
      try {
        const d = await designApi.ops(storeId, cur.id, ops, cur.rev);
        docRef.current = d;
        setDoc(d);
        await loadScene(d);
        setError(null);
        return d;
      } catch (e) {
        if (isConflict(e)) {
          setNotice("این سند در جای دیگری عوض شده بود؛ تازه شد. دوباره انجام بده.");
          await reload();
        } else {
          setError(apiError(e));
        }
        return null;
      } finally {
        setBusy(false);
      }
    };
    const p = chain.current.then(run, run);
    chain.current = p;
    return p;
  }, [storeId, loadScene, reload]);

  const replaceDoc = useCallback(async (d: Doc) => {
    docRef.current = d;
    setDoc(d);
    await loadScene(d);
  }, [loadScene]);

  return { doc, scene, error, notice, busy, apply, reload, replaceDoc, setError, setNotice, setDoc };
}

/** تصویرِ پیش‌نمایش با توکنِ ورود؛ تا رسیدنِ تازه، تصویرِ قبلی دیده می‌شود (بی‌پرش). */
export function usePreview(path: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    let live = true;
    previewBlob(path).then((u) => live && setUrl(u)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [path]);
  return url;
}

export function useOverview(storeId: string) {
  const [ov, setOv] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setOv(await designApi.overview(storeId));
      setError(null);
    } catch (e) {
      setError(apiError(e));
    }
  }, [storeId]);
  useEffect(() => {
    void load();
  }, [load]);
  return { ov, error, reload: load };
}

export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}
