import type { Catalog, Doc } from "./doc";

export type ThemeColors = {
  primary: string;
  on_primary: string;
  text: string;
  text2: string;
  muted: string;
  line: string;
  bg: string;
  surface: string;
};
export type ThemeT = { colors: ThemeColors; font_body: string; font_head: string; button: string; radius: number; width: number };
export type MenuRow = { id: string; page?: number; url?: string; label: string; children?: MenuRow[] };
export type AssetT = { id: number; ref: string; kind: string; name: string; alt: string; width: number; height: number; size: number; url: string; thumb: string };
export type ModelT = {
  ref: string;
  pk: number;
  label: string;
  fields: { name: string; type: string; label: string }[];
  default_fields: string[];
  has_detail: boolean;
  is_product: boolean;
};
export type PageRow = { id: number; title: string; slug: string; in_menu: boolean; has_design: boolean; dirty: boolean; url: string };
export type VersionT = { id: number; label: string; kind: string; created_at: string; user: string };
export type SectionT = { id: number; title: string; type: string; created_at: string };
export type StarterT = { key: string; title: string; desc: string; icon: string; slug: string };
export type PreviewT = { running: boolean; url: string; admin_user: string; admin_password: string };
export type ThemeOptions = {
  fonts: { value: string; label: string; family: string }[];
  presets: { key: string; label: string; colors: Partial<ThemeColors> }[];
  buttons: { value: string; label: string }[];
};
export type StatusT = { dirty: boolean; published_at: string | null; rev: number };

export type Bootstrap = {
  project: { slug: string; name: string; site_title: string; has_cart: boolean };
  target: "page" | "header" | "footer";
  page: { id: number; title: string; slug: string; in_menu: boolean; kind: string } | null;
  doc: Doc;
  status: StatusT;
  notice: string;
  catalog: Catalog;
  starters: StarterT[];
  theme: ThemeT;
  menu: MenuRow[];
  theme_options: ThemeOptions;
  pages: PageRow[];
  models: ModelT[];
  media: AssetT[];
  sections: SectionT[];
  versions: VersionT[];
  preview: PreviewT;
};

export type PublishResp = {
  ok: boolean;
  message: string;
  technical: string;
  preview_url: string;
  warnings: { id: string; type: string; text: string }[];
  status: StatusT;
  versions: VersionT[];
  pages: PageRow[];
  preview: PreviewT;
};
