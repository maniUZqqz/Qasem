/** صحنهٔ «شخصیتِ برند» که صفحهٔ «گالری و کاربرد» برای استودیوی موشن گذاشته؛ یک بار خوانده و پاک می‌شود (فقط برای همین فروشگاه و تا ۱۰ دقیقه). */
export const MOTION_SCENE_KEY = "bc.motion.scene";

export function takeBrandScene(storeId: string): Record<string, unknown> | null {
  try {
    const raw = sessionStorage.getItem(MOTION_SCENE_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(MOTION_SCENE_KEY);
    const v = JSON.parse(raw) as { store?: string; scene?: Record<string, unknown>; at?: number };
    if (!v || String(v.store) !== String(storeId) || !v.scene || Date.now() - Number(v.at || 0) > 10 * 60 * 1000) return null;
    return v.scene;
  } catch {
    return null;
  }
}
