/**
 * پنجرهٔ «پیش از انتشار»: «انتشار» سایت را همان لحظه روی اینترنت می‌برد؛ پس اگر هنوز متنِ نمونه، شمارهٔ ساختگی، دکمهٔ بی‌مقصد
 * یا تصویرِ انتخاب‌نشده هست، اول فهرستش را می‌بیند و باید با چشمِ باز تأیید کند.
 */
import { Modal } from "./panels";
import { Finding, groupFindings } from "./publishFindings";

const nf = new Intl.NumberFormat("fa-IR");

export type PublishCheckProps = {
  findings: Finding[];
  labelOf: (type: string) => string;
  /** صفحهٔ در حالِ ویرایش، برای این‌که «در صفحهٔ دیگر» را از «همین صفحه» جدا بنویسد. */
  here: { target: string; page: number | null };
  busy?: boolean;
  onGo: (f: Finding) => void;
  onPublish: () => void;
  onSaveOnly: () => void;
  onClose: () => void;
};

export function PublishCheckDialog({ findings, labelOf, here, busy, onGo, onPublish, onSaveOnly, onClose }: PublishCheckProps) {
  const groups = groupFindings(findings);
  return (
    <Modal title="پیش از انتشار، این‌ها را ببین" onClose={onClose} wide>
      <div className="nbe-check" data-testid="publish-check">
        <p>
          با «انتشار»، سایت همین حالا روی اینترنت می‌رود و بیننده‌ها همین‌ها را می‌بینند.{" "}
          <b data-testid="publish-check-count">{nf.format(findings.length)}</b> جا هنوز نمونه یا ناتمام است.
        </p>
        {groups.map((g) => (
          <section className="nbe-check-group" key={g.kind} data-kind={g.kind}>
            <h4>
              {g.label} <span>({nf.format(g.items.length)})</span>
            </h4>
            {g.items.map((f, i) => {
              const elsewhere = f.target !== here.target || (f.target === "page" && f.page !== here.page);
              const where = f.target === "header" ? "سربرگِ سایت" : f.target === "footer" ? "پابرگِ سایت" : f.page_title ? `صفحهٔ «${f.page_title}»` : "";
              return (
                <div className="nbe-check-row" key={`${f.id}-${f.kind}-${i}`}>
                  <span>
                    {f.text}
                    <small>
                      {labelOf(f.type) || "بخش"}
                      {elsewhere && where ? ` — ${where}` : ""}
                    </small>
                  </span>
                  <button type="button" className="nbe-add" onClick={() => onGo(f)}>
                    برو به این بلوک
                  </button>
                </div>
              );
            })}
          </section>
        ))}
        <div className="nbe-check-actions">
          <button type="button" className="nbe-primary" data-testid="publish-check-fix" onClick={onClose}>
            برو درستش کنم
          </button>
          <button type="button" className="nbe-add" data-testid="publish-check-confirm" disabled={busy} onClick={onPublish}>
            {busy ? "در حالِ انتشار…" : "بله، همین را منتشر کن"}
          </button>
          <button type="button" className="nbe-quiet" data-testid="publish-check-save" disabled={busy} onClick={onSaveOnly}>
            ذخیره بدون انتشار
          </button>
        </div>
      </div>
    </Modal>
  );
}
