import { Dispatch, SetStateAction } from "react";

import { Alert } from "../../../../components/ui";
import { fa } from "../api";
import { IssuesPanel } from "../editor/BottomPanels";
import { PreviewPanel, ProjectJobs } from "../editor/SidePanels";
import QualityPanel from "../editor/QualityPanel";
import type { Catalog, Estimate, Issue, Project, QualityOverride } from "../types";

/**
 * «رندر» از داخلِ ویرایشگرِ آزاد: همان بخشِ «کیفیت و رندر» (پروفایل‌ها، تنظیمِ دستی، تخمین از آمارِ کارگرها،
 * اول GPU) + کارهای این پروژه با وضعیتِ زنده + آخرین ویدئو. صحنه پیش از شروع خودکار ذخیره و وارسی می‌شود.
 */
export default function RenderDrawer({
  cat,
  proj,
  aspect,
  issues,
  profile,
  setProfile,
  quality,
  setQuality,
  est,
  setEst,
  onRender,
  onCancel,
  onAllowCpu,
  onPickIssue,
  onClose,
}: {
  cat: Catalog;
  proj: Project;
  aspect: string;
  issues: Issue[];
  profile: string;
  setProfile: (id: string) => void;
  quality: QualityOverride | null;
  setQuality: (q: QualityOverride | null) => void;
  est: Record<string, Estimate>;
  setEst: Dispatch<SetStateAction<Record<string, Estimate>>>;
  onRender: (profile: string, allowCpu: boolean, q: QualityOverride | null) => void;
  onCancel: (id: number) => void;
  onAllowCpu: (id: number) => void;
  onPickIssue: (path: string) => void;
  onClose: () => void;
}) {
  const errors = issues.filter((i) => i.level === "error");
  return (
    <div className="u3e-drawer" role="dialog" aria-label="رندر">
      <div className="u3e-drawer-h">
        <b>رندرِ ویدئو</b>
        <button type="button" className="u3e-tbtn" onClick={onClose} aria-label="بستن">
          ×
        </button>
      </div>
      <div className="u3e-drawer-b">
        {errors.length > 0 && (
          <Alert tone="warn" title={`صحنه ${fa(errors.length)} ایرادِ جدی دارد`}>
            پیش از رندر «ترمیمِ خودکار» را بزنید یا ایرادها را درست کنید.
            <IssuesPanel issues={issues} onPick={onPickIssue} />
          </Alert>
        )}
        {profile && (
          <QualityPanel
            cat={cat}
            pid={proj.id}
            version={proj.version}
            aspect={aspect}
            profile={profile}
            setProfile={setProfile}
            quality={quality}
            setQuality={setQuality}
            est={est}
            setEst={setEst}
            onRender={onRender}
          />
        )}
        <b className="mt-3 block text-sm" style={{ color: "var(--text)" }}>
          کارهای این پروژه
        </b>
        <ProjectJobs jobs={proj.jobs} onCancel={onCancel} onAllowCpu={onAllowCpu} />
        <b className="mt-3 block text-sm" style={{ color: "var(--text)" }}>
          خروجی‌ها
        </b>
        <PreviewPanel proj={proj} />
      </div>
    </div>
  );
}
