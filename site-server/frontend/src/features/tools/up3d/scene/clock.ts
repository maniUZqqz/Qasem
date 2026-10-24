import { useSyncExternalStore } from "react";

/**
 * زمانِ ویرایشگر (ثانیه) بیرون از state ِ React: نما هر فریم مستقیم از `clock.t` می‌خواند (بی‌رندرِ دوباره)،
 * و فقط چیزهای کوچک (خطِ زمان، ساعت) با `useClockTime` مشترک می‌شوند.
 */
export class Clock {
  t = 0;
  playing = false;
  private ls = new Set<() => void>();

  set = (t: number) => {
    if (t === this.t) return;
    this.t = t;
    this.ls.forEach((f) => f());
  };

  setPlaying = (p: boolean) => {
    this.playing = p;
    this.ls.forEach((f) => f());
  };

  subscribe = (f: () => void) => {
    this.ls.add(f);
    return () => {
      this.ls.delete(f);
    };
  };

  getT = () => this.t;
  getPlaying = () => this.playing;
}

export function useClockTime(clock: Clock): number {
  return useSyncExternalStore(clock.subscribe, clock.getT);
}

export function useClockPlaying(clock: Clock): boolean {
  return useSyncExternalStore(clock.subscribe, clock.getPlaying);
}
