import { faDateTime, sourceText } from "../../format";
import type { Provenance, SourceInfo } from "../../types";

/** `manual` / `csv:<file>:<row>` / `extract:<run>` -> a SourceInfo (the same split the server does). */
export function parseRef(ref: string | undefined | null): SourceInfo {
  if (!ref || ref === "manual") return { kind: "manual" };
  if (ref.startsWith("csv:")) {
    const rest = ref.slice(4);
    const cut = rest.lastIndexOf(":");
    const file = cut >= 0 ? rest.slice(0, cut) : rest;
    const row = cut >= 0 ? Number(rest.slice(cut + 1)) : NaN;
    return { kind: "csv", file, row: Number.isFinite(row) ? row : null };
  }
  if (ref.startsWith("extract:")) {
    const run = Number(ref.slice(8));
    return { kind: "extract", run: Number.isFinite(run) ? run : null };
  }
  return { kind: "other", ref };
}

/** The text of a provenance chip for one field, or "" when we have no record. */
export function provenanceLabel(prov: Provenance | undefined, field: string): { text: string; title: string } {
  const entry = prov?.[field];
  if (!entry) return { text: "", title: "" };
  return { text: sourceText(parseRef(entry.source)), title: `ثبت‌شده در ${faDateTime(entry.at)}` };
}

export function contactSourceText(ref: string): string {
  return sourceText(parseRef(ref));
}
