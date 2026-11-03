/**
 * ابزارِ کوچکِ WebGL2 برای موتورِ ادیتور: برنامه، بافت، FBO و یک «پاس» تمام‌صفحه.
 * قرارداد: همهٔ بافت‌ها در «فضای t» اند: t=(0,0) بالا-چپِ تصویر. پاس‌های تمام‌صفحه vUv = t را می‌دهند؛ readPixels
 * سطرِ اول را بالا می‌دهد (بی وارونگی).
 */
export type Tex = {
  t: WebGLTexture;
  w: number;
  h: number;
  fbo: WebGLFramebuffer | null;
  float: boolean;
  mips?: boolean;
};

export type UValue = number | number[] | Float32Array | Tex;

type Prog = { p: WebGLProgram; loc: Map<string, WebGLUniformLocation | null> };

export const VS = `#version 300 es
in vec2 aPos; out vec2 vUv;
void main(){ vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }`;

export class GLCtx {
  gl: WebGL2RenderingContext;
  floatOK = false;
  fboErrors = 0;
  private vao: WebGLVertexArrayObject;
  private progs = new Map<string, Prog>();
  private pool = new Map<string, Tex[]>();
  private owned = new Set<Tex>();

  constructor(canvas: HTMLCanvasElement) {
    const gl = canvas.getContext("webgl2", { alpha: false, antialias: false, preserveDrawingBuffer: true, premultipliedAlpha: false, powerPreference: "high-performance" });
    if (!gl) throw new Error("WebGL2 در این مرورگر نیست.");
    this.gl = gl;
    this.floatOK = !!gl.getExtension("EXT_color_buffer_float");
    gl.getExtension("EXT_color_buffer_half_float");
    gl.getExtension("OES_texture_float_linear");
    const vao = gl.createVertexArray()!;
    gl.bindVertexArray(vao);
    const buf = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    this.vao = vao;
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  }

  get lost() {
    return this.gl.isContextLost();
  }

  program(name: string, fs: string): Prog {
    let pr = this.progs.get(name);
    if (pr) return pr;
    const gl = this.gl;
    const mk = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        const log = gl.getShaderInfoLog(s);
        gl.deleteShader(s);
        throw new Error(`shader ${name}: ${log}`);
      }
      return s;
    };
    const p = gl.createProgram()!;
    gl.attachShader(p, mk(gl.VERTEX_SHADER, VS));
    gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fs));
    gl.bindAttribLocation(p, 0, "aPos");
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(`link ${name}: ${gl.getProgramInfoLog(p)}`);
    pr = { p, loc: new Map() };
    this.progs.set(name, pr);
    return pr;
  }

  /** بافتِ خالی (float16 برای میانی‌ها، RGBA8 برای بقیه) */
  create(w: number, h: number, float = true, linear = true): Tex {
    const gl = this.gl;
    w = Math.max(1, Math.round(w));
    h = Math.max(1, Math.round(h));
    const useFloat = float && this.floatOK;
    const t = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, t);
    if (useFloat) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, w, h, 0, gl.RGBA, gl.HALF_FLOAT, null);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, linear ? gl.LINEAR : gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, linear ? gl.LINEAR : gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const fbo = gl.createFramebuffer()!;
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0);
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) this.fboErrors++;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    const tex: Tex = { t, w, h, fbo, float: useFloat };
    this.owned.add(tex);
    return tex;
  }

  /** از قاب‌های بیرونی (تصویر/بوم/ImageData). premult=true ⇒ آلفا ضرب‌شده (برای لایه‌های با لبهٔ نرم) */
  upload(src: TexImageSource | ImageData, opts: { premult?: boolean; mips?: boolean; linear?: boolean } = {}): Tex {
    const gl = this.gl;
    const w = (src as { width: number }).width;
    const h = (src as { height: number }).height;
    const t = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, !!opts.premult);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, src as TexImageSource);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    const mips = !!opts.mips && w > 1 && h > 1;
    if (mips) gl.generateMipmap(gl.TEXTURE_2D);
    const lin = opts.linear !== false;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mips ? gl.LINEAR_MIPMAP_LINEAR : lin ? gl.LINEAR : gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, lin ? gl.LINEAR : gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const tex: Tex = { t, w, h, fbo: null, float: false, mips };
    this.owned.add(tex);
    return tex;
  }

  /** به‌روزرسانیِ بافتِ آپلودشده با محتوای تازه (هم‌اندازه) */
  reupload(tex: Tex, src: TexImageSource | ImageData, premult = false): void {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, tex.t);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, premult);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, src as TexImageSource);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    if (tex.mips) gl.generateMipmap(gl.TEXTURE_2D);
  }

  /** بافتِ ۱×N از بایت‌ها (LUT) */
  fromBytes(data: Uint8Array, w: number, h: number): Tex {
    const gl = this.gl;
    const t = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const tex: Tex = { t, w, h, fbo: null, float: false };
    this.owned.add(tex);
    return tex;
  }

  /** بافتِ RG32F (w×h، بی فیلتر؛ فقط با texelFetch خوانده می‌شود) — برای نقشهٔ مایع‌سازی. data: w·h·2 عدد، سطرِ اول بالا */
  fromFloatRG(data: Float32Array, w: number, h: number): Tex {
    const gl = this.gl;
    const t = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RG32F, w, h, 0, gl.RG, gl.FLOAT, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const tex: Tex = { t, w, h, fbo: null, float: true };
    this.owned.add(tex);
    return tex;
  }

  /** محتوای تازه برای بافتِ fromFloatRG (هم‌اندازه) */
  reuploadFloatRG(tex: Tex, data: Float32Array): void {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, tex.t);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, tex.w, tex.h, gl.RG, gl.FLOAT, data);
  }

  /** از استخر: بافتِ میانیِ هم‌اندازه. با release برمی‌گردد. */
  take(w: number, h: number, float = true): Tex {
    w = Math.max(1, Math.round(w));
    h = Math.max(1, Math.round(h));
    const key = `${w}x${h}${float && this.floatOK ? "f" : "b"}`;
    const list = this.pool.get(key);
    if (list && list.length) return list.pop()!;
    return this.create(w, h, float);
  }

  release(...texs: (Tex | null | undefined)[]): void {
    for (const t of texs) {
      if (!t || !t.fbo) continue;
      const key = `${t.w}x${t.h}${t.float ? "f" : "b"}`;
      const list = this.pool.get(key) ?? [];
      if (list.length < 6) list.push(t);
      else this.destroy(t);
      this.pool.set(key, list);
    }
  }

  destroy(t: Tex | null | undefined): void {
    if (!t || !this.owned.has(t)) return;
    const gl = this.gl;
    gl.deleteTexture(t.t);
    if (t.fbo) gl.deleteFramebuffer(t.fbo);
    this.owned.delete(t);
  }

  clearPool(): void {
    for (const list of this.pool.values()) list.forEach((t) => this.destroy(t));
    this.pool.clear();
  }

  clear(target: Tex, r = 0, g = 0, b = 0, a = 0): void {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
    gl.viewport(0, 0, target.w, target.h);
    gl.clearColor(r, g, b, a);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  /** یک پاسِ تمام‌صفحه: target=null ⇒ بومِ صفحه */
  pass(name: string, fs: string, target: Tex | null, u: Record<string, UValue>, size?: [number, number]): void {
    const gl = this.gl;
    const pr = this.program(name, fs);
    gl.useProgram(pr.p);
    gl.bindVertexArray(this.vao);
    gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fbo : null);
    const [vw, vh] = target ? [target.w, target.h] : (size ?? [gl.drawingBufferWidth, gl.drawingBufferHeight]);
    gl.viewport(0, 0, vw, vh);
    gl.disable(gl.BLEND);
    let unit = 0;
    for (const key of Object.keys(u)) {
      let loc = pr.loc.get(key);
      if (loc === undefined) {
        loc = gl.getUniformLocation(pr.p, key.endsWith("[]") ? key.slice(0, -2) + "[0]" : key);
        pr.loc.set(key, loc);
      }
      if (!loc) continue;
      const v = u[key];
      if (typeof v === "number") gl.uniform1f(loc, v);
      else if (v instanceof Float32Array) gl.uniform1fv(loc, v);
      else if (Array.isArray(v)) {
        if (v.length === 2) gl.uniform2fv(loc, v);
        else if (v.length === 3) gl.uniform3fv(loc, v);
        else if (v.length === 4) gl.uniform4fv(loc, v);
        else if (v.length === 9) gl.uniformMatrix3fv(loc, true, v);
      } else {
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, (v as Tex).t);
        gl.uniform1i(loc, unit);
        unit++;
      }
    }
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  mips(t: Tex): void {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, t.t);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    t.mips = true;
  }

  /** RGBA8 از یک بافت (سطر اول = بالای تصویر) */
  read(t: Tex): Uint8ClampedArray {
    const gl = this.gl;
    const out = new Uint8Array(t.w * t.h * 4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, t.fbo);
    gl.readPixels(0, 0, t.w, t.h, gl.RGBA, gl.UNSIGNED_BYTE, out);
    return new Uint8ClampedArray(out.buffer);
  }
}
