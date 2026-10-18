import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Button, Card, ErrorBox, Field, Input, TextArea } from "../../../components/ui";
import { api, fieldErrors, pUrl, studioError } from "./api";
import { Check, Help, Pre, SectionHead } from "./common";
import type { ProjectDetail } from "./types";

type CreateResp = { project: ProjectDetail; message: string; warning: string; next: "ai" | "detail" };

const TREE = `<slug>/
├── manage.py · requirements.txt · .env.example · README.md
├── config/        settings · urls · views · context
├── apps/
│   ├── catalog/   Category · Product
│   ├── orders/    Order · OrderItem
│   └── cart/      سبدِ خرید روی session
├── templates/
│   ├── base.html
│   ├── components/  header · footer · product_card
│   └── pages/       home · products · product_detail · cart · checkout
├── static/css/    base.css · pages/*.css
└── .git/          هر «تولیدِ کد» یک نسخه`;

const STEPS: [string, string][] = [
  ["تنظیمات", "زبان، منطقهٔ زمانی، اپ‌های بیرونی و … ِ settings.py."],
  ["اپ‌ها و مدل‌ها", "اپ، مدل، فیلد و رابطه؛ نمودارِ رابطه‌ها را ببین."],
  ["نشانی‌ها و ویوها", "فهرست/جزئیات/ساخت/ویرایش/حذف با یک کلیک؛ هر URL گرافیکی."],
  ["فرانت", "هدر و فوتر یک‌بار، بدنهٔ هر صفحه جدا؛ دستی یا با هوشِ مصنوعی (با Diff و تأیید)."],
  ["تولیدِ کد", "فایل‌های واقعی نوشته، وارسی و نسخه‌بندی می‌شوند."],
  ["پیش‌نمایش و ZIP", "سایت را همین‌جا ببین و خروجیِ مستقل بگیر."],
];

/** پروژهٔ تازه */
export default function ProjectCreatePage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState("#2f6df6");
  const [scaffold, setScaffold] = useState(true);
  const [thenAi, setThenAi] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setErrors({});
    try {
      const { data } = await api.post<CreateResp>("/studio/projects/", {
        name,
        slug,
        description,
        brand_color: color,
        scaffold,
        then_ai: thenAi,
      });
      navigate(pUrl(data.project.slug, data.next === "ai" ? "ai" : ""), {
        state: { notice: { text: data.message, tone: data.warning ? "warn" : "ok" } },
      });
    } catch (err) {
      setError(studioError(err));
      setErrors(fieldErrors(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <SectionHead title="مشخصاتِ فروشگاه" />
        <form onSubmit={submit} className="space-y-4">
          <ErrorBox message={error} />
          <Field label="نامِ فروشگاه" hint={errors.name}>
            <Input value={name} onChange={(e) => setName(e.target.value)} required autoFocus placeholder="مثلاً فروشگاهِ پوشاکِ آرام" />
          </Field>
          <Field label="شناسهٔ انگلیسی (نامِ پوشه)" hint={errors.slug ?? "فقط حروفِ کوچک، عدد و خط‌تیره. خالی بگذاری خودش می‌سازد."}>
            <Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="aram-shop" pattern="[a-z0-9-]*" dir="ltr" />
          </Field>
          <Field label="توضیحِ فروشگاه (برای هوشِ مصنوعی هم استفاده می‌شود)">
            <TextArea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              placeholder="چه می‌فروشد، برای چه کسانی، لحنِ سایت، حس و رنگ… مثلاً: فروشگاهِ لوازمِ کوهنوردی، جوان و پرانرژی، رنگ‌های طبیعی"
            />
          </Field>
          <div>
            <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
              رنگِ برند
            </span>
            <div className="flex items-center gap-3">
              <input
                type="color"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                className="h-10 w-14 cursor-pointer rounded-lg"
                style={{ border: "1px solid var(--line)", background: "var(--surface-2)", padding: 3 }}
              />
              <span className="text-sm" style={{ color: "var(--text-3)" }}>
                رنگِ دکمه‌ها و لینک‌های سایتِ تولیدی
              </span>
            </div>
          </div>
          <div className="flex flex-wrap gap-4">
            <Check label="قالبِ استانداردِ فروشگاه را بساز" checked={scaffold} onChange={setScaffold} />
            <Check label="بعدش فرانت را با هوشِ مصنوعی بساز" checked={thenAi} onChange={setThenAi} />
          </div>
          <Help>
            کاتالوگ (دسته، محصول)، سفارش‌ها، سبدِ خریدِ واقعی، تسویه‌حساب و چهار صفحهٔ آماده. اگر تیکِ اول را
            برداری پروژهٔ خالی ساخته می‌شود و خودت همه‌چیز را اضافه می‌کنی.
          </Help>
          <Button type="submit" disabled={busy || !name.trim()}>
            <Icon name="play" size={15} />
            {busy ? "در حالِ ساخت…" : "بساز و کد را تولید کن"}
          </Button>
          {busy && scaffold && <Help>تولیدِ کد و وارسیِ پروژه چند ثانیه طول می‌کشد…</Help>}
        </form>
      </Card>

      <div className="space-y-5">
        <Card>
          <SectionHead title="چه چیزی ساخته می‌شود" />
          <Pre text={TREE} maxHeight="none" />
        </Card>
        <Card>
          <SectionHead title="بعدش چه می‌کنی" />
          <ol className="space-y-2 text-sm leading-7" style={{ color: "var(--text-2)" }}>
            {STEPS.map(([title, text], i) => (
              <li key={title} className="flex gap-3">
                <span
                  className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold"
                  style={{ background: "var(--brand-soft)", color: "var(--brand-strong)" }}
                >
                  {i + 1}
                </span>
                <span>
                  <b style={{ color: "var(--text)" }}>{title}</b> — {text}
                </span>
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </div>
  );
}
