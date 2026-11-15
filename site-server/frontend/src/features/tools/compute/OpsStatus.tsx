import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../../api/client";
import { Badge, Card, Spinner } from "../../../components/ui";
import { OPS_TEXT, backupView, testsView, type OpsStatus } from "./opsModel";
import "./ops-status.css";

/**
 * دو کارتِ کوچکِ «عملیاتِ سرور» (فقط کارکنان):
 *   • BackupLine — «آخرین بکاپ» (صفحهٔ گزارشِ سرورهای پردازش): کی، چه‌قدر، آزمونِ بازیابی، و یادآوریِ «نسخهٔ بیرونی».
 *   • SiteTestsCard — «آزمون‌های شبانهٔ سایت» (صفحهٔ خودآزمایی): هر شب هر اپِ سایت جدا آزموده می‌شود؛ اپ‌های قرمز و آزمون‌هایشان این‌جاست.
 * هر دو از `/compute/ops/` می‌خوانند؛ فایل‌هایی که اسکریپت‌های deploy/nm/ops/ روی سرور می‌نویسند.
 */

function useOps(refreshMs = 60000) {
  const [data, setData] = useState<OpsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<OpsStatus>("/compute/ops/");
      setData(d);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);
  useEffect(() => {
    void load();
    const t = window.setInterval(() => {
      if (!document.hidden) void load();
    }, refreshMs);
    return () => window.clearInterval(t);
  }, [load, refreshMs]);
  return { data, error };
}

export function BackupLine() {
  const { data, error } = useOps();
  if (!data) {
    return error ? (
      <Card>
        <div className="ops-row" data-testid="ops-backup">
          <b>{OPS_TEXT.backupTitle}</b>
          <span className="ops-muted">{error}</span>
        </div>
      </Card>
    ) : null;
  }
  const v = backupView(data.backup);
  return (
    <Card>
      <div className="ops ops-backup" data-testid="ops-backup" data-state={data.backup.state}>
        <div className="ops-row">
          <b className="ops-title">{OPS_TEXT.backupTitle}</b>
          <Badge tone={v.tone}>{v.badge}</Badge>
          <span className={`ops-headline ops-${v.tone}`}>{v.headline}</span>
        </div>
        {v.lines.length > 0 && (
          <ul className="ops-lines">
            {v.lines.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        )}
        <p className="ops-note">{OPS_TEXT.offsite}</p>
      </div>
    </Card>
  );
}

export function SiteTestsCard() {
  const { data, error } = useOps();
  if (!data) {
    return (
      <Card>
        <div className="ops ops-tests" data-testid="ops-tests">
          <div className="ops-row">
            <b className="ops-title">{OPS_TEXT.testsTitle}</b>
            {error ? <span className="ops-muted">{error}</span> : <Spinner />}
          </div>
        </div>
      </Card>
    );
  }
  const t = data.tests;
  const v = testsView(t);
  return (
    <Card>
      <div className="ops ops-tests" data-testid="ops-tests" data-state={t.state}>
        <div className="ops-row">
          <b className="ops-title">{OPS_TEXT.testsTitle}</b>
          <Badge tone={v.tone}>{v.badge}</Badge>
          {t.running && (
            <Badge tone="info">
              {OPS_TEXT.testsRunning}: {t.running.app}
            </Badge>
          )}
        </div>
        <p className={`ops-headline ops-${v.tone}`}>{v.headline}</p>
        <p className="ops-note">{OPS_TEXT.testsSubtitle}</p>
        {v.tiles.length > 0 && (
          <div className="ops-tiles">
            {v.tiles.map((x) => (
              <div key={x.key} className={`ops-tile ops-tile-${x.tone}`}>
                <b>{x.value}</b>
                <span>{x.label}</span>
              </div>
            ))}
          </div>
        )}
        {v.red.length > 0 && (
          <div className="ops-red" data-testid="ops-red">
            <h3>{OPS_TEXT.testsRed}</h3>
            {v.red.map((r) => (
              <details key={r.app} className="ops-app">
                <summary>
                  <span className="ops-appname">{r.app}</span>
                  <span className="ops-muted">{r.note}</span>
                </summary>
                {r.items.length === 0 ? (
                  <p className="ops-note">{r.note}</p>
                ) : (
                  <ul className="ops-fails">
                    {r.items.map((f) => (
                      <li key={f.id}>
                        <code dir="ltr">{f.id}</code>
                        {f.message && <span dir="ltr">{f.message}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </details>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
