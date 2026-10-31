/**
 * ویرایشگرِ دیداری — تمام‌صفحه و لِیزی‌لود (بقیهٔ پنل سنگین نمی‌شود).
 *
 * بوم همان خروجیِ رندرکنندهٔ سرور است؛ هر تغییر سند را می‌فرستد و تکه‌های عوض‌شده جایگزین می‌شوند.
 * پیش‌نویس خودکار ذخیره می‌شود و فقط «انتشار» سایت را عوض می‌کند.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, downloadZip, pUrl, studioError } from "../api";
import AiBox from "../AiBox";
import { BarAction, CanvasCtl, CanvasPayload } from "./canvas";
import * as D from "./doc";
import type { Block, Device, Doc, DropTarget, Rec } from "./doc";
import { DEVICE_LABEL, FieldInput, FormEnv, StyleForm, Svg } from "./fields";
import { LibraryPanel, MediaPanel, MenuPanel, Modal, OutlinePanel, StarterGrid, ThemePanel, VersionsPanel } from "./panels";
import HostingPanel from "../hosting/HostingPanel";
import type { AssetT, Bootstrap, MenuRow, PublishResp, SectionT, StarterT, ThemeT, VersionT } from "./types";
import "./builder.css";

type SidePane = "add" | "outline" | "theme" | "menu" | "media" | "versions";
type SaveState = "saved" | "saving" | "error" | "conflict";
const FRAME_WIDTH: Record<Device, string> = { d: "100%", t: "768px", p: "390px" };
const I = {
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
  redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h3"/>',
  back: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  desktop: '<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
  tablet: '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M11 18h2"/>',
  phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  tree: '<path d="M4 6h16M8 12h12M12 18h8"/>',
  palette: '<circle cx="12" cy="12" r="9"/><circle cx="8" cy="10" r="1"/><circle cx="12" cy="8" r="1"/><circle cx="16" cy="10" r="1"/><path d="M12 21c-2 0-2-2-1-3s0-3-2-3"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  sparkle: '<path d="M12 3l1.800 5.200L19 10l-5.200 1.800L12 17l-1.800-5.200L5 10l5.200-1.800z"/>',
  sliders: '<path d="M4 8h10M18 8h2M4 16h2M10 16h10"/><circle cx="16" cy="8" r="2"/><circle cx="8" cy="16" r="2"/>',
  more: '<circle cx="5" cy="12" r="1.500"/><circle cx="12" cy="12" r="1.500"/><circle cx="19" cy="12" r="1.500"/>',
};

export default function Builder() {
  const params = useParams<{ slug: string; target: string; pk?: string }>();
  // هر صفحه یک نمونهٔ تازه: تاریخچهٔ برگشت و وضعیتِ ذخیره قاطی نمی‌شوند
  return <BuilderInner key={`${params.slug}-${params.target}-${params.pk ?? ""}`} slug={params.slug ?? ""} target={params.target ?? "page"} pk={params.pk} />;
}

function BuilderInner({ slug, target, pk }: { slug: string; target: string; pk?: string }) {
  const navigate = useNavigate();
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  useEffect(() => {
    api
      .get<Bootstrap>(`/studio/projects/${slug}/builder/bootstrap/`, { params: target === "page" ? { target, page: pk } : { target } })
      .then((r) => setBoot(r.data))
      .catch((err) => setFatal(studioError(err)));
  }, [slug, target, pk]);
  if (fatal) {
    return (
      <div className="nbe nbe-fatal" dir="rtl">
        <p>{fatal}</p>
        <button type="button" className="nbe-add" onClick={() => navigate(pUrl(slug, "frontend"))}>
          بازگشت
        </button>
      </div>
    );
  }
  if (!boot) return <div className="nbe nbe-fatal" dir="rtl"><p>در حالِ بازکردنِ ویرایشگر…</p></div>;
  return <Editor slug={slug} boot={boot} />;
}

function Editor({ slug, boot }: { slug: string; boot: Bootstrap }) {
  const navigate = useNavigate();
  const { catalog, target, page } = boot;
  const pageRef = page?.id;
  const [doc, setDocState] = useState<Doc>(boot.doc);
  const pastRef = useRef<Doc[]>([]);
  const futureRef = useRef<Doc[]>([]);
  // سربرگ یک بلوکِ اصلی دارد: تنظیماتش از همان اول باز باشد
  const [selected, setSelected] = useState<string | null>(target === "header" ? boot.doc.blocks[0]?.id ?? null : null);
  const [device, setDevice] = useState<Device>("d");
  const [pane, setPane] = useState<SidePane>("add");
  const [sheet, setSheet] = useState<"none" | "side" | "settings">("none");
  const [settingsTab, setSettingsTab] = useState<"content" | "style">("content");
  const [preview, setPreview] = useState(false);
  const [theme, setTheme] = useState<ThemeT>(boot.theme);
  const [menu, setMenu] = useState<MenuRow[]>(boot.menu);
  const [media, setMedia] = useState<AssetT[]>(boot.media);
  const [pages, setPages] = useState(boot.pages);
  const [sections, setSections] = useState<SectionT[]>(boot.sections);
  const [versions, setVersions] = useState<VersionT[]>(boot.versions);
  const [previewInfo, setPreviewInfo] = useState(boot.preview);
  const [save, setSave] = useState<SaveState>("saved");
  const [dirty, setDirty] = useState(boot.status.dirty);
  const [notice, setNotice] = useState(boot.notice);
  const [warnings, setWarnings] = useState<CanvasPayload["warnings"]>([]);
  const [samples, setSamples] = useState<string[]>([]);
  const [publishing, setPublishing] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [liveOpen, setLiveOpen] = useState(false);
  const [liveJob, setLiveJob] = useState<HostingJob | null>(null);
  const [liveWarnings, setLiveWarnings] = useState<PublishResp["warnings"]>([]);
  const [result, setResult] = useState<PublishResp | null>(null);
  const [pubError, setPubError] = useState<string | null>(null);
  const [mediaPick, setMediaPick] = useState<{ accept: string; then: (ref: string) => void } | null>(null);
  const [starterOpen, setStarterOpen] = useState(target === "page" && !boot.doc.blocks.length);
  const [newPageOpen, setNewPageOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [canvasError, setCanvasError] = useState<string | null>(null);

  const frameRef = useRef<HTMLIFrameElement>(null);
  const ctlRef = useRef<CanvasCtl | null>(null);
  const docRef = useRef(doc);
  docRef.current = doc;
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const revRef = useRef(boot.status.rev);
  const seqRef = useRef(0);
  const saveTimer = useRef<number | undefined>();
  const themeTimer = useRef<number | undefined>();
  const firstDoc = useRef(true);
  const firstTheme = useRef(true);
  const blockedSave = useRef(false);

  const labelOf = useCallback((type: string) => D.specOf(catalog, type)?.label ?? "", [catalog]);

  /* ─────────── تاریخچه ─────────── */
  const commit = useCallback((next: Doc) => {
    pastRef.current = [...pastRef.current.slice(-99), docRef.current];
    futureRef.current = [];
    docRef.current = next;
    setDocState(next);
  }, []);
  const undo = useCallback(() => {
    const prev = pastRef.current[pastRef.current.length - 1];
    if (!prev) return;
    pastRef.current = pastRef.current.slice(0, -1);
    futureRef.current = [docRef.current, ...futureRef.current];
    docRef.current = prev;
    setDocState(prev);
  }, []);
  const redo = useCallback(() => {
    const next = futureRef.current[0];
    if (!next) return;
    futureRef.current = futureRef.current.slice(1);
    pastRef.current = [...pastRef.current, docRef.current];
    docRef.current = next;
    setDocState(next);
  }, []);

  /* ─────────── ذخیرهٔ خودکار ─────────── */
  const flushDoc = useCallback(async () => {
    window.clearTimeout(saveTimer.current);
    if (blockedSave.current) return;
    setSave("saving");
    try {
      const { data } = await api.put<{ status: { rev: number; dirty: boolean } }>(`/studio/projects/${slug}/builder/design/`, {
        target,
        page: pageRef,
        doc: docRef.current,
        rev: revRef.current,
      });
      revRef.current = data.status.rev;
      setDirty(data.status.dirty);
      setSave("saved");
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 409) {
        blockedSave.current = true;
        setSave("conflict");
        setNotice(studioError(err));
      } else {
        setSave("error");
      }
    }
  }, [slug, target, pageRef]);

  useEffect(() => {
    if (firstDoc.current) {
      firstDoc.current = false;
      return;
    }
    setDirty(true);
    setSave("saving");
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => void flushDoc(), 1200);
    return () => window.clearTimeout(saveTimer.current);
  }, [doc, flushDoc]);

  useEffect(() => {
    if (firstTheme.current) {
      firstTheme.current = false;
      return;
    }
    window.clearTimeout(themeTimer.current);
    themeTimer.current = window.setTimeout(() => {
      void api.put(`/studio/projects/${slug}/builder/theme/`, { theme, menu });
    }, 800);
    return () => window.clearTimeout(themeTimer.current);
  }, [theme, menu, slug]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (save === "saving") {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [save]);

  /* ─────────── بوم ─────────── */
  const applyAction = useCallback(
    (action: BarAction, id: string) => {
      const d = docRef.current;
      if (action === "delete") {
        commit(D.removeBlock(d, id));
        setSelected(null);
      } else if (action === "duplicate") {
        const r = D.duplicateBlock(d, id);
        commit(r.doc);
        if (r.id) setSelected(r.id);
      } else if (action === "up" || action === "down") {
        commit(D.moveSibling(d, id, action === "up" ? -1 : 1));
      } else if (action === "parent") {
        const f = D.find(d, id);
        if (f?.parent) setSelected(f.parent.id);
      } else if (action === "save") {
        const f = D.find(d, id);
        if (!f) return;
        const title = window.prompt("نامِ این بخش برای استفادهٔ دوباره:", labelOf(f.block.type));
        if (!title) return;
        api
          .post<{ section: SectionT }>(`/studio/projects/${slug}/builder/sections/`, { title, block: f.block })
          .then((r) => setSections((s) => [r.data.section, ...s]))
          .catch((err) => setNotice(studioError(err)));
      }
    },
    [commit, labelOf, slug],
  );

  /* کشیدن: هم روی پنجره و هم داخلِ iframe گوش می‌دهیم تا نشانگر هر جا باشد دنبال شود */
  const startDrag = useCallback(
    (src: { create?: () => Block; move?: string }, rootOnly: boolean, label: string, x: number, y: number) => {
      const ctl = ctlRef.current;
      const frame = frameRef.current;
      if (!ctl || !frame?.contentDocument) return;
      ctl.commitEdit();
      ctl.setDragging(true);
      const ghost = document.createElement("div");
      ghost.className = "nbe-ghost";
      ghost.textContent = label;
      document.body.appendChild(ghost);
      let target: DropTarget | null = null;
      let lastX = x;
      let lastY = y;
      const place = (cx: number, cy: number) => {
        lastX = cx;
        lastY = cy;
        ghost.style.left = `${cx + 10}px`;
        ghost.style.top = `${cy + 10}px`;
        const r = frame.getBoundingClientRect();
        if (cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom) {
          target = ctl.hit(cx - r.left, cy - r.top, rootOnly, src.move ?? null);
        } else {
          target = null;
          ctl.hideLine();
        }
      };
      const fdoc = frame.contentDocument;
      // نزدیکِ لبهٔ بوم، بی‌حرکتِ موش هم صفحه می‌لغزد
      const scroller = window.setInterval(() => {
        const r = frame.getBoundingClientRect();
        if (lastX >= r.left && lastX <= r.right && lastY >= r.top && lastY <= r.bottom && ctl.autoScroll(lastY - r.top)) place(lastX, lastY);
      }, 30);
      const onWin = (e: PointerEvent) => place(e.clientX, e.clientY);
      const onDoc = (e: PointerEvent) => {
        const r = frame.getBoundingClientRect();
        place(e.clientX + r.left, e.clientY + r.top);
      };
      const finish = () => {
        window.clearInterval(scroller);
        window.removeEventListener("pointermove", onWin);
        window.removeEventListener("pointerup", finish);
        window.removeEventListener("pointercancel", finish);
        fdoc.removeEventListener("pointermove", onDoc);
        fdoc.removeEventListener("pointerup", finish);
        ghost.remove();
        ctl.setDragging(false);
        if (!target) return;
        if (src.move) {
          commit(D.moveBlock(docRef.current, catalog, src.move, target));
          setSelected(src.move);
        } else if (src.create) {
          const b = src.create();
          const r = D.insertBlock(docRef.current, catalog, b, target);
          commit(r.doc);
          setSelected(r.id);
        }
      };
      window.addEventListener("pointermove", onWin);
      window.addEventListener("pointerup", finish);
      window.addEventListener("pointercancel", finish);
      fdoc.addEventListener("pointermove", onDoc);
      fdoc.addEventListener("pointerup", finish);
      place(x, y);
    },
    [catalog, commit],
  );

  const keyHandler = useCallback(
    (e: KeyboardEvent) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target as HTMLElement)?.tagName ?? "");
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !typing) {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y" && !typing) {
        e.preventDefault();
        redo();
      } else if ((e.key === "Delete" || e.key === "Backspace") && selectedRef.current && !typing) {
        e.preventDefault();
        applyAction("delete", selectedRef.current);
      } else if (e.key === "Escape" && !typing) {
        setSelected(null);
      }
    },
    [applyAction, redo, undo],
  );

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const ctl = new CanvasCtl(frame, {
      onSelect: setSelected,
      onText: (id, path, value) => commit(D.setProp(docRef.current, id, path, value)),
      onAction: applyAction,
      onStartMove: (id, x, y) => {
        const f = D.find(docRef.current, id);
        const spec = f ? D.specOf(catalog, f.block.type) : undefined;
        startDrag({ move: id }, !!spec?.root, spec?.label ?? "", x, y);
      },
      onChrome: (which) => {
        if (target === which) return;
        if (window.confirm(which === "header" ? "سربرگ روی همهٔ صفحه‌ها یکی است. به ویرایشِ سربرگ برویم؟" : "پابرگ روی همهٔ صفحه‌ها یکی است. به ویرایشِ پابرگ برویم؟")) {
          void flushDoc().then(() => navigate(pUrl(slug, `builder/${which}`)));
        }
      },
      onKey: keyHandler,
      labelOf,
    });
    ctlRef.current = ctl;
    void ctl.ready.then(() => setFrameReady(true));
    return () => ctl.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [frameReady, setFrameReady] = useState(false);

  useEffect(() => {
    window.addEventListener("keydown", keyHandler);
    return () => window.removeEventListener("keydown", keyHandler);
  }, [keyHandler]);

  useEffect(() => {
    if (!frameReady) return;
    const seq = (seqRef.current += 1);
    const t = window.setTimeout(async () => {
      try {
        const { data } = await api.post<CanvasPayload>(`/studio/projects/${slug}/builder/render/`, {
          target,
          page: pageRef,
          doc: docRef.current,
          theme,
          menu,
        });
        if (seq !== seqRef.current) return;
        ctlRef.current?.update(data);
        setWarnings(data.warnings);
        setSamples(data.sample_models);
        setCanvasError(null);
      } catch (err) {
        if (seq === seqRef.current) setCanvasError(studioError(err));
      }
    }, 160);
    return () => window.clearTimeout(t);
  }, [doc, theme, menu, frameReady, slug, target, pageRef, media]);

  useEffect(() => {
    ctlRef.current?.select(selected);
    setSettingsTab("content");
  }, [selected]);

  useEffect(() => {
    ctlRef.current?.setPreview(preview);
  }, [preview]);

  useEffect(() => {
    ctlRef.current?.reposition();
  }, [device]);

  /* ─────────── افزودن ─────────── */
  const addBlock = useCallback(
    (type: string) => {
      const b = D.makeBlock(catalog, type);
      const t = D.clickTarget(docRef.current, catalog, type, selectedRef.current);
      const r = D.insertBlock(docRef.current, catalog, b, t);
      commit(r.doc);
      setSelected(r.id);
      setSheet("none");
      window.setTimeout(() => ctlRef.current?.select(r.id, true), 450);
    },
    [catalog, commit],
  );
  const loadSaved = useCallback(
    async (s: SectionT) => {
      const { data } = await api.get<{ block: Block }>(`/studio/projects/${slug}/builder/sections/${s.id}/`);
      return data.block;
    },
    [slug],
  );

  /* ─────────── تنظیمات ─────────── */
  const selBlock = selected ? D.find(doc, selected)?.block ?? null : null;
  const selSpec = selBlock ? D.specOf(catalog, selBlock.type) : undefined;
  const env: FormEnv = useMemo(
    () => ({
      catalog,
      pages,
      models: boot.models,
      media,
      theme,
      hasCart: boot.project.has_cart,
      pickMedia: (accept, then) => setMediaPick({ accept, then }),
    }),
    [catalog, pages, boot.models, boot.project.has_cart, media, theme],
  );
  const setProp = (key: string, value: unknown, extra?: Rec) => {
    if (!selBlock) return;
    if (selBlock.type === "columns" && key === "count") {
      commit(D.setColumnCount(doc, catalog, selBlock.id, Number(value)));
      return;
    }
    let next = D.setProp(doc, selBlock.id, key, value);
    if (extra) Object.entries(extra).forEach(([k, v]) => (next = D.setProp(next, selBlock.id, k, v)));
    commit(next);
  };

  /* ─────────── انتشار ─────────── */
  /* انتشارِ واقعی: صفحه‌ها نوشته می‌شوند و بقیه‌اش (ساخت، مهاجرت، جابه‌جایی) کارِ پس‌زمینهٔ سرور است */
  async function publishLive() {
    ctlRef.current?.commitEdit();
    window.clearTimeout(saveTimer.current);
    setPublishing(true);
    setPubError(null);
    try {
      await api.put(`/studio/projects/${slug}/builder/theme/`, { theme, menu });
      const { data } = await api.post<PublishResp>(`/studio/projects/${slug}/builder/publish/`, { target, page: pageRef, doc: docRef.current, live: true });
      if (data.status) {
        revRef.current = data.status.rev;
        setDirty(data.status.dirty);
        setSave("saved");
      }
      if (data.versions) setVersions(data.versions);
      if (data.pages) setPages(data.pages);
      const { data: st } = await api.post<{ job: HostingJob }>(`/studio/projects/${slug}/hosting/publish/`, {});
      setLiveJob(st.job);
      setLiveWarnings(data.warnings ?? []);
      setLiveOpen(true);
    } catch (err) {
      setPubError(studioError(err));
    } finally {
      setPublishing(false);
    }
  }

  async function publish() {
    ctlRef.current?.commitEdit();
    window.clearTimeout(saveTimer.current);
    setPreviewing(true);
    setPubError(null);
    try {
      await api.put(`/studio/projects/${slug}/builder/theme/`, { theme, menu });
      const { data } = await api.post<PublishResp>(`/studio/projects/${slug}/builder/publish/`, { target, page: pageRef, doc: docRef.current });
      applyPublish(data);
    } catch (err) {
      const resp = (err as { response?: { data?: PublishResp; status?: number } }).response;
      if (resp?.status === 500 && resp.data?.message) applyPublish(resp.data);
      else setPubError(studioError(err));
    } finally {
      setPreviewing(false);
    }
  }
  function applyPublish(data: PublishResp) {
    setResult(data);
    if (data.status) {
      revRef.current = data.status.rev;
      setDirty(data.status.dirty);
      setSave("saved");
    }
    if (data.versions) setVersions(data.versions);
    if (data.pages) setPages(data.pages);
    if (data.preview) setPreviewInfo(data.preview);
  }

  async function restore(v: VersionT) {
    const { data } = await api.post<{ doc: Doc; status: { rev: number; dirty: boolean }; versions: VersionT[]; message: string }>(`/studio/projects/${slug}/builder/versions/${v.id}/`, {});
    revRef.current = data.status.rev;
    firstDoc.current = false;
    commit(data.doc);
    setVersions(data.versions);
    setNotice(data.message);
    setSelected(null);
  }

  async function pickStarter(s: StarterT) {
    if (!pageRef) return;
    const { data } = await api.post<{ doc: Doc; status: { rev: number } }>(`/studio/projects/${slug}/builder/pages/${pageRef}/starter/`, { starter: s.key });
    revRef.current = data.status.rev;
    commit(data.doc);
    setStarterOpen(false);
  }

  async function createPage(s: StarterT, title: string) {
    await flushDoc();
    const { data } = await api.post<{ page: { id: number } }>(`/studio/projects/${slug}/builder/pages/`, { starter: s.key, title });
    navigate(pUrl(slug, `builder/page/${data.page.id}`));
  }

  async function seed(modelPk: number) {
    setSeeding(true);
    try {
      const { data } = await api.post<{ message: string }>(`/studio/projects/${slug}/builder/models/${modelPk}/seed/`, {});
      setNotice(data.message);
      setDocState((d) => ({ ...d }));
    } catch (err) {
      setNotice(studioError(err));
    } finally {
      setSeeding(false);
    }
  }

  function goto(value: string) {
    void flushDoc().then(() => {
      if (value === "__new") setNewPageOpen(true);
      else navigate(pUrl(slug, `builder/${value}`));
    });
  }

  const current = target === "page" ? `page/${pageRef}` : target;
  const saveText = { saved: dirty ? "پیش‌نویس ذخیره شد" : "منتشر شده", saving: "در حالِ ذخیره…", error: "ذخیره نشد؛ دوباره تلاش می‌شود", conflict: "جای دیگری هم باز است" }[save];

  const panelSide = (
    <>
      <nav className="nbe-tabs" aria-label="ابزارها">
        {(
          [
            ["add", "افزودن", I.plus],
            ["outline", "ساختار", I.tree],
            ["theme", "پوسته", I.palette],
            ["menu", "منو", I.menu],
            ["media", "رسانه", I.image],
            ["versions", "نسخه‌ها", I.clock],
          ] as [SidePane, string, string][]
        ).map(([k, label, icon]) => (
          <button key={k} type="button" className={pane === k ? "on" : ""} data-pane={k} onClick={() => setPane(k)}>
            <Svg body={icon} size={17} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      {pane === "add" && (
        <LibraryPanel
          catalog={catalog}
          target={target}
          sections={sections}
          onAdd={addBlock}
          onDragStart={(type, x, y) => {
            const spec = D.specOf(catalog, type);
            startDrag({ create: () => D.makeBlock(catalog, type) }, !!spec?.root, spec?.label ?? "", x, y);
          }}
          onAddSaved={async (s) => {
            const b = await loadSaved(s);
            const t = D.clickTarget(docRef.current, catalog, b.type, selectedRef.current);
            const r = D.insertBlock(docRef.current, catalog, b, t);
            commit(r.doc);
            setSelected(r.id);
          }}
          onDragSaved={async (s, x, y) => {
            const b = await loadSaved(s);
            startDrag({ create: () => D.refreshIds(JSON.parse(JSON.stringify(b)) as Block) }, !!D.specOf(catalog, b.type)?.root, s.title, x, y);
          }}
          onDeleteSaved={async (s) => {
            if (!window.confirm(`«${s.title}» حذف شود؟`)) return;
            await api.delete(`/studio/projects/${slug}/builder/sections/${s.id}/`);
            setSections((x) => x.filter((y) => y.id !== s.id));
          }}
        />
      )}
      {pane === "outline" && <OutlinePanel doc={doc} catalog={catalog} selected={selected} onSelect={(id) => { setSelected(id); ctlRef.current?.select(id, true); }} />}
      {pane === "theme" && <ThemePanel theme={theme} options={boot.theme_options} onChange={setTheme} />}
      {pane === "menu" && <MenuPanel menu={menu} pages={pages} onChange={setMenu} />}
      {pane === "media" && <MediaPanel slug={slug} media={media} setMedia={setMedia} />}
      {pane === "versions" && <VersionsPanel versions={versions} onRestore={(v) => { if (window.confirm("این نسخه به پیش‌نویس برگردد؟")) void restore(v); }} />}
    </>
  );

  const selModel = selBlock?.props?.model ? boot.models.find((m) => m.ref === selBlock.props.model) : undefined;

  const panelSettings = selBlock && selSpec ? (
    <div className="nbe-settings" data-testid="settings">
      <div className="nbe-settings-h">
        <Svg body={catalog.icons[selSpec.icon] ?? ""} size={17} />
        <b>{selSpec.label}</b>
        <button type="button" className="nbe-x" aria-label="بستن" onClick={() => { setSelected(null); setSheet("none"); }}>×</button>
      </div>
      <div className="nbe-seg nbe-settings-tabs">
        <button type="button" className={settingsTab === "content" ? "on" : ""} onClick={() => setSettingsTab("content")}>محتوا</button>
        <button type="button" className={settingsTab === "style" ? "on" : ""} data-tab="style" onClick={() => setSettingsTab("style")}>ظاهر</button>
      </div>
      <div className="nbe-pane">
        {settingsTab === "content" ? (
          <>
            {selSpec.hint && <p className="nbe-note">{selSpec.hint}</p>}
            {selSpec.fields.map((f) => (
              <FieldInput key={f.key} f={f} value={selBlock.props[f.key]} env={env} block={selBlock} device={device} onChange={(v, extra) => setProp(f.key, v, extra)} />
            ))}
            {selSpec.fields.length === 0 && <p className="nbe-note">این بلوک محتوای جدا ندارد؛ از زبانهٔ «ظاهر» تنظیمش کن.</p>}
            {selModel && samples.includes(selModel.ref) && (
              <div className="nbe-sample">
                <p>چیزی که می‌بینی نمونه است چون هنوز موردی ثبت نشده.</p>
                <button type="button" className="nbe-add" disabled={seeding} data-testid="seed" onClick={() => void seed(selModel.pk)}>
                  {seeding ? "در حالِ ساخت…" : "چند موردِ نمونه بساز"}
                </button>
              </div>
            )}
            {selModel && previewInfo.running && (
              <a className="nbe-link" href={`${previewInfo.url}admin/`} target="_blank" rel="noreferrer">افزودن یا ویرایشِ موردها در مدیریتِ سایت</a>
            )}
          </>
        ) : (
          <StyleForm spec={selSpec} block={selBlock} device={device} env={env} onChange={(dev, key, value) => commit(D.setStyle(doc, selBlock.id, dev, key, value))} />
        )}
      </div>
    </div>
  ) : (
    <div className="nbe-pane nbe-empty-side">
      <p className="nbe-note">روی هر چیزی در صفحه بزن تا تنظیماتش این‌جا بیاید. برای نوشتن، مستقیم روی متن بزن.</p>
      {page && <PageSettings slug={slug} page={page} onPages={setPages} />}
      {warnings.length > 0 && (
        <div className="nbe-checks-list">
          <h4 className="nbe-h">پیشنهادهایی برای بهتر شدن</h4>
          {warnings.slice(0, 12).map((w, i) => (
            <button type="button" key={i} onClick={() => { setSelected(w.id); ctlRef.current?.select(w.id, true); }}>
              {w.text}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className={`nbe ${preview ? "is-preview" : ""}`} dir="rtl" data-testid="builder">
      <header className="nbe-top">
        <Link className="nbe-iconbtn2" to={pUrl(slug, "frontend")} aria-label="بازگشت" title="بازگشت">
          <Svg body={I.back} />
        </Link>
        <select className="nbe-input nbe-pagesel" value={current} data-testid="page-switch" aria-label="صفحهٔ در حالِ ویرایش" onChange={(e) => goto(e.target.value)}>
          <optgroup label="صفحه‌ها">
            {pages.map((p) => (
              <option key={p.id} value={`page/${p.id}`}>
                {p.title}
                {p.dirty ? " •" : ""}
              </option>
            ))}
          </optgroup>
          <optgroup label="بخش‌های مشترک">
            <option value="header">سربرگِ سایت</option>
            <option value="footer">پابرگِ سایت</option>
          </optgroup>
          <option value="__new">+ صفحهٔ تازه…</option>
        </select>
        <span className={`nbe-save ${save}`} data-testid="save-state">{saveText}</span>
        <div className="nbe-top-mid">
          {(["d", "t", "p"] as Device[]).map((dv) => (
            <button key={dv} type="button" className={`nbe-iconbtn2 nbe-dev ${device === dv ? "on" : ""}`} data-device={dv} title={DEVICE_LABEL[dv]} aria-label={DEVICE_LABEL[dv]} onClick={() => setDevice(dv)}>
              <Svg body={dv === "d" ? I.desktop : dv === "t" ? I.tablet : I.phone} />
            </button>
          ))}
        </div>
        <div className="nbe-top-end">
          <button type="button" className="nbe-iconbtn2" disabled={!pastRef.current.length} title="برگشت" aria-label="برگشت" data-testid="undo" onClick={undo}><Svg body={I.undo} /></button>
          <button type="button" className="nbe-iconbtn2" disabled={!futureRef.current.length} title="جلو" aria-label="جلو" data-testid="redo" onClick={redo}><Svg body={I.redo} /></button>
          <button type="button" className={`nbe-iconbtn2 ${preview ? "on" : ""}`} title="دیدنِ پیش‌نویس بدونِ ابزارها" aria-label="دیدن" onClick={() => setPreview(!preview)}><Svg body={I.eye} /></button>
          <div className="nbe-morewrap">
            <button type="button" className="nbe-iconbtn2" aria-label="بیشتر" title="بیشتر" aria-expanded={moreOpen} data-testid="more" onClick={() => setMoreOpen(!moreOpen)}><Svg body={I.more} /></button>
            {moreOpen && (
              <div className="nbe-more" onClick={() => setMoreOpen(false)}>
                <button type="button" onClick={() => setAiOpen(true)}><Svg body={I.sparkle} size={15} /> ویرایش با هوشِ مصنوعی</button>
                <button type="button" data-testid="open-hosting" onClick={() => { setLiveJob(null); setLiveWarnings([]); setLiveOpen(true); }}>وضعیتِ سایت، دامنه و پیام‌ها</button>
                {target === "page" && <button type="button" onClick={() => setStarterOpen(true)}><Svg body={I.plus} size={15} /> قالبِ آماده روی این صفحه</button>}
                {previewInfo.running && <a href={previewInfo.url} target="_blank" rel="noreferrer">دیدنِ پیش‌نمایش</a>}
                <button type="button" onClick={() => void downloadZip(slug, false).catch((err) => setNotice(String(err.message ?? err)))}>دانلودِ سایت</button>
                <Link to={target === "page" ? pUrl(slug, `page/${pageRef}`) : pUrl(slug, `shared/${target}`)} data-testid="code-mode">حالتِ پیشرفته: ویرایشِ کد</Link>
              </div>
            )}
          </div>
          <button type="button" className="nbe-add nbe-preview-btn" disabled={publishing || previewing} data-testid="preview-btn" onClick={() => void publish()}>
            {previewing ? "در حالِ ساخت…" : "پیش‌نمایش"}
          </button>
          <button type="button" className="nbe-publish" disabled={publishing || previewing} data-testid="publish" onClick={() => void publishLive()}>
            {publishing ? "در حالِ انتشار…" : "انتشار"}
          </button>
        </div>
      </header>

      {notice && (
        <div className="nbe-notice" role="status">
          <span>{notice}</span>
          <button type="button" aria-label="بستن" onClick={() => setNotice("")}>×</button>
        </div>
      )}
      {canvasError && <div className="nbe-notice bad" role="alert"><span>{canvasError}</span></div>}
      {pubError && (
        <div className="nbe-notice bad" role="alert" data-testid="publish-error">
          <span>{pubError}</span>
          <button type="button" aria-label="بستن" onClick={() => setPubError(null)}>×</button>
        </div>
      )}

      <div className="nbe-body">
        <aside className={`nbe-side ${sheet === "side" ? "open" : ""}`} aria-label="ابزارها">
          <button type="button" className="nbe-sheet-close" aria-label="بستن" onClick={() => setSheet("none")}>×</button>
          {panelSide}
        </aside>
        <main className="nbe-stage">
          <div className={`nbe-framebox ${device === "d" ? "is-d" : ""}`} style={{ width: FRAME_WIDTH[device] }}>
            <iframe ref={frameRef} title="بومِ صفحه" className="nbe-frame" data-testid="canvas" />
          </div>
        </main>
        <aside className={`nbe-side nbe-side-l ${sheet === "settings" ? "open" : ""}`} aria-label="تنظیمات">
          <button type="button" className="nbe-sheet-close" aria-label="بستن" onClick={() => setSheet("none")}>×</button>
          {panelSettings}
        </aside>
      </div>

      <nav className="nbe-bottom" aria-label="ابزارهای گوشی">
        <button type="button" data-mobile="add" onClick={() => { setPane("add"); setSheet(sheet === "side" ? "none" : "side"); }}><Svg body={I.plus} /><span>افزودن</span></button>
        <button type="button" data-mobile="settings" className={selBlock ? "hot" : ""} onClick={() => setSheet(sheet === "settings" ? "none" : "settings")}><Svg body={I.sliders} /><span>تنظیمات</span></button>
        <button type="button" data-mobile="theme" onClick={() => { setPane("theme"); setSheet(sheet === "side" ? "none" : "side"); }}><Svg body={I.palette} /><span>پوسته</span></button>
        <button type="button" data-mobile="media" onClick={() => { setPane("media"); setSheet(sheet === "side" ? "none" : "side"); }}><Svg body={I.image} /><span>رسانه</span></button>
      </nav>

      {mediaPick && (
        <Modal title={mediaPick.accept === "video" ? "انتخابِ ویدیو" : "انتخابِ تصویر"} onClose={() => setMediaPick(null)} wide>
          <MediaPanel slug={slug} media={media} setMedia={setMedia} accept={mediaPick.accept} onPick={(a) => { mediaPick.then(a.ref); setMediaPick(null); }} />
        </Modal>
      )}
      {starterOpen && (
        <Modal title="با کدام قالب شروع کنیم؟" onClose={() => setStarterOpen(false)} wide>
          <StarterGrid starters={boot.starters} icons={catalog.icons} hasCart={boot.project.has_cart} onPick={(s) => void pickStarter(s)} />
          <p className="nbe-note">هر چیزی را بعداً می‌توانی عوض کنی. پیش‌نویسِ فعلی در «نسخه‌ها» می‌ماند.</p>
        </Modal>
      )}
      {newPageOpen && (
        <Modal title="صفحهٔ تازه" onClose={() => setNewPageOpen(false)} wide>
          <StarterGrid starters={boot.starters} icons={catalog.icons} hasCart={boot.project.has_cart} onPick={(s) => void createPage(s, window.prompt("نامِ صفحه:", s.title) || s.title)} />
        </Modal>
      )}
      {aiOpen && (
        <Modal title="ویرایش با هوشِ مصنوعی" onClose={() => setAiOpen(false)} wide>
          {dirty && <p className="nbe-warn">هوشِ مصنوعی روی نسخهٔ منتشرشده کار می‌کند؛ پیش‌نویسِ منتشرنشده‌ات را نمی‌بیند. بهتر است اول «انتشار» را بزنی. (پیش‌نویس گم نمی‌شود و در «نسخه‌ها» می‌ماند.)</p>}
          <AiBox slug={slug} endpoint={target === "page" ? `ai/page/${pageRef}/` : `ai/shared/${target}/`} title="چه چیزی عوض شود؟" placeholder="مثلاً: متنِ سربرگِ بزرگ را دوستانه‌تر کن" note="پیش از اعمال، تغییرها را می‌بینی و تأیید می‌کنی. بعدش صفحه باز هم با کلیک ویرایش می‌شود." />
        </Modal>
      )}
      {liveOpen && <LiveDialog slug={slug} job={liveJob} warnings={liveWarnings} onClose={() => setLiveOpen(false)} onSelect={(id) => { setLiveOpen(false); setSelected(id); ctlRef.current?.select(id); }} />}
      {result && <PublishDialog slug={slug} result={result} preview={previewInfo} onClose={() => setResult(null)} onSelect={(id) => { setResult(null); setSelected(id); ctlRef.current?.select(id, true); }} />}
    </div>
  );
}

function PageSettings({ slug, page, onPages }: { slug: string; page: NonNullable<Bootstrap["page"]>; onPages: (p: Bootstrap["pages"]) => void }) {
  const [title, setTitle] = useState(page.title);
  return (
    <div className="nbe-field">
      <h4 className="nbe-h">این صفحه</h4>
      <div className="nbe-label">نامِ صفحه</div>
      <input
        className="nbe-input"
        value={title}
        data-testid="page-title"
        onChange={(e) => setTitle(e.target.value)}
        onBlur={() => {
          if (title.trim() && title !== page.title) {
            void api.post<{ pages: Bootstrap["pages"] }>(`/studio/projects/${slug}/builder/pages/${page.id}/meta/`, { title }).then((r) => onPages(r.data.pages));
          }
        }}
      />
      <p className="nbe-note">نشانی: <span dir="ltr">/{page.slug}</span></p>
    </div>
  );
}

type HostingJob = NonNullable<React.ComponentProps<typeof HostingPanel>["autoJob"]>;

function LiveDialog({ slug, job, warnings, onClose, onSelect }: { slug: string; job: HostingJob | null; warnings: PublishResp["warnings"]; onClose: () => void; onSelect: (id: string) => void }) {
  return (
    <Modal title="انتشار روی اینترنت" onClose={onClose} wide>
      <HostingPanel slug={slug} autoJob={job} />
      {warnings?.length > 0 && (
        <div className="nbe-checks-list">
          <h4 className="nbe-h">پیشنهادهایی برای بهتر شدن</h4>
          {warnings.slice(0, 8).map((w, i) => (
            <button type="button" key={i} onClick={() => onSelect(w.id)}>{w.text}</button>
          ))}
        </div>
      )}
    </Modal>
  );
}

function PublishDialog({ slug, result, preview, onClose, onSelect }: { slug: string; result: PublishResp; preview: Bootstrap["preview"]; onClose: () => void; onSelect: (id: string) => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={result.ok ? "پیش‌نمایش آماده است" : "ساختِ پیش‌نمایش کامل نشد"} onClose={onClose}>
      <div data-testid="publish-result">
        <p>{result.message}</p>
        {result.ok && (result.preview_url || preview.url) && (
          <div className="nbe-row">
            <a className="nbe-publish nbe-a" href={result.preview_url || preview.url} target="_blank" rel="noreferrer" data-testid="view-site">دیدنِ پیش‌نمایش</a>
            <button
              type="button"
              className="nbe-add"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void downloadZip(slug, false).finally(() => setBusy(false));
              }}
            >
              {busy ? "…" : "دانلودِ سایت"}
            </button>
          </div>
        )}
        {!result.ok && result.technical && (
          <details className="nbe-tech">
            <summary>جزئیات برای برنامه‌نویس</summary>
            <pre dir="ltr">{result.technical}</pre>
          </details>
        )}
        {result.warnings?.length > 0 && (
          <div className="nbe-checks-list">
            <h4 className="nbe-h">پیشنهادهایی برای بهتر شدن</h4>
            {result.warnings.slice(0, 8).map((w, i) => (
              <button type="button" key={i} onClick={() => onSelect(w.id)}>{w.text}</button>
            ))}
          </div>
        )}
        {preview.admin_user && (
          <details className="nbe-tech">
            <summary>پیام‌های فرم و داده‌ها در مدیریتِ سایت</summary>
            <p>نشانی: <a href={`${preview.url}admin/`} target="_blank" rel="noreferrer" dir="ltr">{preview.url}admin/</a></p>
            <p>نامِ کاربری: <code dir="ltr">{preview.admin_user}</code> — رمز: <code dir="ltr">{preview.admin_password}</code></p>
          </details>
        )}
      </div>
    </Modal>
  );
}
