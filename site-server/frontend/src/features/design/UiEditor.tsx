import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import Icon from "../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, Input, PageHeader, Select, Spinner, TextArea } from "../../components/ui";
import { useAuth } from "../auth/AuthContext";
import { BlockCatalog, BlockDef, Comment, FieldSpec, Overview, Scene, ScenePage, SiteInfo, apiError, designApi, fa } from "./api";
import C21Panel from "./C21Panel";
import ExportDialog from "./ExportDialog";
import { useDocEditor, useOverview, usePreview } from "./hooks";
import { ColorField, Field, ImagePicker, PageCanvas, Thumb, useWidth, ChecksPanel } from "./parts";
import "./design.css";

type Node = Record<string, any>;
const DEV_FA: Record<string, string> = { desktop: "دسکتاپ", tablet: "تبلت", phone: "گوشی" };

function walk(nodes: Node[], depth = 0, out: { n: Node; depth: number }[] = []) {
  for (const n of nodes) {
    out.push({ n, depth });
    if (Array.isArray(n.children) && depth < 4) walk(n.children, depth + 1, out);
  }
  return out;
}

function nodeLabel(n: Node, catalog: BlockCatalog | null): string {
  if (n.t === "block" && n.type === "c21") return "قطعهٔ 21st.dev";
  if (n.t === "block") return catalog?.blocks.find((b) => b.type === n.type)?.label ?? String(n.type);
  return n.name || ({ frame: "قاب Auto Layout", text: "متن", button: "دکمه", image: "تصویر", rect: "مستطیل", input: "فیلد", spacer: "فاصله", icon: "نماد" } as Record<string, string>)[n.t] || String(n.t);
}

// ───────────────────────────── فرمِ مشخصه‌های بلوک (از تعریفِ سایت‌ساز)

function ItemsEditor({ spec, items, onChange }: { spec: FieldSpec; items: Record<string, any>[]; onChange: (v: Record<string, any>[]) => void }) {
  return (
    <div className="ds-objs ds-wide">
      <div className="ds-sub">{spec.label}</div>
      {items.map((it, i) => (
        <div key={i} className="ds-obj">
          {(spec.fields ?? []).map((f) => (
            <PropField key={f.key} spec={f} value={it[f.key]} onChange={(v) => onChange(items.map((x, j) => (j === i ? { ...x, [f.key]: v } : x)))} compact />
          ))}
          <Button size="sm" variant="ghost" type="button" onClick={() => onChange(items.filter((_, j) => j !== i))}><Icon name="trash" size={14} /> حذف</Button>
        </div>
      ))}
      <Button size="sm" variant="secondary" type="button" onClick={() => onChange([...items, Object.fromEntries((spec.fields ?? []).map((f) => [f.key, f.kind === "toggle" ? false : ""]))])}><Icon name="plus" size={14} /> {spec.add_label || "افزودن"}</Button>
    </div>
  );
}

function PropField({ spec, value, onChange, compact }: { spec: FieldSpec; value: any; onChange: (v: any) => void; compact?: boolean }) {
  const [d, setD] = useState<string | null>(null);
  const commit = (v: string) => {
    setD(null);
    if (v !== (value ?? "")) onChange(v);
  };
  if (spec.kind === "items") return <ItemsEditor spec={spec} items={Array.isArray(value) ? value : []} onChange={onChange} />;
  if (spec.kind === "toggle") return <label className="ds-check-row"><input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {spec.label}</label>;
  if (spec.kind === "select") {
    return (
      <Field label={spec.label}>
        <Select value={String(value ?? "")} onChange={(e) => { const o = spec.options?.find((x) => String(x.value) === e.target.value); onChange(typeof o?.value === "number" ? o.value : e.target.value); }}>
          {spec.options?.map((o) => <option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}
        </Select>
      </Field>
    );
  }
  if (spec.kind === "slider") {
    const n = typeof value === "number" ? value : value && typeof value === "object" ? (value.d ?? 0) : Number(value) || 0;
    return <Field label={`${spec.label}: ${fa(n)}${spec.unit ? " " + spec.unit : ""}`}><Input type="range" min={spec.min ?? 0} max={spec.max ?? 100} value={n} onChange={(e) => onChange(typeof value === "object" && value ? { ...value, d: Number(e.target.value) } : Number(e.target.value))} /></Field>;
  }
  if (spec.kind === "textarea" || spec.kind === "rich" || spec.kind === "code") {
    return <Field label={spec.label} wide><TextArea rows={compact ? 2 : 3} value={d ?? String(value ?? "")} onChange={(e) => setD(e.target.value)} onBlur={(e) => commit(e.target.value)} /></Field>;
  }
  if (spec.kind === "color") return <ColorField label={spec.label} value={String(value ?? "")} onChange={onChange} />;
  if (spec.kind === "image" || spec.kind === "link" || spec.kind === "icon" || spec.kind === "model" || spec.kind === "fields" || spec.kind === "sort" || spec.kind === "detail_link") {
    return <Field label={spec.label}><Input value={d ?? String(typeof value === "string" ? value : "")} onChange={(e) => setD(e.target.value)} onBlur={(e) => commit(e.target.value)} dir={spec.kind === "link" ? "ltr" : undefined} /></Field>;
  }
  return <Field label={spec.label}><Input type={spec.kind === "decimal" ? "number" : "text"} value={d ?? String(value ?? "")} onChange={(e) => setD(e.target.value)} onBlur={(e) => commit(e.target.value)} /></Field>;
}

// ───────────────────────────── راهنمای سبک

function StyleGuide({ storeId, docId, rev, scene, width }: { storeId: string; docId: number; rev: number; scene: Scene; width: number }) {
  const img = usePreview(scene.styleguide ? designApi.previewUrl(storeId, docId, "styleguide", Math.min(1600, width * 2), rev) : null);
  const t = scene.tokens;
  if (!t) return null;
  return (
    <div className="ds-guide">
      {img ? <img src={img} alt="راهنمای سبک" style={{ width }} /> : <Spinner />}
      <div className="ds-sub">توکن‌ها (برای برنامه‌نویس)</div>
      <table className="ds-table">
        <thead><tr><th>نقش</th><th>روشن</th><th>تیره</th></tr></thead>
        <tbody>
          {Object.keys(t.light).map((k) => (
            <tr key={k}><td><code>--{k.replace("_", "-")}</code></td>
              <td><span className="ds-dot" style={{ background: t.light[k] }} /> <code>{t.light[k]}</code></td>
              <td><span className="ds-dot" style={{ background: t.dark[k] }} /> <code>{t.dark[k]}</code></td></tr>
          ))}
        </tbody>
      </table>
      <p className="ds-muted">گردی: {fa(t.radius)} پیکسل · فاصله‌ها: {t.space.map((s) => fa(s)).join("، ")} · مقیاسِ تایپ: {Object.entries(t.type).map(([k, v]) => `${k} ${fa(v)}`).join("، ")}</p>
    </div>
  );
}

export default function UiEditor() {
  const { id = "", docId = "" } = useParams<{ id: string; docId: string }>();
  const { user } = useAuth();
  const { ov } = useOverview(id);
  const [mode, setMode] = useState<"light" | "dark">("light");
  const ed = useDocEditor(id, Number(docId), mode === "dark" ? "dark" : undefined);
  const [fid, setFid] = useState<string | null>(null);
  const [nid, setNid] = useState<string | null>(null);
  const [tab, setTab] = useState<"layers" | "props" | "style" | "guide" | "proto" | "comments">("layers");
  const [catalog, setCatalog] = useState<BlockCatalog | null>(null);
  const [showExport, setShowExport] = useState(false);
  const [comments, setComments] = useState<Comment[]>([]);
  const [draftC, setDraftC] = useState<{ x: number; y: number; text: string } | null>(null);
  const [site, setSite] = useState<SiteInfo | null>(null);
  const [siteBusy, setSiteBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [playHist, setPlayHist] = useState<string[]>([]);
  const wrap = useRef<HTMLDivElement>(null);
  const cw = useWidth(wrap, 300);
  const doc = ed.doc;
  const scene = ed.scene;

  useEffect(() => {
    designApi.uiCatalog(id).then(setCatalog).catch(() => undefined);
  }, [id]);
  useEffect(() => {
    if (doc && !fid) setFid(doc.data.frames[0]?.id ?? null);
  }, [doc, fid]);
  const loadComments = () => designApi.comments(id, Number(docId)).then(setComments).catch(() => undefined);
  useEffect(() => {
    void loadComments();
  }, [id, docId]); // eslint-disable-line react-hooks/exhaustive-deps

  const frames: Node[] = doc?.data.frames ?? [];
  const frame = frames.find((f) => f.id === fid) ?? frames[0];
  const page: ScenePage | undefined = scene?.pages.find((p) => p.id === frame?.id);
  const flat = useMemo(() => (frame ? walk(frame.children ?? []) : []), [frame]);
  const node = flat.find((x) => x.n.id === nid)?.n;
  const deviceW = frame?.device === "desktop" ? 1440 : frame?.device === "tablet" ? 834 : 390;
  const shown = Math.min(cw, frame?.device === "phone" ? 380 : frame?.device === "tablet" ? 620 : 860);
  const staff = !!user?.is_staff;

  if (ed.error && !doc) return <div className="ds-page"><ErrorBox message={ed.error} /></div>;
  if (!doc || !scene || !ov || !frame) return <div className="ds-page"><Spinner /></div>;

  const ops = (o: any[]) => ed.apply(o);
  const topIds = new Set((frame.children ?? []).map((c: Node) => c.id));
  const boxes = (page?.meta?.nodes ?? []).filter((b) => (tab === "layers" || tab === "props") && (topIds.has(b.id) || b.id === nid));
  const frameOptions = frames.map((f) => <option key={f.id} value={f.id}>{f.name} ({DEV_FA[f.device]})</option>);
  const settings = scene.settings;
  const groups = catalog?.groups ?? [];
  const bdef = node?.t === "block" ? catalog?.blocks.find((b) => b.type === node.type) : undefined;

  const addNode = async (type: string) => {
    const r = await ops([{ op: "add_node", frame: frame.id, type }]);
    if (r) {
      const f = r.data.frames.find((x: Node) => x.id === frame.id);
      setNid(f.children[f.children.length - 1].id);
      setTab("props");
    }
  };
  const addPrimitive = (n: Node) => ops([{ op: "add_node", frame: frame.id, parent: node && node.t === "frame" ? node.id : undefined, node: n }]);
  const moveNode = (n: Node, delta: number) => {
    const list = frame.children as Node[];
    const i = list.findIndex((c) => c.id === n.id);
    if (i >= 0) void ops([{ op: "move_node", frame: frame.id, node: n.id, to: i + delta }]);
  };
  const buildSite = async () => {
    if (!window.confirm("از این طرح یک پیش‌نویس در سایت‌ساز ساخته شود؟ (چیزی منتشر نمی‌شود)")) return;
    setSiteBusy(true);
    try {
      setSite(await designApi.site(id, doc.id, { name: doc.title }));
      setMsg("پیش‌نویسِ سایت ساخته شد.");
    } catch (e) {
      ed.setError(apiError(e));
    } finally {
      setSiteBusy(false);
    }
  };
  const siteLink = site ?? (doc.meta?.site as SiteInfo | undefined);

  return (
    <div className="ds-page">
      <PageHeader title={doc.title} subtitle={`طراحیِ UI/UX · سبک «${scene.tokens?.style_label}» · ${fa(frames.length)} فریم`}
        actions={
          <>
            <Link to={`/stores/${id}/design/ui`}><Button variant="ghost" type="button"><Icon name="back" size={14} /> فهرست</Button></Link>
            <Button variant="secondary" type="button" onClick={() => setMode(mode === "light" ? "dark" : "light")}><Icon name={mode === "light" ? "moon" : "sun"} size={14} /> {mode === "light" ? "پیش‌نمایشِ تیره" : "پیش‌نمایشِ روشن"}</Button>
            <Button variant="secondary" type="button" onClick={() => setShowExport(true)}><Icon name="download" size={14} /> خروجی (PNG، SVG، PDF)</Button>
            <Button type="button" disabled={siteBusy || !staff} title={staff ? "" : "سایت‌ساز فقط برای کارکنان است"} onClick={buildSite}>{siteBusy ? <Spinner size={14} /> : <Icon name="rocket" size={14} />} ساختِ سایت از این طرح</Button>
          </>
        } />
      {ed.notice ? <Alert tone="warn">{ed.notice}</Alert> : null}
      {msg ? <Alert tone="ok">{msg}</Alert> : null}
      {ed.error ? <ErrorBox message={ed.error} /> : null}
      {siteLink ? (
        <Alert tone="ok" title="پیش‌نویسِ سایت ساخته شد (منتشر نشده)">
          {fa(siteLink.pages.length)} صفحه · سبک {siteLink.style} · <Link to={`/tools/studio/p/${siteLink.slug}/builder/page`}>بازکردن در سایت‌ساز</Link> · هر صفحه و سربرگ/پابرگ جدا نشسته و پیوندِ دکمه‌ها به نشانیِ صفحه‌ها تبدیل شده است.
        </Alert>
      ) : null}

      <div className="ds-editor ds-ui">
        <aside className="ds-strip" aria-label="فریم‌ها">
          {scene.pages.map((p) => {
            const f = frames.find((x) => x.id === p.id);
            return (
              <div key={p.id} className="ds-frame-card">
                <Thumb storeId={id} docId={doc.id} page={p} rev={doc.rev} width={p.w > 1000 ? 130 : p.w > 600 ? 90 : 60} active={p.id === frame.id} label={`${f?.name ?? p.name} · ${DEV_FA[p.device ?? ""] ?? ""}`}
                  onClick={() => { setFid(p.id); setNid(null); }} mode={mode === "dark" ? "dark" : undefined} />
              </div>
            );
          })}
          <div className="ds-addpage">
            {(["desktop", "tablet", "phone"] as const).map((d) => (
              <Button key={d} size="sm" variant="secondary" type="button" onClick={async () => { const r = await ops([{ op: "add_frame", device: d, name: `${frame.name.split(" · ")[0]} · ${DEV_FA[d]}`, copy_of: frame.id, of: frame.of || frame.id }]); if (r) setFid(r.data.frames[r.data.frames.length - 1].id); }}>+ {DEV_FA[d]}</Button>
            ))}
          </div>
        </aside>

        <main className="ds-stage" ref={wrap}>
          <div className="ds-stagebar">
            <div className="ds-row">
              <Input aria-label="نامِ فریم" onBlur={(e) => e.target.value !== frame.name && ops([{ op: "update_frame", frame: frame.id, set: { name: e.target.value } }])} defaultValue={frame.name} key={frame.id} />
              <Select value={frame.device} onChange={(e) => ops([{ op: "update_frame", frame: frame.id, set: { device: e.target.value } }])} aria-label="دستگاه">
                {Object.entries(DEV_FA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
              <Select value={frame.mode || ""} onChange={(e) => ops([{ op: "update_frame", frame: frame.id, set: { mode: e.target.value } }])} aria-label="حالتِ فریم">
                <option value="">حالتِ سند</option><option value="light">روشن</option><option value="dark">تیره</option>
              </Select>
            </div>
            <div className="ds-row">
              {frame.of ? <Button size="sm" variant="ghost" type="button" onClick={() => ops([{ op: "sync_responsive", frame: frame.of }])} title="چیدمانِ فریمِ اصلی را در فریم‌های هم‌خانواده کپی می‌کند">همگام‌سازی با اصلی</Button> : frames.some((f) => f.of === frame.id) ? <Button size="sm" variant="ghost" type="button" onClick={() => ops([{ op: "sync_responsive", frame: frame.id }])}>همگام‌سازیِ تبلت/گوشی با این</Button> : null}
              <Button size="sm" variant="danger" type="button" onClick={() => window.confirm("این فریم حذف شود؟") && ops([{ op: "delete_frame", frame: frame.id }]).then(() => setFid(null))}><Icon name="trash" size={14} /></Button>
            </div>
          </div>
          {tab === "proto" && page ? (
            <>
              <div className="ds-row"><Badge tone="info">نمونهٔ کلیک‌پذیر</Badge>{playHist.length ? <Button size="sm" variant="ghost" type="button" onClick={() => { const h = [...playHist]; setFid(h.pop() ?? fid); setPlayHist(h); }}><Icon name="back" size={14} /> برگشت</Button> : null}<span className="ds-muted">روی دکمه‌هایی که پیوند دارند بزن.</span></div>
              <div className={`ds-device ds-device-${frame.device}`}><PageCanvas storeId={id} docId={doc.id} page={page} rev={doc.rev} width={shown} mode={mode === "dark" ? "dark" : undefined} pointerMode="play" hotspots={page.meta?.hotspots ?? []}
                onHotspot={(to) => { setPlayHist([...playHist, frame.id]); setFid(to); }} /></div>
            </>
          ) : page && tab === "comments" ? (
            <>
              <div className="ds-row"><Badge tone="info">برای نظر دادن روی جای دقیق کلیک کن</Badge></div>
              <PageCanvas storeId={id} docId={doc.id} page={page} rev={doc.rev} width={shown} mode={mode === "dark" ? "dark" : undefined} pointerMode="comment" onBackgroundClick={(x, y) => setDraftC({ x, y, text: "" })}
                overlays={<>{comments.filter((c) => c.frame === frame.id && !c.parent).map((c, i) => <span key={c.id} className={`ds-pin ${c.resolved ? "is-done" : ""}`} style={{ left: `${c.x * 100}%`, top: `${c.y * 100}%` }} title={c.text}>{fa(i + 1)}</span>)}
                  {draftC ? <span className="ds-pin is-new" style={{ left: `${draftC.x * 100}%`, top: `${draftC.y * 100}%` }}>+</span> : null}</>} />
            </>
          ) : page ? (
            <PageCanvas storeId={id} docId={doc.id} page={page} rev={doc.rev} width={shown} mode={mode === "dark" ? "dark" : undefined} selected={nid} onSelect={(x) => { setNid(x); if (x) setTab("props"); }} boxes={boxes} />
          ) : <Spinner />}
          <p className="ds-muted">{DEV_FA[frame.device]} · {fa(deviceW)} پیکسل · فریمِ {mode === "dark" ? "تیره" : "روشن"} (متغیرها عوض می‌شوند، چیدمان نه)</p>
        </main>

        <section className="ds-side">
          <div className="ds-tabs" role="tablist">
            {([["layers", "لایه‌ها"], ["props", "ویژگی"], ["style", "سبک و توکن"], ["guide", "راهنمای سبک"], ["proto", "نمونهٔ اولیه"], ["comments", "نظرها"]] as const).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "is-on" : ""} onClick={() => setTab(k)} type="button">{l}</button>
            ))}
          </div>

          {tab === "layers" ? (
            <div className="ds-panel">
              <div className="ds-sub">لایه‌های این فریم</div>
              <div className="ds-layers">
                {flat.map(({ n, depth }) => (
                  <div key={n.id} className={`ds-layer ${n.id === nid ? "is-on" : ""}`} style={{ paddingInlineStart: 8 + depth * 14 }}>
                    <button type="button" className="ds-layer-name" onClick={() => { setNid(n.id); setTab("props"); }}>{nodeLabel(n, catalog)}{n.link ? " 🔗" : ""}</button>
                    {depth === 0 ? (
                      <>
                        <button type="button" aria-label="بالا" onClick={() => moveNode(n, -1)}><Icon name="up" size={13} /></button>
                        <button type="button" aria-label="پایین" onClick={() => moveNode(n, 1)}><Icon name="down" size={13} /></button>
                      </>
                    ) : null}
                    <button type="button" aria-label="حذف" onClick={() => ops([{ op: "remove_node", frame: frame.id, node: n.id }]).then(() => setNid(null))}><Icon name="trash" size={13} /></button>
                  </div>
                ))}
                {!flat.length ? <p className="ds-muted">فریم خالی است؛ از پایین قطعه اضافه کن.</p> : null}
              </div>
              <div className="ds-sub">افزودنِ قطعه (همان کتابخانهٔ سایت‌ساز)</div>
              <select className="u-input" aria-label="قطعه" onChange={(e) => { if (e.target.value) void addNode(e.target.value); e.target.value = ""; }} defaultValue="">
                <option value="">+ قطعه…</option>
                {groups.map((g) => (
                  <optgroup key={g.value} label={g.label}>
                    {catalog?.blocks.filter((b) => b.group === g.value).map((b: BlockDef) => <option key={b.type} value={b.type}>{b.label}</option>)}
                  </optgroup>
                ))}
              </select>
              <div className="ds-sub">قطعه‌های آمادهٔ 21st.dev (جست‌وجو، پیش‌نمایش، درج)</div>
              <C21Panel onAdd={(n) => addPrimitive(n)} />
              <div className="ds-sub">Auto Layout و عنصرها {node?.t === "frame" ? "(داخلِ قابِ انتخاب‌شده)" : ""}</div>
              <div className="ds-row ds-wrap">
                <Button size="sm" variant="secondary" type="button" onClick={() => addPrimitive({ t: "frame", name: "پشتهٔ عمودی", dir: "v", gap: 12, pad: [16, 16, 16, 16], fill: "var:surface", radius: 14, children: [] })}>+ پشتهٔ عمودی</Button>
                <Button size="sm" variant="secondary" type="button" onClick={() => addPrimitive({ t: "frame", name: "ردیف", dir: "h", gap: 12, pad: [16, 16, 16, 16], fill: "var:surface", radius: 14, children: [] })}>+ ردیف</Button>
                <Button size="sm" variant="secondary" type="button" onClick={() => addPrimitive({ t: "frame", name: "شبکه", dir: "grid", cols: 3, gap: 16, pad: [16, 16, 16, 16], children: [] })}>+ شبکه</Button>
                <Button size="sm" variant="secondary" type="button" onClick={() => addPrimitive({ t: "text", text: "متنِ تازه", size: 20, weight: 600 })}>+ متن</Button>
                <Button size="sm" variant="secondary" type="button" onClick={() => addPrimitive({ t: "button", text: "دکمه", variant: "filled" })}>+ دکمه</Button>
                <Button size="sm" variant="secondary" type="button" onClick={() => addPrimitive({ t: "image", src: "", ratio: 0.6 })}>+ تصویر</Button>
                <Button size="sm" variant="secondary" type="button" onClick={() => addPrimitive({ t: "input", label: "نام", placeholder: "مثلاً علی" })}>+ فیلد</Button>
                <Button size="sm" variant="secondary" type="button" onClick={() => addPrimitive({ t: "spacer", h: 32, w: "fill" })}>+ فاصله</Button>
              </div>
            </div>
          ) : null}

          {tab === "props" ? (
            <div className="ds-panel">
              {!node ? <p className="ds-muted">یک لایه یا بلوک را انتخاب کن.</p> : (
                <>
                  <div className="ds-sub">{nodeLabel(node, catalog)} {bdef?.hint ? <small className="ds-muted">— {bdef.hint}</small> : null}</div>
                  <div className="ds-form">
                    {node.t === "block" && bdef ? bdef.fields.map((f) => (
                      <PropField key={f.key} spec={f} value={node.props?.[f.key]} onChange={(v) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { props: { [f.key]: v } } }])} />
                    )) : null}
                    {node.t === "frame" ? (
                      <>
                        <Field label="جهت"><Select value={node.dir ?? "v"} onChange={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { dir: e.target.value } }])}><option value="v">عمودی (پشته)</option><option value="h">افقی (ردیف)</option><option value="grid">شبکه</option><option value="z">رویِ هم</option></Select></Field>
                        <Field label={`فاصلهٔ بین فرزندها: ${fa(node.gap ?? 0)}`}><Input type="range" min={0} max={80} value={node.gap ?? 0} onChange={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { gap: Number(e.target.value) } }])} /></Field>
                        <Field label={`فاصلهٔ داخلی (Padding): ${fa(Array.isArray(node.pad) ? node.pad[0] : node.pad ?? 0)}`}><Input type="range" min={0} max={96} value={Array.isArray(node.pad) ? node.pad[0] : node.pad ?? 0} onChange={(e) => { const v = Number(e.target.value); void ops([{ op: "update_node", frame: frame.id, node: node.id, set: { pad: [v, v, v, v] } }]); }} /></Field>
                        {node.dir === "grid" ? <Field label={`ستون: ${fa(node.cols ?? 2)}`}><Input type="range" min={1} max={6} value={node.cols ?? 2} onChange={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { cols: Number(e.target.value) } }])} /></Field> : null}
                        <Field label="ترازِ فرزندها"><Select value={node.align ?? "stretch"} onChange={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { align: e.target.value } }])}><option value="stretch">کشیده</option><option value="start">شروع</option><option value="center">وسط</option><option value="end">پایان</option></Select></Field>
                        <Field label="توزیع"><Select value={node.justify ?? "start"} onChange={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { justify: e.target.value } }])}><option value="start">شروع</option><option value="center">وسط</option><option value="end">پایان</option><option value="between">فاصلهٔ مساوی</option></Select></Field>
                        <Field label="رنگِ پس‌زمینه (متغیر یا هگز)"><Input dir="ltr" defaultValue={node.fill ?? ""} key={node.id + "f"} placeholder="var:surface" onBlur={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { fill: e.target.value || null } }])} /></Field>
                        <Field label={`گردی: ${fa(node.radius ?? 0)}`}><Input type="range" min={0} max={60} value={node.radius ?? 0} onChange={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { radius: Number(e.target.value) } }])} /></Field>
                      </>
                    ) : null}
                    {node.t === "text" ? (
                      <>
                        <Field label="متن" wide><TextArea rows={3} defaultValue={node.text} key={node.id + "t"} onBlur={(e) => e.target.value !== node.text && ops([{ op: "update_node", frame: frame.id, node: node.id, set: { text: e.target.value } }])} /></Field>
                        <Field label={`اندازه: ${fa(node.size ?? 16)}`}><Input type="range" min={10} max={96} value={node.size ?? 16} onChange={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { size: Number(e.target.value) } }])} /></Field>
                        <Field label="وزن"><Select value={String(node.weight ?? 400)} onChange={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { weight: Number(e.target.value) } }])}>{[400, 500, 600, 700, 800].map((w) => <option key={w} value={w}>{fa(w)}</option>)}</Select></Field>
                        <Field label="رنگ (متغیر یا هگز)"><Input dir="ltr" defaultValue={node.color ?? "var:text"} key={node.id + "c"} onBlur={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { color: e.target.value || "var:text" } }])} /></Field>
                      </>
                    ) : null}
                    {node.t === "button" ? (
                      <>
                        <Field label="متنِ دکمه"><Input defaultValue={node.text} key={node.id + "b"} onBlur={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { text: e.target.value } }])} /></Field>
                        <Field label="شکل"><Select value={node.variant ?? "filled"} onChange={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { variant: e.target.value } }])}><option value="filled">پررنگ</option><option value="outline">حاشیه‌دار</option><option value="soft">کم‌رنگ</option></Select></Field>
                      </>
                    ) : null}
                    {node.t === "input" ? (
                      <>
                        <Field label="عنوانِ فیلد"><Input defaultValue={node.label} key={node.id + "l"} onBlur={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { label: e.target.value } }])} /></Field>
                        <Field label="نمونهٔ متن"><Input defaultValue={node.placeholder} key={node.id + "p"} onBlur={(e) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { placeholder: e.target.value } }])} /></Field>
                      </>
                    ) : null}
                    {node.t === "image" ? <Field label="تصویر" wide><ImagePicker storeId={id} products={ov.products} hasLogo={ov.store.has_logo} value={node.src ?? ""} onChange={(v) => ops([{ op: "update_node", frame: frame.id, node: node.id, set: { src: v } }])} /></Field> : null}
                  </div>
                  <div className="ds-sub">پیوندِ نمونهٔ اولیه</div>
                  <Field label="با کلیک برود به فریم…">
                    <Select value={node.link?.frame ?? ""} onChange={(e) => ops([{ op: "set_link", frame: frame.id, node: node.id, to: e.target.value }])}>
                      <option value="">— بدونِ پیوند —</option>
                      {frameOptions}
                    </Select>
                  </Field>
                  <Button size="sm" variant="danger" type="button" onClick={() => ops([{ op: "remove_node", frame: frame.id, node: node.id }]).then(() => setNid(null))}><Icon name="trash" size={14} /> حذفِ این لایه</Button>
                </>
              )}
            </div>
          ) : null}

          {tab === "style" ? (
            <div className="ds-panel">
              <div className="ds-sub">سبکِ طراحی (از ۱۴ سبکِ ui-ux-pro-max)</div>
              <div className="ds-styles">
                {ov.ui.styles.map((s) => (
                  <button type="button" key={s.key} className={`ds-style ${scene.tokens?.style === s.key ? "is-on" : ""}`} onClick={() => ops([{ op: "set_settings", set: { style: s.key } }])} title={s.desc}>
                    <span className="ds-style-dots">{["primary", "bg", "surface", "text"].map((k) => <i key={k} style={{ background: s.colors[k] }} />)}</span>
                    <b>{s.label}</b><small>{s.mood}</small>
                  </button>
                ))}
              </div>
              <div className="ds-form">
                <ColorField label="رنگِ برند (خالی = رنگِ فروشگاه)" value={settings.brand_color || ""} onChange={(v) => /^#[0-9a-f]{6}$/i.test(v) || v === "" ? void ops([{ op: "set_settings", set: { brand_color: v } }]) : undefined} />
                <Field label="فونتِ تیتر"><Select value={settings.font_head ?? "vazirmatn"} onChange={(e) => ops([{ op: "set_settings", set: { font_head: e.target.value } }])}>{ov.fonts.map((f) => <option key={f.key} value={f.key}>{f.title}</option>)}</Select></Field>
                <Field label="فونتِ متن"><Select value={settings.font_body ?? "vazirmatn"} onChange={(e) => ops([{ op: "set_settings", set: { font_body: e.target.value } }])}>{ov.fonts.map((f) => <option key={f.key} value={f.key}>{f.title}</option>)}</Select></Field>
                <Field label={`گردیِ پایه: ${fa(Math.round(scene.tokens?.radius ?? 12))} پیکسل`}><Input type="range" min={0} max={40} value={scene.tokens?.radius ?? 12} onChange={(e) => ops([{ op: "set_settings", set: { radius: Number(e.target.value) } }])} /></Field>
                <Field label="رقم‌ها"><Select value={settings.digits ?? "fa"} onChange={(e) => ops([{ op: "set_settings", set: { digits: e.target.value } }])}><option value="fa">فارسی</option><option value="en">لاتین</option><option value="keep">همان‌که نوشته‌ام</option></Select></Field>
                <Field label="منوی سربرگ (هر خط یک مورد)" wide><TextArea rows={3} defaultValue={(settings.menu ?? []).join("\n")} key={String(settings.menu)} onBlur={(e) => ops([{ op: "set_settings", set: { menu: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) } }])} /></Field>
              </div>
              {scene.tokens ? (
                <>
                  <div className="ds-sub">متغیرهای رنگ (روشن / تیره) — هر نقش را عوض کنی همهٔ فریم‌ها عوض می‌شود</div>
                  <div className="ds-vars">
                    {["primary", "bg", "surface", "text", "muted"].map((k) => (
                      <div key={k} className="ds-var">
                        <code>{k}</code>
                        <input type="color" aria-label={`${k} روشن`} value={scene.tokens!.light[k]} onChange={(e) => ops([{ op: "set_settings", set: { colors: { ...(settings.colors || {}), light: { ...((settings.colors || {}).light || {}), [k]: e.target.value } } } }])} />
                        <input type="color" aria-label={`${k} تیره`} value={scene.tokens!.dark[k]} onChange={(e) => ops([{ op: "set_settings", set: { colors: { ...(settings.colors || {}), dark: { ...((settings.colors || {}).dark || {}), [k]: e.target.value } } } }])} />
                      </div>
                    ))}
                  </div>
                </>
              ) : null}
              <ChecksPanel checks={scene.checks} title="بازبینی" />
            </div>
          ) : null}

          {tab === "guide" ? <div className="ds-panel"><StyleGuide storeId={id} docId={doc.id} rev={doc.rev} scene={scene} width={Math.min(520, cw)} /></div> : null}

          {tab === "proto" ? (
            <div className="ds-panel">
              <div className="ds-sub">پیوندهای بین فریم‌ها</div>
              {(scene.links ?? []).length ? (
                <ul className="ds-links">
                  {(scene.links ?? []).map((l, i) => {
                    const from = frames.find((f) => f.id === l.from);
                    const to = frames.find((f) => f.id === l.to);
                    return <li key={i}>{from?.name} <Icon name="back" size={12} /> {to?.name}</li>;
                  })}
                </ul>
              ) : <p className="ds-muted">هنوز پیوندی نیست. یک دکمه را انتخاب کن (تب «ویژگی») و «با کلیک برود به فریم…» را بزن؛ بعد همین‌جا روی طرح کلیک کن.</p>}
              <p className="ds-muted">پیوندها در «ساختِ سایت» به نشانیِ صفحه‌ها تبدیل می‌شوند.</p>
            </div>
          ) : null}

          {tab === "comments" ? (
            <div className="ds-panel">
              {draftC ? (
                <div className="ds-obj">
                  <TextArea rows={3} value={draftC.text} onChange={(e) => setDraftC({ ...draftC, text: e.target.value })} placeholder="نظرت را بنویس…" />
                  <div className="ds-row">
                    <Button size="sm" type="button" disabled={!draftC.text.trim()} onClick={async () => { try { await designApi.addComment(id, doc.id, { frame: frame.id, x: draftC.x, y: draftC.y, text: draftC.text }); setDraftC(null); await loadComments(); } catch (e) { ed.setError(apiError(e)); } }}>ثبتِ نظر</Button>
                    <Button size="sm" variant="ghost" type="button" onClick={() => setDraftC(null)}>انصراف</Button>
                  </div>
                </div>
              ) : <p className="ds-muted">روی طرح (سمتِ چپ) در جای دلخواه کلیک کن تا نظر بگذاری.</p>}
              {comments.filter((c) => c.frame === frame.id && !c.parent).map((c, i) => (
                <div key={c.id} className={`ds-comment ${c.resolved ? "is-done" : ""}`}>
                  <div className="ds-row"><b>{fa(i + 1)}</b><span>{c.author || "ناشناس"}</span>{c.resolved ? <Badge tone="ok">حل شد</Badge> : null}</div>
                  <p>{c.text}</p>
                  {comments.filter((r) => r.parent === c.id).map((r) => <p key={r.id} className="ds-reply">↳ {r.text}</p>)}
                  <div className="ds-row">
                    <Button size="sm" variant="secondary" type="button" onClick={async () => { await designApi.patchComment(id, c.id, { resolved: !c.resolved }); await loadComments(); }}>{c.resolved ? "بازکردن" : "حل شد"}</Button>
                    <Button size="sm" variant="ghost" type="button" onClick={async () => { const t = window.prompt("پاسخ:"); if (t) { await designApi.addComment(id, doc.id, { frame: frame.id, parent: c.id, text: t }); await loadComments(); } }}>پاسخ</Button>
                    <Button size="sm" variant="ghost" type="button" aria-label="حذف" onClick={async () => { await designApi.deleteComment(id, c.id); await loadComments(); }}><Icon name="trash" size={14} /></Button>
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </section>
      </div>
      {showExport ? <ExportDialog storeId={id} doc={doc} ov={ov} checks={scene.checks} onClose={() => setShowExport(false)} /> : null}
    </div>
  );
}
