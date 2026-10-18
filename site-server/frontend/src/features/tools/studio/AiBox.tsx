import { FormEvent, ReactNode, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Button, Chip, ErrorBox, Input, TextArea } from "../../../components/ui";
import { api, pUrl, studioError, truncate } from "./api";
import type { ProposalT } from "./types";

/**
 * کادرِ بنفشِ «با هوشِ مصنوعی عوض کن» — روی صفحه، بخشِ مشترک و قالبِ ویو.
 * فقط یک درخواست می‌فرستد و به صفحهٔ پیشنهاد می‌رود؛ هیچ‌چیز بی‌تأیید اعمال نمی‌شود.
 */
export default function AiBox({
  slug,
  endpoint,
  title,
  placeholder,
  note,
  withSection,
  recent,
}: {
  slug: string;
  /** مثلاً `ai/page/12/` — نسبت به /studio/projects/<slug>/ */
  endpoint: string;
  title: string;
  placeholder: string;
  note: ReactNode;
  withSection?: boolean;
  recent?: ProposalT[];
}) {
  const navigate = useNavigate();
  const [instruction, setInstruction] = useState("");
  const [section, setSection] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post<{ proposal: ProposalT }>(`/studio/projects/${slug}/${endpoint}`, {
        instruction,
        section: withSection ? section : "",
      });
      navigate(pUrl(slug, `ai/proposal/${data.proposal.id}`));
    } catch (err) {
      setError(studioError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-2xl p-4"
      style={{
        background: "linear-gradient(135deg, var(--brand-soft), transparent)",
        border: "1px solid color-mix(in srgb, var(--brand) 35%, transparent)",
      }}
    >
      <h3 className="flex items-center gap-2 text-base font-bold" style={{ color: "var(--text)" }}>
        <Icon name="sparkle" size={18} />
        {title}
      </h3>
      <ErrorBox message={error} />
      <TextArea value={instruction} onChange={(e) => setInstruction(e.target.value)} rows={3} placeholder={placeholder} />
      <div className="flex flex-wrap items-center gap-3">
        {withSection && (
          <div className="w-72 max-w-full">
            <Input value={section} onChange={(e) => setSection(e.target.value)} placeholder="بخشِ هدف (اختیاری)، مثلاً hero" dir="ltr" />
          </div>
        )}
        <Button type="submit" disabled={busy || !instruction.trim()}>
          <Icon name="sparkle" size={14} />
          {busy ? "در حالِ فرستادن…" : "بفرست — پیشنهاد بده"}
        </Button>
        <span className="text-sm" style={{ color: "var(--text-3)" }}>
          {note}
        </span>
      </div>
      {recent && recent.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {recent.map((r) => (
            <Link key={r.id} to={pUrl(slug, `ai/proposal/${r.id}`)} className="no-underline">
              <Chip>
                {truncate(r.prompt_text, 40)} <span style={{ color: "var(--text-3)" }}>{r.status_display}</span>
              </Chip>
            </Link>
          ))}
        </div>
      )}
    </form>
  );
}
