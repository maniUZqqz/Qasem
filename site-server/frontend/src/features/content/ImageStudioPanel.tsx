import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import JobProgress from "../../components/JobProgress";
import {
  Button,
  Card,
  Chip,
  ErrorBox,
  Field,
  Input,
  SectionTitle,
} from "../../components/ui";
import { useJobRunner } from "../../hooks/useJobRunner";
import { GeneratedImageInfo, Job, Product } from "../../types";

const KIND_LABEL: Record<string, string> = {
  POSTER: "پوستر تبلیغاتی",
  PRODUCT_SHOT: "عکس اینستاگرامی",
  ENHANCED: "بهبود عکس محصول",
};

export default function ImageStudioPanel({ product }: { product: Product }) {
  const [images, setImages] = useState<GeneratedImageInfo[]>([]);
  const [kind, setKind] = useState<string>("POSTER");
  const [style, setStyle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [sourceImageId, setSourceImageId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<GeneratedImageInfo[]>(
        `/products/${product.id}/image-studio/`,
      );
      setImages(data);
    } catch {
      setImages([]);
    }
  }, [product.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const runner = useJobRunner(load);
  const { resume } = runner;

  // re-attach to an in-flight image job after refresh/navigation (beter.md #2)
  useEffect(() => {
    void resume({ type: "image_generation", productId: product.id });
  }, [resume, product.id]);

  const generate = async () => {
    // synchronous mode blocks inside this POST — light the progress box first
    // so the studio never looks frozen (beter.md v2 #4)
    runner.begin();
    try {
      const { data } = await api.post<{ job_id: number; job: Job }>(
        `/products/${product.id}/image-studio/`,
        { kind, style, instructions, source_image_id: sourceImageId ?? undefined },
      );
      runner.track(data.job_id, data.job);
    } catch (err) {
      runner.fail(errorMessage(err));
    }
  };

  // POSTER is also photo-based now (img2img keeps the real product in frame)
  const needsSource = kind === "ENHANCED" || kind === "PRODUCT_SHOT" || kind === "POSTER";

  return (
    <Card>
      <SectionTitle>🎨 استودیوی تصویر (FLUX)</SectionTitle>
      <ErrorBox message={runner.error} />

      <div className="mb-3 flex flex-wrap gap-2">
        {Object.keys(KIND_LABEL).map((k) => (
          <button
            key={k}
            onClick={() => setKind(k)}
            className={`rounded-full px-4 py-1.5 text-sm transition ${
              kind === k
                ? "bg-violet-600 text-white"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {KIND_LABEL[k]}
          </button>
        ))}
      </div>

      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <Field label="سبک (اختیاری)">
          <Input
            value={style}
            onChange={(e) => setStyle(e.target.value)}
            placeholder="مینیمال، لوکس، پرانرژی…"
          />
        </Field>
        <Field label="توضیحات بیشتر (اختیاری)">
          <Input
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="مثلاً پس‌زمینه روشن باشد"
          />
        </Field>
      </div>

      {needsSource && product.images.length > 0 && (
        <div className="mb-3">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            عکس مبنا (پیش‌فرض: اولین عکس)
          </span>
          <div className="flex flex-wrap gap-2">
            {product.images.map((img) => (
              <button
                key={img.id}
                onClick={() => setSourceImageId(img.id === sourceImageId ? null : img.id)}
                className={`overflow-hidden rounded-lg border-2 transition ${
                  sourceImageId === img.id ? "border-violet-600" : "border-transparent"
                }`}
              >
                <img src={img.image} alt="" className="h-16 w-16 object-cover" />
              </button>
            ))}
          </div>
        </div>
      )}
      {kind === "ENHANCED" && product.images.length === 0 && (
        <p className="mb-3 text-sm text-amber-600">
          برای بهبود عکس، اول یک عکس محصول آپلود کنید.
        </p>
      )}

      <Button
        onClick={generate}
        disabled={runner.running || (kind === "ENHANCED" && product.images.length === 0)}
      >
        {runner.running ? "در حال تولید تصویر…" : "تولید تصویر با AI"}
      </Button>
      {kind === "POSTER" && (
        <p className="mt-2 text-xs text-slate-500">
          پوستر از روی عکس واقعی محصول ساخته می‌شود و متن فارسی (عنوان + قیمت) بعد از تولید،
          توسط خود برنامه روی تصویر نوشته می‌شود — نه توسط مدل.
        </p>
      )}
      {runner.running && (
        <div className="mt-3">
          <JobProgress
            job={runner.job}
            startedAt={runner.startedAt}
            onCancel={() => void runner.cancel()}
            fallbackLabel="در حال شروع تولید تصویر…"
          />
        </div>
      )}

      {images.length > 0 && (
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {images.map((img) => (
            <div key={img.id} className="overflow-hidden rounded-lg border border-slate-200">
              <a href={img.image} target="_blank" rel="noreferrer">
                <img src={img.image} alt={img.concept} className="h-48 w-full object-cover" />
              </a>
              <div className="space-y-1 p-3">
                <Chip>{KIND_LABEL[img.kind] ?? img.kind}</Chip>
                {img.concept && (
                  <p className="text-xs leading-5 text-slate-600">{img.concept}</p>
                )}
                {/* the Persian text is drawn by code, so say whether it landed —
                    a poster whose overlay failed looks identical otherwise */}
                {img.metadata?.text_overlay && (
                  <p className="text-xs leading-5 text-slate-500">
                    متن روی تصویر: «{img.metadata.text_overlay.headline}»
                    {img.metadata.text_overlay.badge
                      ? ` · ${img.metadata.text_overlay.badge}`
                      : ""}
                  </p>
                )}
                {img.metadata?.text_overlay_error && (
                  <p className="text-xs leading-5 text-amber-600">
                    ⚠️ متن فارسی روی این تصویر نوشته نشد ({img.metadata.text_overlay_error})
                  </p>
                )}
                <p className="text-xs text-slate-400">
                  {new Date(img.created_at).toLocaleString("fa-IR")}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
