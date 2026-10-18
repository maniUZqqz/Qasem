import { useCallback, useEffect, useState } from "react";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState } from "../../../components/ui";
import { api, fa, studioError } from "./api";
import { CopyButton, Loading, Mono, Pre, PreviewFrame, SectionHead } from "./common";
import { useProject } from "./shell";
import type { PreviewResp } from "./types";

/** پیش‌نمایشِ زنده — پروژه روی یک پورتِ جدا از همین سرور */
export default function PreviewPage() {
  const { slug, project, notify, buildCount } = useProject();
  const [data, setData] = useState<PreviewResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [tick, setTick] = useState(0);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<PreviewResp>(`/studio/projects/${slug}/preview/`);
      setData(d);
      setError(null);
    } catch (err) {
      setError(studioError(err));
    }
  }, [slug]);

  useEffect(() => {
    void load();
  }, [load, buildCount]);

  async function act(what: "start" | "stop") {
    setBusy(true);
    try {
      const { data: d } = await api.post<PreviewResp>(`/studio/projects/${slug}/preview/${what}/`, {});
      setData(d);
      if (d.message) notify(d.message, d.ok ? "ok" : "bad");
      setTick((t) => t + 1);
    } catch (err) {
      notify(studioError(err), "bad");
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <Loading error={error} />;

  const actions = data.running ? (
    <>
      <a href={data.url} target="_blank" rel="noreferrer" className="no-underline">
        <Button variant="ghost" size="sm">بازکردن در تبِ جدا ↗</Button>
      </a>
      <Button variant="danger" size="sm" onClick={() => act("stop")} disabled={busy}>
        {busy ? "…" : "خاموش"}
      </Button>
    </>
  ) : data.exists_on_disk ? (
    <Button size="sm" onClick={() => act("start")} disabled={busy}>
      <Icon name="play" size={14} />
      {busy ? "در حالِ روشن‌کردن…" : "روشن کن"}
    </Button>
  ) : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm" style={{ color: "var(--text-3)" }}>
          پیش‌نمایشِ زنده
        </span>
        <div className="ms-auto flex gap-2">{actions}</div>
      </div>

      {!data.exists_on_disk ? (
        <Card>
          <EmptyState title="هنوز کدی تولید نشده">اول «تولیدِ کد» را بزن.</EmptyState>
        </Card>
      ) : !data.running ? (
        <Card>
          <SectionHead title="پیش‌نمایش خاموش است" />
          <p className="text-sm leading-7" style={{ color: "var(--text-3)" }}>
            با «روشن کن»، پروژه روی یک پورتِ جدا از همین سرور اجرا می‌شود — دقیقاً همان‌طور که روی سرورِ خودت اجرا خواهد
            شد. مهاجرت‌ها خودکار اجرا می‌شوند و یک کاربرِ ادمین با رمزِ تازه ساخته می‌شود.
            {project.is_imported && !data.own_env && (
              <>
                <br />
                پروژهٔ واردشده با پایتونِ استودیو اجرا می‌شود؛ اگر بسته‌ای کم بود، در «گزارشِ سازگاری» «نصبِ وابستگی‌ها» را
                بزن.
              </>
            )}
          </p>
          <Button onClick={() => act("start")} disabled={busy} className="mt-3">
            <Icon name="play" size={15} />
            {busy ? "در حالِ روشن‌کردن… (تا ۱۵ ثانیه)" : "روشن کن"}
          </Button>
          {data.log && (
            <div className="mt-4">
              <SectionHead title={<span className="text-sm">آخرین لاگ</span>} />
              <Pre text={data.log} maxHeight={300} />
            </div>
          )}
        </Card>
      ) : (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone="ok">
                <Icon name="ok" size={12} />
                در حالِ اجرا
              </Badge>
              <Mono>{data.url}</Mono>
              <span className="text-sm" style={{ color: "var(--text-3)" }}>
                پورت {fa(data.port ?? 0)} · pid {fa(data.pid ?? 0)}
              </span>
              <div className="ms-auto flex gap-2">
                <a href={`${data.url}admin/`} target="_blank" rel="noreferrer" className="no-underline">
                  <Button variant="ghost" size="sm">ادمینِ سایت ↗</Button>
                </a>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    void load();
                    setTick((t) => t + 1);
                  }}
                >
                  <Icon name="refresh" size={14} />
                  تازه کن
                </Button>
              </div>
            </div>
          </Card>
          {data.admin_user && (
            <Alert tone="info">
              ادمینِ سایتِ پیش‌نمایش — نامِ کاربری: <Mono>{data.admin_user}</Mono> · رمز: <Mono>{data.admin_password}</Mono>{" "}
              <CopyButton text={data.admin_password} />{" "}
              <span style={{ color: "var(--text-3)" }}>(هر بار روشن‌کردن، رمزِ تازه)</span>
            </Alert>
          )}
          <PreviewFrame key={tick} src={data.url} address={data.url} height="calc(100vh - 260px)" title="پیش‌نمایشِ زنده" />
          {data.log && (
            <Card>
              <SectionHead
                title={<span className="text-sm">لاگِ سرور</span>}
                action={
                  <Button variant="ghost" size="sm" onClick={() => setShowLog(!showLog)}>
                    {showLog ? "بستن" : "نشان بده"}
                  </Button>
                }
              />
              {showLog && <Pre text={data.log} maxHeight={320} />}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
