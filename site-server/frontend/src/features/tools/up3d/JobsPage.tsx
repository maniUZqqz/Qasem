import { useState } from "react";
import { Link } from "react-router-dom";

import { Card, EmptyState, ErrorBox, PageHeader, Spinner, Table } from "../../../components/ui";
import { P, dur, errMsg, fa, up3d, when } from "./api";
import { Bar, StateBadge, usePoll } from "./shared";
import type { Job } from "./types";

/** فهرستِ همهٔ کارها؛ هر ۴ ثانیه به‌روز می‌شود. */
export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  usePoll(
    async () => {
      try {
        setJobs(await up3d.jobs());
        setError(null);
      } catch (e) {
        setError(errMsg(e));
      }
    },
    4000,
    [],
  );

  return (
    <div className="space-y-4">
      <PageHeader title="کارها" subtitle="هر ۴ ثانیه به‌روز می‌شود" />
      <ErrorBox message={error} />
      {jobs === null ? (
        <div className="py-10 text-center">
          <Spinner />
        </div>
      ) : jobs.length === 0 ? (
        <Card>
          <EmptyState icon="clock" title="کاری نیست" description="با «پروژهٔ تازه» یا دکمه‌های رندرِ هر پروژه، کار ساخته می‌شود." />
        </Card>
      ) : (
        <Card padded={false}>
          <Table>
            <thead>
              <tr>
                <th>#</th>
                <th>نوع</th>
                <th>پروژه</th>
                <th>پروفایل</th>
                <th>وضعیت</th>
                <th style={{ width: "28%" }}>پیشرفت</th>
                <th>کارگر</th>
                <th>زمان</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td className="u-num">
                    <Link to={P.job(j.id)} style={{ color: "var(--brand-strong)" }}>
                      {fa(j.id)}
                    </Link>
                  </td>
                  <td>{j.kind_label}</td>
                  <td>
                    {j.project ? (
                      <Link to={P.project(j.project)} style={{ color: "var(--text)" }}>
                        {j.project_title || `#${fa(j.project)}`}
                      </Link>
                    ) : (
                      "—"
                    )}
                    {j.version ? <span style={{ color: "var(--text-3)" }}> · v{fa(j.version)}</span> : null}
                  </td>
                  <td className="u3d-mono">{j.profile || ""}</td>
                  <td>
                    <StateBadge job={j} />
                  </td>
                  <td>
                    {!j.final && <Bar value={j.progress} />}
                    <div className="text-xs" style={{ color: "var(--text-3)" }}>
                      {j.message || ""}
                    </div>
                  </td>
                  <td>{j.worker || "—"}</td>
                  <td className="text-xs">{j.eta_seconds ? `مانده ${dur(j.eta_seconds)}` : j.finished ? when(j.finished) : ""}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}
