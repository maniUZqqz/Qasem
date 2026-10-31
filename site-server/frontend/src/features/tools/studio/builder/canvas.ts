/**
 * کنترل‌کنندهٔ بوم (iframe).
 *
 * محتوای بوم همان خروجیِ رندرکنندهٔ سرور است؛ این فایل فقط انتخاب، ویرایشِ متن و جای‌گذاریِ کشیدن را روی آن
 * اضافه می‌کند. هیچ اسکریپتی داخلِ iframe اجرا نمی‌شود: همهٔ رویدادها از بیرون وصل‌اند و چیزی از این لایه
 * در خروجیِ سایت نمی‌ماند.
 */
import type { DropTarget } from "./doc";

export type CanvasPayload = {
  base_css: string;
  page_css: string;
  parts: { id: string; html: string }[];
  header: string;
  footer: string;
  warnings: { id: string; type: string; text: string }[];
  sample_models: string[];
  title: string;
};

export type BarAction = "up" | "down" | "duplicate" | "delete" | "parent" | "save";

export type CanvasCallbacks = {
  onSelect: (id: string | null) => void;
  onText: (id: string, path: string, value: string) => void;
  onAction: (action: BarAction, id: string) => void;
  onStartMove: (id: string, parentX: number, parentY: number) => void;
  onChrome: (which: "header" | "footer") => void;
  onKey: (e: KeyboardEvent) => void;
  labelOf: (type: string) => string;
};

const BAR_ICONS: Record<string, string> = {
  move: '<path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  parent: '<path d="M9 14L4 9l5-5"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>',
  duplicate: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  save: '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
  delete: '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
};

function barBtn(act: string, title: string): string {
  return `<button type="button" data-act="${act}" title="${title}" aria-label="${title}"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${BAR_ICONS[act]}</svg></button>`;
}

const UI_CSS = `
html{scroll-behavior:auto}
#nb-h,#nb-f{display:contents}
#nb-h>*,#nb-f>*{cursor:pointer}
.nb-custom{display:block!important}
[data-bid]{cursor:default}
[data-nb-edit]{cursor:text;outline:none}
[data-nb-edit]:empty::before,.nb-blank:empty::before{content:"این‌جا بنویس…";opacity:.4}
[contenteditable]{outline:2px dashed #6366f1!important;outline-offset:2px;border-radius:3px;cursor:text}
iframe,video{pointer-events:none}
form *{pointer-events:none}
form [data-nb-edit]{pointer-events:auto}
.nb-header.is-sticky{position:relative}
.nb-drop-here{border:2px dashed #94a3b8;color:#64748b;border-radius:12px;padding:26px 14px;text-align:center;font-size:14px;background:rgba(148,163,184,.08);font-family:inherit}
.nb-col:has(>.nb-drop-here){min-height:80px}
#nb-ui{position:absolute;inset:0 0 auto 0;height:0;z-index:2147483000;font-family:Vazirmatn,Tahoma,sans-serif}
#nb-hover,#nb-sel,#nb-line{position:absolute;pointer-events:none;display:none}
#nb-hover{outline:1px solid #818cf8;outline-offset:-1px}
#nb-sel{outline:2px solid #4f46e5;outline-offset:-1px}
#nb-line{height:4px;background:#4f46e5;border-radius:4px;box-shadow:0 0 0 2px rgba(255,255,255,.8)}
#nb-bar{position:absolute;pointer-events:auto;display:flex;gap:1px;background:#312e81;color:#fff;border-radius:9px;padding:2px;box-shadow:0 6px 18px rgba(15,23,42,.35);direction:rtl;white-space:nowrap}
#nb-bar span{font-size:12px;padding:5px 8px 5px 6px;line-height:20px;font-weight:600}
#nb-bar button{all:unset;display:grid;place-items:center;width:28px;height:28px;border-radius:7px;cursor:pointer;color:#fff}
#nb-bar button:hover{background:rgba(255,255,255,.18)}
#nb-bar button[data-act=move]{cursor:grab;touch-action:none}
#nb-bar button[data-act=delete]:hover{background:#dc2626}
#nb-rich{position:absolute;display:none;pointer-events:auto;gap:1px;background:#0f172a;color:#fff;border-radius:8px;padding:2px;box-shadow:0 6px 18px rgba(15,23,42,.35)}
#nb-rich button{all:unset;display:grid;place-items:center;min-width:28px;height:28px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:700}
#nb-rich button:hover{background:rgba(255,255,255,.2)}
@media (max-width:640px){#nb-bar button{width:34px;height:34px}#nb-bar span{display:none}}
body.nb-preview #nb-ui{display:none}
body.nb-preview [data-nb-ph]{visibility:hidden}
`;

const SKELETON =
  '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
  `<style id="s-base"></style><style id="s-page"></style><style id="s-ui">${UI_CSS}</style></head>` +
  '<body><div id="nb-h"></div><main id="page-body"></main><div id="nb-f"></div>' +
  '<div id="nb-ui"><div id="nb-hover"></div><div id="nb-sel"></div><div id="nb-line"></div>' +
  `<div id="nb-bar">${barBtn("move", "بکش و جابه‌جا کن")}${barBtn("up", "بالاتر")}${barBtn("down", "پایین‌تر")}${barBtn("parent", "انتخابِ بخشِ بیرونی")}${barBtn("duplicate", "کپی")}${barBtn("save", "ذخیرهٔ این بخش")}${barBtn("delete", "حذف")}<span id="nb-bar-label"></span></div>` +
  '<div id="nb-rich"><button data-cmd="bold" title="پررنگ"><b>B</b></button><button data-cmd="italic" title="کج"><i>I</i></button><button data-cmd="insertUnorderedList" title="فهرست">•</button><button data-cmd="link" title="پیوند">🔗</button></div>' +
  "</div></body></html>";

export class CanvasCtl {
  iframe: HTMLIFrameElement;
  cb: CanvasCallbacks;
  doc: Document | null = null;
  ready: Promise<void>;
  private cache = new Map<string, string>();
  private selected: string | null = null;
  private editing: HTMLElement | null = null;
  private editOriginal = "";
  private dragging = false;
  private preview = false;
  private raf = 0;
  private headerHtml = "";
  private footerHtml = "";
  private resizeObs: ResizeObserver | null = null;

  constructor(iframe: HTMLIFrameElement, cb: CanvasCallbacks) {
    this.iframe = iframe;
    this.cb = cb;
    this.ready = new Promise((resolve) => {
      const onload = () => {
        iframe.removeEventListener("load", onload);
        this.doc = iframe.contentDocument;
        this.wire();
        resolve();
      };
      iframe.addEventListener("load", onload);
      iframe.srcdoc = SKELETON;
    });
  }

  private $(id: string): HTMLElement {
    return (this.doc as Document).getElementById(id) as HTMLElement;
  }

  destroy(): void {
    this.resizeObs?.disconnect();
    cancelAnimationFrame(this.raf);
  }

  /* ─────────── محتوا ─────────── */
  update(p: CanvasPayload): void {
    if (!this.doc) return;
    const base = this.$("s-base");
    if (base.textContent !== p.base_css) base.textContent = p.base_css;
    const page = this.$("s-page");
    if (page.textContent !== p.page_css) page.textContent = p.page_css;
    if (p.header !== this.headerHtml) {
      this.$("nb-h").innerHTML = p.header;
      this.headerHtml = p.header;
    }
    if (p.footer !== this.footerHtml) {
      this.$("nb-f").innerHTML = p.footer;
      this.footerHtml = p.footer;
    }
    this.patchBlocks(p.parts);
    if (!p.parts.length) {
      this.$("page-body").innerHTML =
        '<div class="nb-drop-here" data-nb-ph="1" style="margin:48px auto;max-width:640px">صفحه خالی است. از فهرستِ بلوک‌ها یکی را این‌جا بکش.</div>';
      this.cache.clear();
    }
    this.reposition();
  }

  private patchBlocks(parts: CanvasPayload["parts"]): void {
    const main = this.$("page-body");
    const doc = this.doc as Document;
    const present = new Map<string, Element>();
    Array.from(main.children).forEach((el) => {
      const id = (el as HTMLElement).dataset.bid;
      if (id) present.set(id, el);
      else el.remove();
    });
    const wanted = new Set(parts.map((x) => x.id));
    present.forEach((el, id) => {
      if (!wanted.has(id)) {
        el.remove();
        this.cache.delete(id);
        present.delete(id);
      }
    });
    let prev: Element | null = null;
    for (const part of parts) {
      let el = present.get(part.id) ?? null;
      if (!el || this.cache.get(part.id) !== part.html) {
        const tpl = doc.createElement("template");
        tpl.innerHTML = part.html;
        const fresh = tpl.content.firstElementChild ?? doc.createElement("div");
        if (el) el.replaceWith(fresh);
        el = fresh;
        this.cache.set(part.id, part.html);
      }
      const should: Element | null = prev ? prev.nextElementSibling : main.firstElementChild;
      if (should !== el) main.insertBefore(el, should);
      prev = el;
    }
  }

  setPreview(on: boolean): void {
    this.preview = on;
    this.commitEdit();
    this.doc?.body.classList.toggle("nb-preview", on);
  }

  blockEl(id: string): HTMLElement | null {
    return this.doc?.querySelector(`[data-bid="${id}"]`) ?? null;
  }

  /* ─────────── انتخاب ─────────── */
  select(id: string | null, scroll = false): void {
    this.selected = id;
    this.reposition();
    if (id && scroll) this.blockEl(id)?.scrollIntoView({ block: "center" });
  }

  private rect(el: Element): { x: number; y: number; w: number; h: number } {
    const win = this.doc?.defaultView as Window;
    const box = (el as HTMLElement).dataset?.bid ? this.boxOf(el) : el.getBoundingClientRect();
    return { x: box.left + win.scrollX, y: box.top + win.scrollY, w: box.width, h: box.height };
  }

  private boxOf(el: Element): DOMRect {
    const r = el.getBoundingClientRect();
    if (r.width || r.height) return r;
    // عنصرِ بی‌جعبه
    const first = el.firstElementChild;
    return first ? first.getBoundingClientRect() : r;
  }

  reposition(): void {
    cancelAnimationFrame(this.raf);
    this.raf = requestAnimationFrame(() => this.positionNow());
  }

  private positionNow(): void {
    if (!this.doc) return;
    const sel = this.$("nb-sel");
    const bar = this.$("nb-bar");
    const el = this.selected ? this.blockEl(this.selected) : null;
    if (!el || this.preview) {
      sel.style.display = "none";
      bar.style.display = "none";
      return;
    }
    const r = this.rect(el);
    sel.style.cssText = `display:block;left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px`;
    bar.style.display = this.dragging ? "none" : "flex";
    (this.$("nb-bar-label") as HTMLElement).textContent = this.cb.labelOf(el.dataset.type ?? "");
    const win = this.doc.defaultView as Window;
    const bw = bar.offsetWidth;
    const bh = bar.offsetHeight;
    const docW = this.doc.documentElement.clientWidth;
    let top = r.y - bh - 6;
    if (top < win.scrollY + 2) top = Math.min(r.y + 6, r.y + r.h - bh - 6, win.scrollY + win.innerHeight - bh - 6);
    if (top < win.scrollY + 2) top = win.scrollY + 2;
    const left = Math.max(4, Math.min(r.x + r.w - bw, docW - bw - 4));
    bar.style.left = `${left}px`;
    bar.style.top = `${top}px`;
    if (this.editing && this.editing.dataset.nbMode === "rich") this.showRich();
    else this.$("nb-rich").style.display = "none";
  }

  private showHover(el: Element | null): void {
    const h = this.$("nb-hover");
    if (!el || this.dragging || this.preview || (el as HTMLElement).dataset.bid === this.selected) {
      h.style.display = "none";
      return;
    }
    const r = this.rect(el);
    h.style.cssText = `display:block;left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px`;
  }

  /* ─────────── رویدادها ─────────── */
  private wire(): void {
    const doc = this.doc as Document;
    const win = doc.defaultView as Window;
    doc.addEventListener("pointermove", (e) => {
      if (this.preview) return;
      const t = e.target as Element;
      if (t.closest?.("#nb-ui")) return;
      this.showHover(t.closest?.("[data-bid]") ?? null);
    });
    doc.addEventListener("pointerleave", () => this.showHover(null));
    doc.addEventListener("click", (e) => this.onClick(e), true);
    doc.addEventListener("submit", (e) => e.preventDefault(), true);
    doc.addEventListener("dragstart", (e) => e.preventDefault());
    doc.addEventListener("keydown", (e) => {
      if (this.editing) {
        const el = this.editing;
        if (e.key === "Escape") {
          el.innerHTML = this.editOriginal;
          this.stopEditing();
          e.preventDefault();
        } else if (e.key === "Enter" && el.dataset.nbMode === "plain") {
          e.preventDefault();
          this.commitEdit();
        }
        return;
      }
      this.cb.onKey(e);
    });
    doc.addEventListener("paste", (e) => {
      if (!this.editing) return;
      e.preventDefault();
      const text = e.clipboardData?.getData("text/plain") ?? "";
      doc.execCommand("insertText", false, text);
    });
    this.$("nb-bar").addEventListener("pointerdown", (e) => {
      const btn = (e.target as Element).closest("button[data-act]") as HTMLElement | null;
      if (!btn || !this.selected) return;
      e.preventDefault();
      e.stopPropagation();
      const act = btn.dataset.act as string;
      if (act === "move") {
        const box = this.iframe.getBoundingClientRect();
        this.cb.onStartMove(this.selected, box.left + e.clientX, box.top + e.clientY);
        return;
      }
      this.cb.onAction(act as BarAction, this.selected);
    });
    this.$("nb-rich").addEventListener("mousedown", (e) => {
      e.preventDefault();
      const btn = (e.target as Element).closest("button[data-cmd]") as HTMLElement | null;
      if (!btn) return;
      const cmd = btn.dataset.cmd as string;
      if (cmd === "link") {
        const url = win.parent.prompt("نشانیِ پیوند را بنویس (مثلاً https://example.com)");
        if (url) doc.execCommand("createLink", false, url);
      } else {
        doc.execCommand(cmd);
      }
    });
    win.addEventListener("scroll", () => this.reposition(), { passive: true });
    win.addEventListener("resize", () => this.reposition());
    this.resizeObs = new ResizeObserver(() => this.reposition());
    this.resizeObs.observe(doc.body);
    doc.addEventListener("load", () => this.reposition(), true);
  }

  private onClick(e: MouseEvent): void {
    if (this.preview) {
      const el = e.target as Element;
      if (!el.closest?.("summary")) e.preventDefault();
      return;
    }
    const t = e.target as HTMLElement;
    if (t.closest?.("#nb-ui")) return;
    if (t.closest?.("[contenteditable]")) return;
    e.preventDefault();
    e.stopPropagation();
    if (t.closest?.("#nb-h")) {
      this.commitEdit();
      this.cb.onChrome("header");
      return;
    }
    if (t.closest?.("#nb-f")) {
      this.commitEdit();
      this.cb.onChrome("footer");
      return;
    }
    const editable = t.closest?.("[data-nb-edit]") as HTMLElement | null;
    const block = t.closest?.("[data-bid]") as HTMLElement | null;
    this.commitEdit();
    if (!block) {
      this.cb.onSelect(null);
      return;
    }
    this.cb.onSelect(block.dataset.bid as string);
    if (editable && editable.closest("[data-bid]") === block) this.startEditing(editable, e.clientX, e.clientY);
  }

  /* ─────────── ویرایشِ متن ─────────── */
  private startEditing(el: HTMLElement, x: number, y: number): void {
    const doc = this.doc as Document;
    this.editing = el;
    this.editOriginal = el.innerHTML;
    const rich = el.dataset.nbMode === "rich";
    el.setAttribute("contenteditable", rich ? "true" : "plaintext-only");
    if (el.contentEditable !== (rich ? "true" : "plaintext-only")) el.setAttribute("contenteditable", "true");
    el.focus();
    const range = doc.caretRangeFromPoint?.(x, y);
    if (range) {
      const s = doc.getSelection();
      s?.removeAllRanges();
      s?.addRange(range);
    }
    el.addEventListener("blur", this.onBlur);
    this.reposition();
  }

  private onBlur = (): void => {
    // کلیک روی نوارِ قالب‌بندی نباید ویرایش را تمام کند (mousedown را متوقف کرده‌ایم)
    this.commitEdit();
  };

  private showRich(): void {
    const el = this.editing as HTMLElement;
    const rich = this.$("nb-rich");
    const r = this.rect(el);
    rich.style.display = "flex";
    rich.style.left = `${r.x}px`;
    rich.style.top = `${r.y + r.h + 6}px`;
  }

  private stopEditing(): void {
    const el = this.editing;
    if (!el) return;
    el.removeEventListener("blur", this.onBlur);
    el.removeAttribute("contenteditable");
    this.editing = null;
    this.$("nb-rich").style.display = "none";
  }

  commitEdit(): void {
    const el = this.editing;
    if (!el) return;
    const changed = el.innerHTML !== this.editOriginal;
    const rich = el.dataset.nbMode === "rich";
    const value = rich ? el.innerHTML : (el.innerText || "").replace(/\n+$/, "");
    const path = el.dataset.nbEdit as string;
    const block = el.closest("[data-bid]") as HTMLElement | null;
    this.stopEditing();
    if (changed && block?.dataset.bid) {
      this.cb.onText(block.dataset.bid, path, value);
    }
  }

  get isEditing(): boolean {
    return this.editing !== null;
  }

  /* ─────────── کشیدن ─────────── */
  setDragging(on: boolean): void {
    this.dragging = on;
    this.showHover(null);
    if (!on && this.doc) this.$("nb-line").style.display = "none";
    this.reposition();
  }

  /** نقطهٔ نسبت به iframe ⇐ جای افتادن. rootOnly: بخش‌های کاملِ سطحِ بالا. */
  hit(x: number, y: number, rootOnly: boolean, movingId: string | null): DropTarget | null {
    if (!this.doc) return null;
    const doc = this.doc;
    const main = this.$("page-body");
    const roots = () => Array.from(main.children).filter((c) => (c as HTMLElement).dataset.bid) as HTMLElement[];
    const rootTarget = (wrap: boolean): DropTarget => {
      const list = roots().filter((r) => r.dataset.bid !== movingId);
      let idx = 0;
      let lineY: number | null = null;
      for (const r of list) {
        const b = r.getBoundingClientRect();
        if (y > b.top + b.height / 2) {
          idx += 1;
          lineY = b.bottom;
        } else {
          lineY = lineY ?? b.top;
          break;
        }
      }
      // اندیس در فهرستِ واقعی (با خودِ بلوکِ در حالِ جابه‌جایی)
      const real = roots();
      let realIndex = idx;
      if (movingId) {
        const at = real.findIndex((r) => r.dataset.bid === movingId);
        if (at >= 0 && at < idx) realIndex = idx + 1;
        if (at >= 0 && at >= idx) realIndex = idx;
      }
      const mb = main.getBoundingClientRect();
      this.showLine(mb.left, lineY ?? mb.top, mb.width);
      return { parent: null, index: realIndex, wrap };
    };
    if (rootOnly) return rootTarget(false);
    let node = doc.elementFromPoint(x, y)?.closest("[data-bid]") as HTMLElement | null;
    if (movingId) {
      const mv = this.blockEl(movingId);
      if (node && mv && (node === mv || mv.contains(node))) node = (mv.parentElement?.closest("[data-bid]") as HTMLElement) ?? null;
    }
    const kidsOf = (c: HTMLElement) =>
      Array.from(c.querySelectorAll("[data-bid]")).filter(
        (k) => k.parentElement?.closest("[data-bid]") === c && (k as HTMLElement).dataset.bid !== movingId,
      ) as HTMLElement[];
    const realIndexIn = (c: HTMLElement, visibleIdx: number) => {
      if (!movingId) return visibleIdx;
      const all = Array.from(c.querySelectorAll("[data-bid]")).filter((k) => k.parentElement?.closest("[data-bid]") === c) as HTMLElement[];
      const at = all.findIndex((k) => k.dataset.bid === movingId);
      return at >= 0 && at < visibleIdx ? visibleIdx + 1 : visibleIdx;
    };
    while (node) {
      const type = node.dataset.type;
      if (type === "section" || type === "column") {
        const kids = kidsOf(node);
        let idx = 0;
        let lineY: number | null = null;
        for (const k of kids) {
          const b = k.getBoundingClientRect();
          if (y > b.top + b.height / 2) {
            idx += 1;
            lineY = b.bottom;
          } else {
            lineY = lineY ?? b.top;
            break;
          }
        }
        const box = (kids[0] ?? node).getBoundingClientRect();
        const nb = node.getBoundingClientRect();
        this.showLine(kids[0] ? box.left : nb.left + 8, lineY ?? nb.top + 8, kids[0] ? box.width : nb.width - 16);
        return { parent: node.dataset.bid as string, index: realIndexIn(node, idx), wrap: false };
      }
      node = (node.parentElement?.closest("[data-bid]") as HTMLElement) ?? null;
    }
    return rootTarget(true);
  }

  private showLine(left: number, top: number, width: number): void {
    const win = this.doc?.defaultView as Window;
    this.$("nb-line").style.cssText = `display:block;left:${left + win.scrollX}px;top:${top + win.scrollY - 2}px;width:${width}px`;
  }

  hideLine(): void {
    if (this.doc) this.$("nb-line").style.display = "none";
  }

  /** ⇒ آیا صفحه لغزید؟ */
  autoScroll(y: number): boolean {
    const win = this.doc?.defaultView;
    if (!win) return false;
    const before = win.scrollY;
    const h = win.innerHeight;
    if (y < 60) win.scrollBy(0, -18);
    else if (y > h - 60) win.scrollBy(0, 18);
    return win.scrollY !== before;
  }
}
