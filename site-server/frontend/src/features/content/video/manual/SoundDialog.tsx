import { ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import "./sound.css";

/**
 * پنجرهٔ گفت‌وگوی مشترکِ «انتخابِ موسیقی» و «گویندگی از متن». روی بدنهٔ صفحه (portal) باز می‌شود تا درونِ پنلِ بازرس بریده نشود؛
 * کلیدهای صفحه‌کلید به میان‌برهای تایم‌لاین (Space، Delete، …) نمی‌رسند؛ Esc و کلیک روی پس‌زمینه می‌بندد.
 */
export default function SoundDialog({ title, testId, onClose, children }: { title: string; testId: string; onClose: () => void; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    box.current?.focus();
  }, []);
  return createPortal(
    <div className="sq-back" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        ref={box} className="sq-modal" role="dialog" aria-modal="true" aria-label={title} data-testid={testId} dir="rtl" tabIndex={-1}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Escape") onClose();
        }}
        onKeyUp={(e) => e.stopPropagation()}
      >
        <div className="sq-modal-head">
          <b>{title}</b>
          <button type="button" className="ws-btn sq-x" onClick={onClose} aria-label="بستن" title="بستن">×</button>
        </div>
        <div className="sq-modal-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
