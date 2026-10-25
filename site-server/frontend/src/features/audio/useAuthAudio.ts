import { useCallback, useEffect, useMemo, useRef } from "react";

import { api } from "../../api/client";

/**
 * Audio through the API: recordings and generated sounds are not public files, so an <audio> element cannot
 * point at them directly. `load(path)` fetches with the user's token and returns an object URL (revoked when
 * the component goes away); `play(path)` plays it at once; `download(path, name)` saves it.
 */
export function useAuthAudio() {
  const urls = useRef<string[]>([]);
  const player = useRef<HTMLAudioElement | null>(null);
  useEffect(
    () => () => {
      player.current?.pause();
      urls.current.forEach((u) => URL.revokeObjectURL(u));
    },
    [],
  );
  const load = useCallback(async (path: string): Promise<string> => {
    const { data } = await api.get<Blob>(path, { responseType: "blob" });
    const url = URL.createObjectURL(data);
    urls.current.push(url);
    return url;
  }, []);
  const play = useCallback(
    async (path: string) => {
      const url = await load(path);
      player.current?.pause();
      player.current = new Audio(url);
      await player.current.play();
    },
    [load],
  );
  const download = useCallback(
    async (path: string, name: string) => {
      const url = await load(path);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
    },
    [load],
  );
  return useMemo(() => ({ load, play, download }), [load, play, download]);
}
