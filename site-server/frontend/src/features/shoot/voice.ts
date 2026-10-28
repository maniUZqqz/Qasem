import { useCallback, useEffect, useRef } from "react";

/**
 * صدای راهنما: اول فایلِ ساخته‌شده با موتورِ گفتارِ سایت (session.voice.clips)، وگرنه گفتارِ خودِ مرورگر اگر
 * صدای فارسی دارد، وگرنه فقط لرزش. یک پخش‌کنندهٔ مشترک، تا جمله‌ها روی هم نیفتند.
 */
export function useCueVoice(clips: Record<string, string> | undefined, enabled: boolean) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const clipsRef = useRef(clips);
  clipsRef.current = clips;

  useEffect(
    () => () => {
      audio.current?.pause();
      if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    },
    [],
  );

  return useCallback(
    (text: string, opts: { vibrate?: number } = {}) => {
      if (opts.vibrate && typeof navigator !== "undefined" && "vibrate" in navigator) {
        try {
          navigator.vibrate(opts.vibrate);
        } catch {
          /* بعضی مرورگرها اجازه نمی‌دهند */
        }
      }
      if (!enabled || !text) return;
      const url = clipsRef.current?.[text];
      if (url) {
        if (!audio.current) audio.current = new Audio();
        audio.current.pause();
        audio.current.src = url;
        void audio.current.play().catch(() => undefined);
        return;
      }
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        const voices = window.speechSynthesis.getVoices();
        const voice = voices.find((v) => v.lang.toLowerCase().startsWith("fa"));
        if (!voice) return;
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.voice = voice;
        u.lang = voice.lang;
        window.speechSynthesis.speak(u);
      }
    },
    [enabled],
  );
}

export function browserHasPersianVoice(): boolean {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return false;
  return window.speechSynthesis.getVoices().some((v) => v.lang.toLowerCase().startsWith("fa"));
}
