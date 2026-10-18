import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import JobProgress from "../../components/JobProgress";
import { Button, Card, Chip, ErrorBox, Field, Input, SectionTitle } from "../../components/ui";
import { useJobRunner } from "../../hooks/useJobRunner";
import { Caption, GeneratedImageInfo, Job, VideoScriptInfo } from "../../types";

const PLATFORM_LABEL: Record<string, string> = {
  INSTAGRAM: "اینستاگرام",
  TELEGRAM: "تلگرام",
  LINKEDIN: "لینکدین",
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        void navigator.clipboard.writeText(text);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
      className="text-xs text-violet-600 hover:underline"
    >
      {copied ? "کپی شد ✓" : "کپی"}
    </button>
  );
}

export default function CaptionsPanel({ productId }: { productId: number }) {
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [platforms, setPlatforms] = useState<string[]>(["INSTAGRAM", "TELEGRAM", "LINKEDIN"]);
  const [tone, setTone] = useState("");
  const [objective, setObjective] = useState("");
  // beter.md #11: the caption is written FOR a content item, not the bare product
  const [images, setImages] = useState<GeneratedImageInfo[]>([]);
  const [videoScript, setVideoScript] = useState<VideoScriptInfo | null>(null);
  const [subject, setSubject] = useState<
    { kind: "PRODUCT" } | { kind: "IMAGE"; id: number } | { kind: "VIDEO"; id: number }
  >({ kind: "PRODUCT" });

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Caption[]>(`/products/${productId}/captions/`);
      setCaptions(data);
    } catch {
      setCaptions([]);
    }
  }, [productId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void api
      .get<GeneratedImageInfo[]>(`/products/${productId}/image-studio/`)
      .then((r) => setImages(r.data))
      .catch(() => setImages([]));
    void api
      .get<VideoScriptInfo | null>(`/products/${productId}/video-script/`)
      .then((r) => setVideoScript(r.data ?? null))
      .catch(() => setVideoScript(null));
  }, [productId]);

  const runner = useJobRunner(load);
  const { resume } = runner;

  // re-attach to an in-flight caption job after refresh/navigation (beter.md #2)
  useEffect(() => {
    void resume({ type: "caption_generation", productId });
  }, [resume, productId]);

  const generate = async () => {
    runner.begin();
    try {
      const { data } = await api.post<{ job_id: number; job: Job }>(
        `/products/${productId}/captions/`,
        {
          platforms,
          tone,
          objective,
          image_id: subject.kind === "IMAGE" ? subject.id : undefined,
          video_script_id: subject.kind === "VIDEO" ? subject.id : undefined,
        },
      );
      runner.track(data.job_id, data.job);
    } catch (err) {
      runner.fail(errorMessage(err));
    }
  };

  const togglePlatform = (p: string) =>
    setPlatforms((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));

  return (
    <Card>
      <SectionTitle>✍️ کپشن‌ها</SectionTitle>
      <ErrorBox message={runner.error} />

      <div className="mb-3">
        <span className="mb-1 block text-sm font-medium text-slate-700">
          کپشن برای چه محتوایی نوشته شود؟
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setSubject({ kind: "PRODUCT" })}
            className={`rounded-full px-3 py-1 text-xs transition ${
              subject.kind === "PRODUCT"
                ? "bg-violet-600 text-white"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            خود محصول
          </button>
          {videoScript && (
            <button
              onClick={() => setSubject({ kind: "VIDEO", id: videoScript.id })}
              className={`rounded-full px-3 py-1 text-xs transition ${
                subject.kind === "VIDEO"
                  ? "bg-violet-600 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              🎬 ویدیوی تبلیغاتی
            </button>
          )}
          {images.slice(0, 8).map((img) => (
            <button
              key={img.id}
              onClick={() => setSubject({ kind: "IMAGE", id: img.id })}
              title={img.concept}
              className={`overflow-hidden rounded-lg border-2 transition ${
                subject.kind === "IMAGE" && subject.id === img.id
                  ? "border-violet-600"
                  : "border-transparent opacity-80 hover:opacity-100"
              }`}
            >
              <img src={img.image} alt={img.concept} className="h-12 w-12 object-cover" />
            </button>
          ))}
        </div>
        {images.length === 0 && !videoScript && (
          <p className="mt-1 text-xs text-slate-400">
            هنوز محتوایی (پوستر/عکس/ویدیو) تولید نشده — کپشن برای خود محصول نوشته می‌شود.
          </p>
        )}
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <div>
          <span className="mb-1 block text-sm font-medium text-slate-700">پلتفرم‌ها</span>
          <div className="flex flex-wrap gap-2">
            {Object.keys(PLATFORM_LABEL).map((p) => (
              <button
                key={p}
                onClick={() => togglePlatform(p)}
                className={`rounded-full px-3 py-1 text-xs transition ${
                  platforms.includes(p)
                    ? "bg-violet-600 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {PLATFORM_LABEL[p]}
              </button>
            ))}
          </div>
        </div>
        <Field label="لحن (اختیاری)">
          <Input value={tone} onChange={(e) => setTone(e.target.value)} placeholder="صمیمی، لوکس…" />
        </Field>
        <Field label="هدف کمپین (اختیاری)">
          <Input
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="مثلاً فروش پاییزه"
          />
        </Field>
      </div>
      <Button onClick={generate} disabled={runner.running || platforms.length === 0}>
        {runner.running ? "در حال نوشتن…" : "تولید کپشن با AI"}
      </Button>
      {runner.running && (
        <div className="mt-3">
          <JobProgress
            job={runner.job}
            startedAt={runner.startedAt}
            onCancel={() => void runner.cancel()}
            fallbackLabel="در حال شروع نوشتن کپشن…"
          />
        </div>
      )}

      {captions.length > 0 && (
        <div className="mt-5 grid gap-4 lg:grid-cols-3">
          {captions.slice(0, 6).map((caption) => (
            <div key={caption.id} className="rounded-lg border border-slate-200 p-4">
              <div className="mb-2 flex items-center justify-between">
                <Chip>{PLATFORM_LABEL[caption.platform] ?? caption.platform}</Chip>
                <span className="text-xs text-slate-400">
                  {new Date(caption.created_at).toLocaleDateString("fa-IR")}
                </span>
              </div>
              <div className="mb-2 flex items-center gap-2">
                {caption.about_image_url && (
                  <img
                    src={caption.about_image_url}
                    alt=""
                    className="h-8 w-8 rounded object-cover"
                  />
                )}
                <span className="text-[10px] text-slate-500">{caption.about_label}</span>
              </div>
              <div className="space-y-3 text-sm text-slate-700">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-500">کوتاه (استوری)</span>
                    <CopyButton text={caption.short_text} />
                  </div>
                  <p className="whitespace-pre-wrap">{caption.short_text}</p>
                </div>
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-500">متوسط (پست)</span>
                    <CopyButton text={caption.medium_text} />
                  </div>
                  <p className="line-clamp-4 whitespace-pre-wrap">{caption.medium_text}</p>
                </div>
                {caption.cta && <p className="text-xs text-violet-700">CTA: {caption.cta}</p>}
                {caption.hashtags.length > 0 && (
                  <p className="text-xs text-slate-500">{caption.hashtags.join(" ")}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
