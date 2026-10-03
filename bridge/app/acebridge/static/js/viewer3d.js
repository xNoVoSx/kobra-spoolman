// 3D-Ansicht der Druckdatei mit WebGL2 - ohne Bibliothek. Daten: /api/print/geometry.bin (render.geometry_bin).
// Jede Druckbahn ist eine Instanz: "Volumen" zeichnet sie als schattierten Strang (Quader), "Linien" als Linie.
// Was schon gedruckt ist (Instanz < done), welche Schichten sichtbar sind und die Farben entscheidet der Shader -
// laeuft der Druck weiter, aendert sich nur eine Zahl, nichts wird neu hochgeladen.

const LINE_W = 0.45;           // Strangbreite in mm (Duese 0,4)
const GHOST = [0.30, 0.33, 0.38];

/** Was kann dieses Geraet? volume | lines | image */
export function capability() {
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2");
    if (!gl) return "image";
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    const r = String(dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)).toLowerCase();
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    if (/swiftshader|llvmpipe|software|softpipe/.test(r)) return "image";       // keine echte Grafikkarte
    const mem = navigator.deviceMemory || 8;
    const touch = matchMedia("(pointer: coarse)").matches;
    return touch || mem < 4 ? "lines" : "volume";
  } catch { return "image"; }
}

const QUALITY_KEY = "kobra.render3d";
/** Einstellung dieses Geraets: auto | volume | lines | image (App: ?q= in der Adresse). */
export function quality() {
  const q = new URLSearchParams(location.search).get("q") || new URLSearchParams(location.hash.split("?")[1] || "").get("q");
  let v = q;
  if (!v) { try { v = localStorage.getItem(QUALITY_KEY); } catch { /* egal */ } }
  return ["volume", "lines", "image"].includes(v) ? v : "auto";
}
export function setQuality(v) { try { localStorage.setItem(QUALITY_KEY, v); } catch { /* egal */ } }
export const effectiveQuality = () => (quality() === "auto" ? capability() : quality());

/** Binaerformat der Bridge lesen. */
export function parseGeometry(buf) {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== "KSG1") throw new Error("Unbekanntes Format der Druckbahnen");
  const n = dv.getUint32(8, true), nl = dv.getUint32(12, true), step = dv.getUint32(16, true);
  const bed = dv.getFloat32(20, true), zmax = dv.getFloat32(24, true);
  const layers = new Float32Array(buf, 28, nl);
  const base = 28 + 4 * nl;
  const col = (k) => new Uint16Array(buf, base + 2 * n * k, n);
  return { n, step, bed, zmax, layers, cols: buf.slice(base, base + 12 * n), tools: new Uint8Array(buf, base + 12 * n, n),
    x1: col(2), y1: col(3), z: col(4), layer: col(5) };
}

// ------------------------------------------------------------ Mathe (Spalten-Matrizen wie WebGL)
function perspective(fov, aspect, near, far) {
  const f = 1 / Math.tan(fov / 2), nf = 1 / (near - far);
  return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
}
function lookAt(e, c, up) {
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const norm = (v) => { const l = Math.hypot(...v) || 1; return v.map((x) => x / l); };
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const z = norm(sub(e, c)), x = norm(cross(up, z)), y = cross(z, x);
  return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, e), -dot(y, e), -dot(z, e), 1];
}
function mul(a, b) {
  const o = new Array(16).fill(0);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
  return o;
}

// ------------------------------------------------------------ Shader
const VS = `#version 300 es
precision highp float;
in float a_x0, a_y0, a_x1, a_y1, a_z, a_layer, a_tool;   // je Bahn (Instanz)
in vec3 a_corner;                                         // t (0..1 entlang), Seite (-1/1), oben (0/1)
in vec3 a_normal;                                         // entlang, seitlich, oben
uniform mat4 u_mvp;
uniform float u_bed, u_zmax, u_h, u_w, u_maxLayer, u_single, u_ghost;
uniform int u_done;
uniform vec3 u_colors[16];
uniform vec3 u_ghostColor;
uniform bool u_volume;
out vec3 v_color;
out float v_light;
void main() {
  bool done = gl_InstanceID < u_done;
  if (a_layer > u_maxLayer || (u_single > 0.5 && a_layer != u_maxLayer) || (!done && u_ghost < 0.5)) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return;        // ausserhalb: nicht zeichnen
  }
  vec2 p0 = vec2(a_x0, a_y0) * u_bed, p1 = vec2(a_x1, a_y1) * u_bed;
  float z = a_z * u_zmax;
  vec2 d = p1 - p0; float len = length(d);
  vec2 dir = len > 1e-5 ? d / len : vec2(1.0, 0.0);
  vec2 perp = vec2(-dir.y, dir.x);
  vec3 pos;
  vec3 n = vec3(0.0, 0.0, 1.0);
  if (u_volume) {
    vec2 along = mix(p0, p1, a_corner.x) + dir * (a_corner.x * 2.0 - 1.0) * u_w * 0.5;
    vec2 xy = along + perp * a_corner.y * u_w * 0.5;
    pos = vec3(xy, z - u_h + a_corner.z * u_h);
    n = normalize(vec3(dir * a_normal.x + perp * a_normal.y, a_normal.z));
  } else {
    pos = vec3(mix(p0, p1, a_corner.x), z);
  }
  gl_Position = u_mvp * vec4(pos, 1.0);
  vec3 c = done ? u_colors[int(a_tool) & 15] : u_ghostColor;
  if (done && a_layer == u_maxLayer && u_single < 0.5) c = mix(c, vec3(1.0), 0.18);   // aktuelle Schicht heller
  v_color = c;
  vec3 L = normalize(vec3(-0.45, -0.6, 0.75));
  v_light = u_volume ? 0.42 + 0.58 * max(dot(n, L), 0.0) : 0.55 + 0.45 * clamp(z / max(u_zmax, 1.0), 0.0, 1.0);
}`;
const FS = `#version 300 es
precision mediump float;
in vec3 v_color; in float v_light;
out vec4 o;
void main() { o = vec4(v_color * v_light, 1.0); }`;
const VS_FLAT = `#version 300 es
in vec3 a_pos; uniform mat4 u_mvp; uniform float u_size;
void main() { gl_Position = u_mvp * vec4(a_pos, 1.0); gl_PointSize = u_size; }`;
const FS_FLAT = `#version 300 es
precision mediump float; uniform vec4 u_color; out vec4 o; void main() { o = u_color; }`;

function program(gl, vs, fs) {
  const mk = (type, src) => {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  };
  const p = gl.createProgram();
  gl.attachShader(p, mk(gl.VERTEX_SHADER, vs)); gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  return p;
}

// Quader: 6 Flaechen x 4 Ecken; (t, Seite, oben) und Normale (entlang, seitlich, oben)
function boxMesh() {
  const v = [], idx = [];
  const face = (corners, normal) => {
    const b = v.length / 6;
    corners.forEach((c) => v.push(...c, ...normal));
    idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
  };
  face([[0, -1, 1], [1, -1, 1], [1, 1, 1], [0, 1, 1]], [0, 0, 1]);     // oben
  face([[0, -1, 0], [0, 1, 0], [1, 1, 0], [1, -1, 0]], [0, 0, -1]);    // unten
  face([[0, 1, 0], [0, 1, 1], [1, 1, 1], [1, 1, 0]], [0, 1, 0]);       // Seite links
  face([[0, -1, 0], [1, -1, 0], [1, -1, 1], [0, -1, 1]], [0, -1, 0]);  // Seite rechts
  face([[1, -1, 0], [1, 1, 0], [1, 1, 1], [1, -1, 1]], [1, 0, 0]);     // Ende
  face([[0, -1, 0], [0, -1, 1], [0, 1, 1], [0, 1, 0]], [-1, 0, 0]);    // Anfang
  return { v: new Float32Array(v), idx: new Uint16Array(idx) };
}

const hexRgb = (h) => { const s = String(h || "").replace("#", "").padEnd(6, "8"); return [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16) / 255); };

export class PrintView {
  constructor(canvas, onLost) {
    this.canvas = canvas;
    const gl = canvas.getContext("webgl2", { antialias: true, alpha: false, preserveDrawingBuffer: false });
    if (!gl) throw new Error("WebGL2 nicht verfügbar");
    this.gl = gl;
    this.prog = program(gl, VS, FS);
    this.flat = program(gl, VS_FLAT, FS_FLAT);
    this.mode = "volume";
    this.geo = null;
    this.done = 0;
    this.maxLayer = 0;
    this.single = false;
    this.ghost = true;
    this.colors = Array(16).fill([0.8, 0.8, 0.8]);
    this.cam = { yaw: -0.75, pitch: 0.55, dist: 420, target: [125, 125, 10] };
    this.dirty = true;
    canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); this.lost = true; onLost?.(); });
    this._controls();
    this._ro = new ResizeObserver(() => this.redraw());
    this._ro.observe(canvas);
    this._loop = () => { if (this.dirty && !this.lost) { this.dirty = false; this._draw(); } this._raf = requestAnimationFrame(this._loop); };
    this._raf = requestAnimationFrame(this._loop);
  }

  redraw() { this.dirty = true; }

  load(geo) {
    const gl = this.gl;
    this.geo = geo;
    if (this.vao) gl.deleteVertexArray(this.vao);
    this.buffers?.forEach((b) => gl.deleteBuffer(b));
    const inst = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, inst);
    gl.bufferData(gl.ARRAY_BUFFER, geo.cols, gl.STATIC_DRAW);
    const tools = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, tools);
    gl.bufferData(gl.ARRAY_BUFFER, geo.tools, gl.STATIC_DRAW);
    const box = boxMesh();
    const mesh = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh);
    gl.bufferData(gl.ARRAY_BUFFER, box.v, gl.STATIC_DRAW);
    const ibo = gl.createBuffer();
    const line = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, line);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1]), gl.STATIC_DRAW);
    this.buffers = [inst, tools, mesh, ibo, line];
    this.boxCount = box.idx.length;
    const p = this.prog;
    const vaoFor = (meshBuf, stride, withIndex) => {
      const vao = gl.createVertexArray();
      gl.bindVertexArray(vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, inst);
      ["a_x0", "a_y0", "a_x1", "a_y1", "a_z", "a_layer"].forEach((name, k) => {
        const loc = gl.getAttribLocation(p, name);
        if (loc < 0) return;
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, 1, gl.UNSIGNED_SHORT, name !== "a_layer", 0, 2 * geo.n * k);
        gl.vertexAttribDivisor(loc, 1);
      });
      const tl = gl.getAttribLocation(p, "a_tool");
      gl.bindBuffer(gl.ARRAY_BUFFER, tools);
      gl.enableVertexAttribArray(tl);
      gl.vertexAttribPointer(tl, 1, gl.UNSIGNED_BYTE, false, 0, 0);
      gl.vertexAttribDivisor(tl, 1);
      gl.bindBuffer(gl.ARRAY_BUFFER, meshBuf);
      const cl = gl.getAttribLocation(p, "a_corner"), nl = gl.getAttribLocation(p, "a_normal");
      gl.enableVertexAttribArray(cl);
      gl.vertexAttribPointer(cl, 3, gl.FLOAT, false, stride, 0);
      if (nl >= 0) { gl.enableVertexAttribArray(nl); gl.vertexAttribPointer(nl, 3, gl.FLOAT, false, stride, 12); }
      if (withIndex) { gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, box.idx, gl.STATIC_DRAW); }
      gl.bindVertexArray(null);
      return vao;
    };
    this.vaoBox = vaoFor(mesh, 24, true);
    this.vaoLine = vaoFor(line, 24, false);
    // Schichthoehe: haeufigster Abstand der Schichten
    const L = geo.layers, gaps = [];
    for (let i = 1; i < L.length; i++) gaps.push(Math.round((L[i] - L[i - 1]) * 100) / 100);
    gaps.sort((a, b) => a - b);
    this.layerH = gaps.length ? Math.max(0.05, gaps[gaps.length >> 1]) : 0.2;
    this.maxLayer = L.length - 1;
    this.cam.target = [geo.bed / 2, geo.bed / 2, Math.min(geo.zmax, 60) / 2];
    this._fit();
    this.redraw();
  }

  /** Kamera auf das Druckteil ausrichten (Mitte und Groesse aus den Bahnen). */
  _fit() {
    // Mitte und Groesse aus 2.-98. Perzentil der Bahnen - Spuellinie und Abstreifer am Rand zaehlen nicht
    const g = this.geo; if (!g || !g.n) return;
    const s = Math.max(1, Math.floor(g.n / 20000)), q = g.bed / 65535, xs = [], ys = [];
    for (let i = 0; i < g.n; i += s) { xs.push(g.x1[i] * q); ys.push(g.y1[i] * q); }
    xs.sort((a, b) => a - b); ys.sort((a, b) => a - b);
    const pc = (a, f) => a[Math.min(a.length - 1, Math.floor(a.length * f))];
    const x0 = pc(xs, 0.02), x1 = pc(xs, 0.98), y0 = pc(ys, 0.02), y1 = pc(ys, 0.98);
    const size = Math.max(x1 - x0, y1 - y0, g.zmax, 20);
    this.cam.target = [(x0 + x1) / 2, (y0 + y1) / 2, g.zmax / 2];
    this.cam.dist = size * 1.9;
    this.home = { ...this.cam, target: [...this.cam.target] };
  }

  view(kind) {
    const h = this.home || this.cam;
    this.cam = { ...h, target: [...h.target], ...(kind === "top" ? { yaw: 0, pitch: 1.55 } : kind === "front" ? { yaw: 0, pitch: 0.05 } : { yaw: -0.75, pitch: 0.55 }) };
    this.redraw();
  }

  set(opts) { Object.assign(this, opts); this.redraw(); }
  setColors(hexes) { this.colors = Array.from({ length: 16 }, (_, i) => hexRgb(hexes?.[i] || "cccccc")); this.redraw(); }

  _matrix() {
    const c = this.canvas, aspect = c.width / Math.max(1, c.height);
    const { yaw, pitch, dist, target } = this.cam;
    const eye = [target[0] + dist * Math.cos(pitch) * Math.sin(yaw), target[1] - dist * Math.cos(pitch) * Math.cos(yaw), target[2] + dist * Math.sin(pitch)];
    const up = pitch > 1.5 ? [Math.sin(yaw), Math.cos(yaw), 0] : [0, 0, 1];
    return mul(perspective(0.7, aspect, Math.max(0.5, dist / 200), dist * 6 + 600), lookAt(eye, target, up));
  }

  _draw() {
    const gl = this.gl, c = this.canvas;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(c.clientWidth * dpr)), h = Math.max(1, Math.round(c.clientHeight * dpr));
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    gl.viewport(0, 0, w, h);
    gl.clearColor(0.043, 0.047, 0.055, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    const mvp = this._matrix();
    this._bed(mvp);
    const g = this.geo;
    if (!g || !g.n) return;
    const p = this.prog;
    gl.useProgram(p);
    const u = (n) => gl.getUniformLocation(p, n);
    gl.uniformMatrix4fv(u("u_mvp"), false, mvp);
    gl.uniform1f(u("u_bed"), g.bed);
    gl.uniform1f(u("u_zmax"), g.zmax);
    gl.uniform1f(u("u_h"), this.layerH);
    gl.uniform1f(u("u_w"), LINE_W);
    gl.uniform1f(u("u_maxLayer"), this.maxLayer);
    gl.uniform1f(u("u_single"), this.single ? 1 : 0);
    gl.uniform1f(u("u_ghost"), this.ghost ? 1 : 0);
    gl.uniform1i(u("u_done"), this.done);
    gl.uniform3fv(u("u_colors"), this.colors.flat());
    gl.uniform3fv(u("u_ghostColor"), GHOST);
    const volume = this.mode === "volume";
    gl.uniform1i(u("u_volume"), volume ? 1 : 0);
    if (volume) {
      gl.bindVertexArray(this.vaoBox);
      gl.drawElementsInstanced(gl.TRIANGLES, this.boxCount, gl.UNSIGNED_SHORT, 0, g.n);
    } else {
      gl.bindVertexArray(this.vaoLine);
      gl.drawArraysInstanced(gl.LINES, 0, 2, g.n);
    }
    gl.bindVertexArray(null);
    this._nozzle(mvp);
  }

  _flat(mvp, data, mode, color, size = 1) {
    const gl = this.gl;
    gl.useProgram(this.flat);
    if (!this._flatBuf) this._flatBuf = gl.createBuffer();
    if (!this._flatVao) {
      this._flatVao = gl.createVertexArray();
      gl.bindVertexArray(this._flatVao);
      gl.bindBuffer(gl.ARRAY_BUFFER, this._flatBuf);
      const loc = gl.getAttribLocation(this.flat, "a_pos");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 3, gl.FLOAT, false, 0, 0);
    }
    gl.bindVertexArray(this._flatVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this._flatBuf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.DYNAMIC_DRAW);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.flat, "u_mvp"), false, mvp);
    gl.uniform4fv(gl.getUniformLocation(this.flat, "u_color"), color);
    gl.uniform1f(gl.getUniformLocation(this.flat, "u_size"), size);
    gl.drawArrays(mode, 0, data.length / 3);
    gl.bindVertexArray(null);
  }

  _bed(mvp) {
    const b = this.geo?.bed || 250, d = [];
    for (let i = 0; i <= b; i += 25) { d.push(i, 0, 0, i, b, 0, 0, i, 0, b, i, 0); }
    this._flat(mvp, d, this.gl.LINES, [0.16, 0.18, 0.21, 1]);
    this._flat(mvp, [0, 0, 0, b, 0, 0, b, 0, 0, b, b, 0, b, b, 0, 0, b, 0, 0, b, 0, 0, 0, 0], this.gl.LINES, [0.35, 0.38, 0.44, 1]);
  }

  _nozzle(mvp) {
    const g = this.geo, i = Math.min(this.done, g.n) - 1;
    if (i < 0 || this.single || this.done >= g.n) return;
    const q = g.bed / 65535;
    const p = [g.x1[i] * q, g.y1[i] * q, g.z[i] / 65535 * g.zmax + 0.3];
    this.gl.disable(this.gl.DEPTH_TEST);
    this._flat(mvp, p, this.gl.POINTS, [1, 0.85, 0.3, 1], 9 * Math.min(window.devicePixelRatio || 1, 2));
    this.gl.enable(this.gl.DEPTH_TEST);
  }

  _controls() {
    const c = this.canvas, pts = new Map();
    let last = null, pinch = null;
    c.style.touchAction = "none";
    c.addEventListener("contextmenu", (e) => e.preventDefault());
    c.addEventListener("pointerdown", (e) => { c.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]); last = [e.clientX, e.clientY, e.button, e.shiftKey]; pinch = null; });
    c.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      if (pts.size === 2) {
        const [a, b] = [...pts.values()], dist = Math.hypot(a[0] - b[0], a[1] - b[1]), mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
        if (pinch) { this.cam.dist = Math.min(3000, Math.max(5, this.cam.dist * pinch.d / dist)); this._pan(mid[0] - pinch.m[0], mid[1] - pinch.m[1]); }
        pinch = { d: dist, m: mid };
      } else if (last) {
        const dx = e.clientX - last[0], dy = e.clientY - last[1];
        if (last[2] === 2 || last[2] === 1 || last[3]) this._pan(dx, dy);
        else { this.cam.yaw -= dx * 0.008; this.cam.pitch = Math.min(1.55, Math.max(-0.2, this.cam.pitch + dy * 0.008)); }
        last = [e.clientX, e.clientY, last[2], last[3]];
      }
      this.redraw();
    });
    const up = (e) => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; if (!pts.size) last = null; };
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
    c.addEventListener("wheel", (e) => { e.preventDefault(); this.cam.dist = Math.min(3000, Math.max(5, this.cam.dist * Math.exp(e.deltaY * 0.0012))); this.redraw(); }, { passive: false });
    c.addEventListener("dblclick", () => this.view("iso"));
  }

  _pan(dx, dy) {
    const k = this.cam.dist * 0.0016, { yaw } = this.cam;
    const right = [Math.cos(yaw), Math.sin(yaw)], fwd = [-Math.sin(yaw), Math.cos(yaw)];
    const t = this.cam.target;
    this.cam.target = [t[0] - (right[0] * dx - fwd[0] * dy) * k, t[1] - (right[1] * dx - fwd[1] * dy) * k, t[2]];
  }

  dispose() {
    cancelAnimationFrame(this._raf);
    this._ro.disconnect();
    this.gl.getExtension("WEBGL_lose_context")?.loseContext();
  }
}
