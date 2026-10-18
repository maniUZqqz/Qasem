import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, errorMessage, fetchAllPages } from "../../api/client";
import Icon from "../../components/Icon";
import CampaignBoard from "./CampaignBoard";
import {
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorBox,
  Field,
  Input,
  SectionTitle,
  Spinner,
} from "../../components/ui";
import { useJobRunner } from "../../hooks/useJobRunner";
import {
  ApprovalState,
  CampaignInfo,
  Caption,
  GeneratedImageInfo,
  Job,
  Product,
  VideoScriptInfo,
} from "../../types";

const STATE_LABEL: Record<ApprovalState, string> = {
  DRAFT: "پیش‌نویس",
  APPROVED: "تأییدشده ✓",
  REJECTED: "ردشده",
  PUBLISHED: "منتشرشده 🚀",
  ARCHIVED: "آرشیو",
};

const STATE_STYLE: Record<ApprovalState, string> = {
  DRAFT: "bg-slate-100 text-slate-600",
  APPROVED: "bg-green-100 text-green-800",
  REJECTED: "bg-red-100 text-red-700",
  PUBLISHED: "bg-violet-100 text-violet-800",
  ARCHIVED: "bg-slate-200 text-slate-500",
};

const PLATFORMS = [
  { key: "instagram", label: "اینستاگرام" },
  { key: "telegram", label: "تلگرام" },
  { key: "linkedin", label: "لینکدین" },
];

function CampaignCard({ campaign, onChanged }: { campaign: CampaignInfo; onChanged: () => void }) {
  const [platforms, setPlatforms] = useState<string[]>(["instagram"]);
  const [error, setError] = useState<string | null>(null);
  const [when, setWhen] = useState("");
  const [scheduling, setScheduling] = useState(false);
  const [scheduled, setScheduled] = useState<string | null>(null);
  const runner = useJobRunner(onChanged);

  const act = async (action: "approve" | "reject") => {
    setError(null);
    try {
      await api.post(`/campaigns/${campaign.id}/${action}/`);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const publish = async () => {
    setError(null);
    runner.begin();
    try {
      const { data } = await api.post<{ job_id: number; job: Job }>(
        `/campaigns/${campaign.id}/publish/`,
        { platforms },
      );
      runner.track(data.job_id, data.job);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  /** زمان‌بندی انتشار برای آینده.
   *
   *  `datetime-local` زمان را بدون منطقه‌ی زمانی می‌دهد؛ ساختن `Date` از
   *  آن، وقت محلی را می‌گیرد و `toISOString` آن را درست به UTC می‌برد —
   *  که همان چیزی است که سرور انتظار دارد. فرستادن رشته‌ی خام یعنی روی
   *  مرورگری با منطقه‌ی دیگر، پست چند ساعت جابه‌جا می‌رود. */
  const scheduleIt = async () => {
    setError(null);
    setScheduled(null);
    const at = new Date(when);
    if (!when || Number.isNaN(at.getTime())) {
      setError("زمان انتشار خوانده نشد.");
      return;
    }
    if (at <= new Date()) {
      setError("زمان انتشار باید در آینده باشد.");
      return;
    }
    setScheduling(true);
    try {
      await api.post(`/campaigns/${campaign.id}/schedule/`, {
        when: at.toISOString(),
        platforms,
      });
      setScheduled(
        at.toLocaleString("fa-IR", {
          month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
        }),
      );
      setWhen("");
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setScheduling(false);
    }
  };

  const pieces: Array<[string, boolean]> = [
    ["پوستر", campaign.poster !== null],
    ["عکس محصول", campaign.product_image !== null],
    ["کپشن", campaign.caption !== null],
    ["ویدیو", campaign.video_script_detail?.final_video != null],
  ];

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-bold text-slate-800">{campaign.name}</h3>
          {campaign.goal && <p className="text-xs text-slate-500">هدف: {campaign.goal}</p>}
        </div>
        <span className={`rounded-full px-3 py-1 text-xs ${STATE_STYLE[campaign.approval_state]}`}>
          {STATE_LABEL[campaign.approval_state]}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {pieces.map(([label, present]) => (
          <span
            key={label}
            className={`rounded-full px-3 py-1 text-xs ${
              present ? "bg-green-50 text-green-700" : "bg-slate-100 text-slate-400"
            }`}
          >
            {label} {present ? "✓" : "—"}
          </span>
        ))}
      </div>

      {(campaign.poster_detail || campaign.product_image_detail) && (
        <div className="mt-3 flex gap-2">
          {campaign.poster_detail && (
            <img
              src={campaign.poster_detail.image}
              alt="پوستر"
              className="h-20 w-20 rounded-lg object-cover"
            />
          )}
          {campaign.product_image_detail && (
            <img
              src={campaign.product_image_detail.image}
              alt="عکس محصول"
              className="h-20 w-20 rounded-lg object-cover"
            />
          )}
        </div>
      )}

      <ErrorBox message={error || runner.error} />

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {campaign.approval_state !== "PUBLISHED" && (
          <>
            <Button onClick={() => void act("approve")} disabled={runner.running}>
              تأیید
            </Button>
            <Button variant="danger" onClick={() => void act("reject")} disabled={runner.running}>
              رد
            </Button>
          </>
        )}
        {(campaign.approval_state === "APPROVED" || campaign.approval_state === "PUBLISHED") && (
          <div className="flex flex-wrap items-center gap-2">
            {PLATFORMS.map((p) => (
              <label key={p.key} className="flex items-center gap-1 text-xs text-slate-600">
                <input
                  type="checkbox"
                  checked={platforms.includes(p.key)}
                  onChange={() =>
                    setPlatforms((prev) =>
                      prev.includes(p.key)
                        ? prev.filter((x) => x !== p.key)
                        : [...prev, p.key],
                    )
                  }
                />
                {p.label}
              </label>
            ))}
            <Button
              variant="secondary"
              onClick={publish}
              disabled={runner.running || platforms.length === 0}
            >
              <Icon name="rocket" size={15} />
              {runner.running ? "در حال ارسال…" : "انتشار حالا"}
            </Button>
          </div>
        )}
      </div>

      {/* زمان‌بندی: بک‌اندش از فاز ۲۴ آماده بود و هیچ دکمه‌ای نداشت.
          فقط روی کمپین تأییدشده، چون زمان‌بندیِ چیزی که هنوز تأیید نشده
          یعنی سپردن تصمیم به ساعت به‌جای آدم. */}
      {campaign.approval_state === "APPROVED" && (
        <div
          className="mt-3 flex flex-wrap items-end gap-2 rounded-xl p-3"
          style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
        >
          <label className="flex-1" style={{ minWidth: 200 }}>
            <span className="mb-1 block text-xs" style={{ color: "var(--text-2)" }}>
              یا برای بعد زمان‌بندی کن
            </span>
            <input
              type="datetime-local"
              className="u-input"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
            />
          </label>
          <Button
            variant="secondary"
            onClick={scheduleIt}
            disabled={scheduling || !when || platforms.length === 0}
          >
            <Icon name="clock" size={15} />
            {scheduling ? "…" : "زمان‌بندی"}
          </Button>
          {scheduled && (
            <span className="text-xs" style={{ color: "var(--ok)" }}>
              برای {scheduled} در صف نشست.
            </span>
          )}
        </div>
      )}

      {campaign.publish_jobs.length > 0 && (
        <div className="mt-3 space-y-1 text-xs">
          {campaign.publish_jobs.map((pj) => (
            <div key={pj.id} className="flex items-center gap-2">
              <span className="font-semibold">{pj.platform}</span>
              <span
                className={
                  pj.status === "SENT"
                    ? "text-green-700"
                    : pj.status === "FAILED"
                      ? "text-red-600"
                      : "text-slate-500"
                }
              >
                {pj.status === "SENT" ? "ارسال شد ✓" : pj.status === "FAILED" ? "خطا" : "در انتظار"}
              </span>
              {pj.last_error && <span className="text-red-500">{pj.last_error}</span>}
            </div>
          ))}
        </div>
      )}

      <CampaignBoard campaignId={campaign.id} />
    </Card>
  );
}

/** فهرست کمپین‌ها و فرم ساخت. سربرگ و تب‌ها در `CampaignsLayout` است. */
export default function CampaignListPage() {
  const { id: storeId } = useParams<{ id: string }>();
  const [campaigns, setCampaigns] = useState<CampaignInfo[] | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);

  // create-form state
  const [productId, setProductId] = useState<string>("");
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [images, setImages] = useState<GeneratedImageInfo[]>([]);
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [script, setScript] = useState<VideoScriptInfo | null>(null);
  const [posterId, setPosterId] = useState<string>("");
  const [productImageId, setProductImageId] = useState<string>("");
  const [captionId, setCaptionId] = useState<string>("");
  const [useScript, setUseScript] = useState(true);

  const load = useCallback(async () => {
    try {
      const [campaignList, productList] = await Promise.all([
        fetchAllPages<CampaignInfo>(`/campaigns/?store=${storeId}`),
        fetchAllPages<Product>(`/products/?store=${storeId}`),
      ]);
      setCampaigns(campaignList);
      setProducts(productList);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!productId) {
      setImages([]);
      setCaptions([]);
      setScript(null);
      return;
    }
    void api
      .get<GeneratedImageInfo[]>(`/products/${productId}/image-studio/`)
      .then((r) => setImages(r.data))
      .catch(() => setImages([]));
    void api
      .get<Caption[]>(`/products/${productId}/captions/`)
      .then((r) => setCaptions(r.data))
      .catch(() => setCaptions([]));
    void api
      .get<VideoScriptInfo>(`/products/${productId}/video-script/`)
      .then((r) => setScript(r.data))
      .catch(() => setScript(null));
  }, [productId]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/campaigns/", {
        product: Number(productId),
        name,
        goal,
        poster: posterId ? Number(posterId) : null,
        product_image: productImageId ? Number(productImageId) : null,
        caption: captionId ? Number(captionId) : null,
        video_script: useScript && script ? script.id : null,
      });
      setShowForm(false);
      setName("");
      setGoal("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const posters = images.filter((i) => i.kind === "POSTER");
  const productShots = images.filter((i) => i.kind !== "POSTER");

  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <Button onClick={() => setShowForm((v) => !v)} variant={showForm ? "secondary" : "primary"}>
          <Icon name={showForm ? "x" : "plus"} size={15} />
          {showForm ? "بستن فرم" : "کمپین جدید"}
        </Button>
      </div>
      <ErrorBox message={error} />

      {showForm && (
        <Card>
          <SectionTitle>کمپین جدید</SectionTitle>
          <form onSubmit={create} className="grid gap-4 sm:grid-cols-2">
            <Field label="محصول *">
              <select
                value={productId}
                onChange={(e) => setProductId(e.target.value)}
                required
                className="u-input"
              >
                <option value="">— انتخاب محصول —</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="نام کمپین *">
              <Input value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="هدف">
              <Input value={goal} onChange={(e) => setGoal(e.target.value)} />
            </Field>
            <Field label="پوستر (از استودیوی تصویر)">
              <select
                value={posterId}
                onChange={(e) => setPosterId(e.target.value)}
                className="u-input"
              >
                <option value="">— هیچ —</option>
                {posters.map((img) => (
                  <option key={img.id} value={img.id}>
                    پوستر #{img.id} — {img.concept.slice(0, 40)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="عکس محصول">
              <select
                value={productImageId}
                onChange={(e) => setProductImageId(e.target.value)}
                className="u-input"
              >
                <option value="">— هیچ —</option>
                {productShots.map((img) => (
                  <option key={img.id} value={img.id}>
                    تصویر #{img.id} — {img.concept.slice(0, 40)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="کپشن">
              <select
                value={captionId}
                onChange={(e) => setCaptionId(e.target.value)}
                className="u-input"
              >
                <option value="">— هیچ —</option>
                {captions.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.platform} — {c.short_text.slice(0, 40)}
                  </option>
                ))}
              </select>
            </Field>
            {script?.final_video && (
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={useScript}
                  onChange={(e) => setUseScript(e.target.checked)}
                />
                استفاده از ویدیوی تولیدشده ({script.total_duration} ثانیه)
              </label>
            )}
            <div>
              <Button type="submit" disabled={busy || !productId}>
                {busy ? "در حال ساخت…" : "ساخت کمپین"}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {campaigns === null ? (
        <div className="py-10 text-center">
          <Spinner />
        </div>
      ) : campaigns.length === 0 ? (
        <EmptyState>
          هنوز کمپینی ندارید. محتوا را در صفحه محصول تولید کنید، بعد این‌جا یک کمپین بسازید،
          تأیید کنید و منتشر کنید.
        </EmptyState>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {campaigns.map((campaign) => (
            <CampaignCard key={campaign.id} campaign={campaign} onChanged={load} />
          ))}
        </div>
      )}
    </div>
  );
}
