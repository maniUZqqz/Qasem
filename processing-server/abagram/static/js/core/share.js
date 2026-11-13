// «تقسیم کار» (Settings; server: ig_share.py): several copies of آباگرام on different computers split the work, and every page
// belongs to one system. Queueing a page that is another system's share asks first; «با این حال» sends it again with force.
import { confirm } from "./overlay.js";
import { faNum } from "./format.js";

/** call(force) → {ok, status, data}. Resolves the final answer; {declined: true} when he chose not to do it here. */
export async function mineOrAsk(call) {
  const r = await call(false);
  if (r?.status !== 409 || r.data?.detail !== "not_mine") return r;
  const d = r.data;
  const yes = await confirm({
    title: `این پیج سهمِ سیستمِ ${faNum(d.owner)} است`,
    text: `کار بین ${faNum(d.count)} سیستم تقسیم شده و این سیستمِ ${faNum(d.index)} است. اگر این‌جا هم انجام شود، همین پیج در دو سیستم خوانده می‌شود و وقت هدر می‌رود.`,
    cta: "با این حال همین‌جا انجام بده",
  });
  return yes ? call(true) : { ok: false, status: 409, data: d, declined: true };
}
