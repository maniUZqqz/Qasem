import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { bcApi } from "./api";

export type AgentCard = { enabled: boolean; name?: string; greeting?: string; signoff?: string; avatar?: string | null; persona_active?: boolean; persona_exists?: boolean };

/** آواتار و سلامِ ایجنتِ فروش از «شخصیتِ برند»؛ شخصیتی نباشد ⇒ null و صفحه مثلِ قبل است. */
export function useBrandAgent(storeId?: string): AgentCard | null {
  const [card, setCard] = useState<AgentCard | null>(null);
  useEffect(() => {
    if (!storeId) return;
    let live = true;
    bcApi
      .inbox(storeId)
      .then((c) => live && setCard(c.enabled ? c : null))
      .catch(() => live && setCard(null));
    return () => {
      live = false;
    };
  }, [storeId]);
  return card;
}

export function AgentAvatar({ card, size = 36 }: { card: AgentCard | null; size?: number }) {
  if (!card?.avatar) return null;
  return <img src={card.avatar} alt={card.name || "ایجنت"} width={size} height={size} style={{ width: size, height: size, objectFit: "contain", borderRadius: 12, background: "var(--surface-2)", flex: "none" }} />;
}

/** نوارِ «ایجنت با لحنِ برند جواب می‌دهد» بالای صندوقِ پیام و چتِ آزمایشی. فقط وقتی لحن واقعاً فعال است این را می‌گوید؛ وگرنه راست می‌گوید که فقط آواتار هست. */
export function AgentVoiceBanner({ card, storeId }: { card: AgentCard | null; storeId: string }) {
  if (!card) return null;
  if (card.persona_active === false) {
    return (
      <div className="u-card p-4 mb-4" data-testid="agent-voice" data-persona="inactive" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <AgentAvatar card={card} size={52} />
        <div style={{ flex: 1, minWidth: 180 }}>
          <b style={{ color: "var(--text)" }}>{card.name}</b>
          <div style={{ fontSize: 12.5, color: "var(--warning, var(--text-3))", lineHeight: 1.8 }}>
            {card.persona_exists
              ? "لحنِ شخصیتِ برند ذخیره شده ولی هنوز فعال نیست؛ تا فعال نکنید ایجنتِ فروش با لحنِ عادیِ خودش جواب می‌دهد (فقط آواتار نمایش داده می‌شود)."
              : "هنوز لحنی برای شخصیتِ برند نساخته‌اید؛ ایجنتِ فروش با لحنِ عادیِ خودش جواب می‌دهد (فقط آواتار نمایش داده می‌شود)."}
          </div>
        </div>
        <Link className="u-btn u-btn-secondary u-btn-sm" to={`/stores/${storeId}/brand-character/persona`}>
          {card.persona_exists ? "لحن را بازبینی و فعال کن" : "لحن را بساز"}
        </Link>
      </div>
    );
  }
  return (
    <div className="u-card p-4 mb-4" data-testid="agent-voice" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
      <AgentAvatar card={card} size={52} />
      <div style={{ flex: 1, minWidth: 180 }}>
        <b style={{ color: "var(--text)" }}>{card.name}</b>
        <div style={{ fontSize: 12.5, color: "var(--text-3)", lineHeight: 1.8 }}>
          ایجنتِ فروش با لحنِ شخصیتِ برند جواب می‌دهد{card.greeting ? ` — سلام: «${card.greeting}»` : ""}
        </div>
      </div>
      <Link className="u-btn u-btn-ghost u-btn-sm" to={`/stores/${storeId}/brand-character/persona`}>
        لحن را ویرایش کن
      </Link>
    </div>
  );
}
