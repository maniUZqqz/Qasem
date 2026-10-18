import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";

import { api } from "../api/client";
import { JobStream, openJobStream } from "../api/jobStream";
import { Job, Paginated } from "../types";

/** How many consecutive failed polls before giving up (2.5s apart). */
const MAX_CONSECUTIVE_ERRORS = 8;

const TERMINAL: Job["state"][] = ["COMPLETED", "FAILED", "CANCELLED"];

/**
 * States where nothing will change until a person answers.
 *
 * These must stop the poller. A job parked for approval can sit there
 * overnight, and polling it every 2.5 seconds with a spinner on screen is
 * exactly the eternal-spinner bug this hook was written to prevent — except
 * this time the job is perfectly healthy and simply waiting for its owner.
 */
const PARKED: Job["state"][] = ["PREVIEW", "WAITING_APPROVAL"];

function isParked(job: Job | null): boolean {
  if (!job) return false;
  return job.awaiting_human ?? PARKED.includes(job.state);
}

export interface ResumeParams {
  type: string;
  productId?: number;
  scriptId?: number;
}

/**
 * Drives one AI job from click to result.
 *
 * Two rules this hook exists to guarantee:
 *  1. The user sees something the instant they click — in synchronous mode the
 *     POST itself blocks for the whole generation, so `begin()` must light the
 *     progress box up before the request is even sent (beter.md v2 #4).
 *  2. The user is never stuck — `cancel()` always unlocks the panel, and a job
 *     that the server reports as dead ends the polling (beter.md v2 #1/#2).
 */
export function useJobRunner(onComplete: () => void | Promise<void>) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const intervalRef = useRef<number | null>(null);
  const streamRef = useRef<JobStream | null>(null);
  const errorsRef = useRef(0);
  // In synchronous mode the POST that starts a job only returns when the job
  // has finished. If the user pressed Cancel meanwhile, that late response
  // must not re-lock the panel it just freed.
  const abandonedRef = useRef(false);

  const stop = useCallback(() => {
    if (intervalRef.current) window.clearInterval(intervalRef.current);
    intervalRef.current = null;
    streamRef.current?.close();
    streamRef.current = null;
  }, []);

  useEffect(() => stop, [stop]);

  const finish = useCallback(
    async (data: Job) => {
      stop();
      setBusy(false);
      setStartedAt(null);
      if (data.state === "COMPLETED") await onComplete();
      if (data.state === "FAILED") setError(data.error || "عملیات ناموفق بود");
      if (data.state === "CANCELLED" && data.error) setError(data.error);
    },
    [onComplete, stop],
  );

  /** Stop waiting, but keep the job on screen — the owner has to act on it. */
  const park = useCallback(
    (data: Job) => {
      stop();
      setBusy(false);
      setStartedAt(null);
      setJob(data);
      // Reload so the finished piece (a rendered segment) is on screen next to
      // the approve button, rather than only its filename in a JSON blob.
      void onComplete();
    },
    [onComplete, stop],
  );

  /** Show progress immediately, before the request that creates the job. */
  const begin = useCallback(() => {
    stop();
    errorsRef.current = 0;
    abandonedRef.current = false;
    setJob(null);
    setError(null);
    setBusy(true);
    setStartedAt(Date.now());
  }, [stop]);

  /** The fallback when the live stream is not available. */
  const startPolling = useCallback(
    (jobId: number) => {
      if (abandonedRef.current || intervalRef.current) return;
      intervalRef.current = window.setInterval(async () => {
        try {
          const { data } = await api.get<Job>(`/jobs/${jobId}/`);
          errorsRef.current = 0;
          setJob(data);
          if (TERMINAL.includes(data.state)) await finish(data);
          else if (isParked(data)) park(data);
        } catch (err) {
          // a job that no longer exists (or is forbidden) will never finish
          const status = axios.isAxiosError(err) ? err.response?.status : undefined;
          if (status === 404 || status === 403) {
            stop();
            setBusy(false);
            setStartedAt(null);
            setError("این Job دیگر وجود ندارد.");
            return;
          }
          errorsRef.current += 1;
          if (errorsRef.current >= MAX_CONSECUTIVE_ERRORS) {
            stop();
            setBusy(false);
            setStartedAt(null);
            setError("ارتباط با سرور برای پیگیری Job قطع شد؛ صفحه را رفرش کنید.");
          }
        }
      }, 2500);
    },
    [finish, park, stop],
  );


  const track = useCallback(
    (jobId: number, initial?: Job) => {
      if (abandonedRef.current) return; // the user cancelled this run already
      stop(); // never leave a previous poller running
      errorsRef.current = 0;
      setBusy(true);
      setError(null);
      setStartedAt((current) => current ?? Date.now());
      if (initial) setJob(initial);
      // synchronous mode finishes the whole job inside the POST, so the job we
      // are handed is already done — don't wait 2.5s to notice
      if (initial && TERMINAL.includes(initial.state)) {
        void finish(initial);
        return;
      }
      if (isParked(initial ?? null)) {
        park(initial!);
        return;
      }

      // Prefer the live stream; fall back to polling when it is unavailable —
      // an old browser, or the server's per-process stream budget being full.
      // Polling is slower and completely fine, so a refusal is never shown.
      void openJobStream(jobId, {
        onProgress: (payload) => setJob(payload as Job),
        onDone: (payload) => void finish(payload as Job),
        onWaiting: (payload) => park(payload as Job),
        onGone: () => {
          stop();
          setBusy(false);
          setStartedAt(null);
          setError("این Job دیگر وجود ندارد.");
        },
        // The connection ended but the job may not have. Rather than rebuild
        // the stream, hand over to the poller: it already knows every way this
        // can end, and a render has minutes left anyway.
        onDrop: () => startPolling(jobId),
      }).then((stream) => {
        if (abandonedRef.current || !stream) {
          stream?.close();
          if (!stream) startPolling(jobId);
          return;
        }
        streamRef.current = stream;
      });
    },
    [finish, park, startPolling, stop],
  );

  const fail = useCallback(
    (message: string) => {
      if (abandonedRef.current) return; // cancelled runs report nothing
      stop();
      setBusy(false);
      setStartedAt(null);
      setError(message);
    },
    [stop],
  );

  /** Unlock the panel no matter what the server is doing. */
  const cancel = useCallback(async () => {
    abandonedRef.current = true;
    stop();
    setBusy(false);
    setStartedAt(null);
    const id = job?.id;
    setJob(null);
    setError(null);
    if (id == null) return;
    try {
      await api.post(`/jobs/${id}/cancel/`);
    } catch {
      // the panel is already unlocked locally; a stale row is reaped server-side
    }
  }, [job?.id, stop]);

  /**
   * Re-attach to a job that is still running on the server (page was
   * refreshed / user navigated away mid-generation). Returns true when an
   * active job was found and tracking restarted. Jobs the server considers
   * dead are never returned by this endpoint, so no eternal spinner.
   */
  const resume = useCallback(
    async (params: ResumeParams) => {
      abandonedRef.current = false;
      try {
        const query = new URLSearchParams({ active: "true", type: params.type });
        if (params.productId != null) query.set("product_id", String(params.productId));
        if (params.scriptId != null) query.set("script_id", String(params.scriptId));
        const { data } = await api.get<Paginated<Job>>(`/jobs/?${query.toString()}`);
        const active = data.results?.[0];
        if (active) {
          setStartedAt(new Date(active.created_at).getTime());
          track(active.id, active);
          return true;
        }
      } catch {
        // resuming is best-effort; the user can always start a new run
      }
      return false;
    },
    [track],
  );

  // A parked job is not running: the panel unlocks so the owner can answer it.
  const waiting = isParked(job);
  const running = !waiting && (busy || (!!job && !TERMINAL.includes(job.state)));
  return {
    job,
    error,
    running,
    waiting,
    startedAt,
    begin,
    track,
    resume,
    cancel,
    fail,
    setError,
    setJob,
  };
}
