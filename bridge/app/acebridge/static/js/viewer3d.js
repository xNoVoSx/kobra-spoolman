// 3D-Ansicht der Druckdatei mit WebGL2 - ohne Bibliothek. Daten: /api/print/geometry.bin (render.geometry_bin).
// Aussehen wie Orcas Vorschau (eigene Umsetzung, kein Orca-Code): grauer Hintergrund, Druckplatte mit 10-mm-Raster,
// jede Druckbahn als Strang mit gerundetem Querschnitt (echte Breite und Schichthoehe) und spitzen Enden, Licht von oben
// und vorne mit leichtem Glanz. "Linien" zeichnet jede Bahn nur als Linie (schwache Geraete).
// Was schon gedruckt ist (Instanz < done), welche Schichten sichtbar sind und die Farben entscheidet der Shader -
// laeuft der Druck weiter, aendert sich nur eine Zahl, nichts wird neu hochgeladen.

const BG = [0.329, 0.329, 0.353];          // wie Orca im dunklen Design
const PLATE = [0.255, 0.255, 0.283];
const PLATE_EDGE = [0.2, 0.2, 0.22];
const MARGIN = 5;                           // Platte ragt ueber den Druckbereich hinaus (mm)
const THICK = 4;                            // Plattendicke (mm)
const RADIUS = 8;                           // Eckenradius der Platte (mm)
const GHOST_ALPHA = 0.2;                    // Rest als Strang (vorderste Flaeche einmal geblendet)
const GHOST_ALPHA_LINES = 0.05;             // Rest als Linien: liegen viele uebereinander, daher viel schwaecher

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

/** Binaerformat der Bridge lesen (Version 1 ohne, Version 2 mit Strangbreite). */
export function parseGeometry(buf) {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== "KSG1") throw new Error("Unbekanntes Format der Druckbahnen");
  const ver = dv.getUint16(4, true);
  const n = dv.getUint32(8, true), nl = dv.getUint32(12, true), step = dv.getUint32(16, true);
  const bed = dv.getFloat32(20, true), zmax = dv.getFloat32(24, true);
  const layers = new Float32Array(buf, 28, nl);
  const base = 28 + 4 * nl;
  const col = (k) => new Uint16Array(buf, base + 2 * n * k, n);
  const widths = ver >= 2 ? new Uint8Array(buf, base + 13 * n, n) : new Uint8Array(n).fill(45);
  return { n, step, bed, zmax, layers, cols: buf.slice(base, base + 12 * n), tools: new Uint8Array(buf, base + 12 * n, n),
    widths, x1: col(2), y1: col(3), z: col(4), layer: col(5) };
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

// ------------------------------------------------------------ Shader
// Licht im Kameraraum: eines von oben links, eines von vorne, Grundhelligkeit und Glanz - kraeftige Filamentfarben.
const LIGHT = `
const vec3 L_TOP = vec3(-0.4575, 0.4575, 0.7625);
const vec3 L_FRONT = vec3(0.6985, 0.1397, 0.6985);
vec3 shade(vec3 base, vec3 n, vec3 eyePos) {
  n = normalize(n);
  if (dot(n, eyePos) > 0.0) n = -n;                       // Rueckseite von hinten gesehen
  float diff = 0.48 * max(dot(n, L_TOP), 0.0) + 0.18 * max(dot(n, L_FRONT), 0.0);
  float spec = 0.15 * pow(max(dot(reflect(-L_TOP, n), normalize(-eyePos)), 0.0), 20.0);
  return base * (0.34 + 0.15 + diff) + vec3(spec);
}`;

const VS = `#version 300 es
precision highp float;
in float a_x0, a_y0, a_x1, a_y1, a_z, a_layer, a_tool, a_width, a_height;   // je Bahn (Instanz)
in vec4 a_v;                                   // t (0..1 entlang), Seite (-1..1), oben (-1..1), Spitze (-1/0/1)
in vec3 a_n;                                   // Normale: entlang, seitlich, oben
uniform mat4 u_view, u_proj;
uniform float u_bed, u_zmax, u_maxLayer, u_single, u_ghostAlpha;
uniform int u_done, u_pass;                    // Durchgang 0: Gedrucktes, 1: Rest (blass)
uniform vec3 u_colors[16];
uniform bool u_volume;
out vec3 v_color; out vec3 v_n; out vec3 v_pos; out float v_alpha; out float v_flat;
void main() {
  bool done = gl_InstanceID < u_done;
  if (a_layer > u_maxLayer || (u_single > 0.5 && a_layer != u_maxLayer) || (u_pass == 0) != done) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return;        // gehoert nicht in diesen Durchgang
  }
  vec2 p0 = vec2(a_x0, a_y0) * u_bed, p1 = vec2(a_x1, a_y1) * u_bed;
  float z = a_z * u_zmax;
  vec2 d = p1 - p0; float len = length(d);
  vec2 dir = len > 1e-5 ? d / len : vec2(1.0, 0.0);
  vec2 perp = vec2(-dir.y, dir.x);
  vec3 pos; vec3 n = vec3(0.0, 0.0, 1.0);
  if (u_volume) {
    float h = max(a_height / 100.0, 0.05), w = max(a_width / 100.0, h);
    vec2 xy = mix(p0, p1, a_v.x) + dir * a_v.w * w * 0.5 + perp * a_v.y * w * 0.5;
    pos = vec3(xy, z - h * 0.5 + a_v.z * h * 0.5);
    n = vec3(dir * a_n.x + perp * a_n.y, a_n.z);
  } else {
    pos = vec3(mix(p0, p1, a_v.x), z);
  }
  vec4 eye = u_view * vec4(pos, 1.0);
  gl_Position = u_proj * eye;
  vec3 c = u_colors[int(a_tool) & 15];
  v_color = u_pass == 0 ? c : mix(c, vec3(0.85), 0.45);
  v_alpha = u_pass == 0 ? 1.0 : u_ghostAlpha;
  v_n = mat3(u_view) * n;
  v_pos = eye.xyz;
  v_flat = u_volume ? 0.0 : 0.55 + 0.45 * clamp(z / max(u_zmax, 1.0), 0.0, 1.0);
}`;
const FS = `#version 300 es
precision mediump float;
in vec3 v_color; in vec3 v_n; in vec3 v_pos; in float v_alpha; in float v_flat;
out vec4 o;
${LIGHT}
void main() {
  vec3 c = v_flat > 0.0 ? v_color * v_flat : shade(v_color, v_n, v_pos);
  o = vec4(c, v_alpha);
}`;

// Platte, Duese: Dreiecke mit Normale, Farbe oder Textur
const VS_MESH = `#version 300 es
in vec3 a_pos; in vec3 a_n; in vec2 a_uv;
uniform mat4 u_view, u_proj; uniform vec3 u_offset;
out vec3 v_n; out vec3 v_pos; out vec2 v_uv;
void main() {
  vec4 eye = u_view * vec4(a_pos + u_offset, 1.0);
  gl_Position = u_proj * eye; v_n = mat3(u_view) * a_n; v_pos = eye.xyz; v_uv = a_uv;
}`;
const FS_MESH = `#version 300 es
precision mediump float;
in vec3 v_n; in vec3 v_pos; in vec2 v_uv;
uniform vec4 u_color; uniform bool u_useTex; uniform sampler2D u_tex; uniform bool u_lit;
out vec4 o;
${LIGHT}
void main() {
  vec4 c = u_useTex ? texture(u_tex, v_uv) : u_color;
  o = vec4(u_lit ? shade(c.rgb, v_n, v_pos) : c.rgb, c.a * u_color.a);
}`;
const VS_FLAT = `#version 300 es
in vec3 a_pos; uniform mat4 u_view, u_proj;
void main() { gl_Position = u_proj * u_view * vec4(a_pos, 1.0); }`;
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

// Strang: Querschnitt als abgerundetes Rechteck (Superellipse, 8 Punkte) an beiden Enden plus je eine Spitze -
// wie ein echter Extrusionsstrang: flach oben/unten, rund an den Seiten. Die Normalen zeigen an den Punkten nach
// aussen, weich interpoliert wirkt der Strang rund; Schichten liegen ohne tiefe Rillen aufeinander.
function strandMesh(N = 8) {
  const sg = (x) => (x < 0 ? -1 : 1);
  const ring = [];
  for (let k = 0; k < N; k++) {
    const a = (k / N) * 2 * Math.PI, c = Math.cos(a), s = Math.sin(a);
    const p = [sg(c) * Math.sqrt(Math.abs(c)), sg(s) * Math.sqrt(Math.abs(s))];       // |x|^4 + |y|^4 = 1
    const n = [sg(c) * Math.abs(c) ** 1.5, sg(s) * Math.abs(s) ** 1.5];
    const l = Math.hypot(...n) || 1;
    ring.push([p[0], p[1], n[0] / l, n[1] / l]);
  }
  const v = [];
  for (const t of [0, 1]) for (const [sd, up, ns, nu] of ring) v.push(t, sd, up, 0, 0, ns, nu);
  v.push(0, 0, 0, -1, -1, 0, 0);                             // Spitze am Anfang (2N)
  v.push(1, 0, 0, 1, 1, 0, 0);                               // Spitze am Ende (2N+1)
  const idx = [];
  for (let k = 0; k < N; k++) {
    const a = k, b = (k + 1) % N;
    idx.push(a, b, N + b, a, N + b, N + a);                  // Mantel
    idx.push(2 * N, b, a, 2 * N + 1, N + a, N + b);          // Spitzen
  }
  return { v: new Float32Array(v), idx: new Uint16Array(idx) };
}

// Platte als abgerundetes Rechteck mit Dicke: Oberseite (Textur), Rand, Unterseite.
function plateMesh(bed) {
  const x0 = -MARGIN, x1 = bed + MARGIN, size = x1 - x0, r = RADIUS, seg = 8, out = [];
  const corners = [[x1 - r, x0 + r, -Math.PI / 2], [x1 - r, x1 - r, 0], [x0 + r, x1 - r, Math.PI / 2], [x0 + r, x0 + r, Math.PI]];
  for (const [cx, cy, a0] of corners) for (let i = 0; i <= seg; i++) {
    const a = a0 + (Math.PI / 2) * (i / seg);
    out.push([cx + r * Math.cos(a), cy + r * Math.sin(a), Math.cos(a), Math.sin(a)]);
  }
  const top = [], side = [], c = bed / 2;
  const uv = (x, y) => [(x - x0) / size, 1 - (y - x0) / size];
  out.forEach((p, i) => {
    const q = out[(i + 1) % out.length];
    top.push(c, c, 0, 0, 0, 1, ...uv(c, c), p[0], p[1], 0, 0, 0, 1, ...uv(p[0], p[1]), q[0], q[1], 0, 0, 0, 1, ...uv(q[0], q[1]));
    top.push(c, c, -THICK, 0, 0, -1, 0, 0, q[0], q[1], -THICK, 0, 0, -1, 0, 0, p[0], p[1], -THICK, 0, 0, -1, 0, 0);
    const P = (x, y, z, nx, ny) => side.push(x, y, z, nx, ny, 0, 0, 0);
    P(p[0], p[1], 0, p[2], p[3]); P(p[0], p[1], -THICK, p[2], p[3]); P(q[0], q[1], -THICK, q[2], q[3]);
    P(p[0], p[1], 0, p[2], p[3]); P(q[0], q[1], -THICK, q[2], q[3]); P(q[0], q[1], 0, q[2], q[3]);
  });
  return { top: new Float32Array(top), side: new Float32Array(side) };
}

// Aufdruck der Platte: Raster alle 10 mm, Rahmen des Druckbereichs, Schriftzug - einmal in ein Canvas gezeichnet.
function plateTexture(bed) {
  const px = 2048, size = bed + 2 * MARGIN, k = px / size;
  const c = document.createElement("canvas"); c.width = c.height = px;
  const g = c.getContext("2d");
  const rgb = (a) => `rgb(${a.map((x) => Math.round(x * 255)).join(",")})`;
  g.fillStyle = rgb(PLATE); g.fillRect(0, 0, px, px);
  const X = (mm) => (mm + MARGIN) * k, Y = (mm) => px - (mm + MARGIN) * k;
  g.strokeStyle = "rgba(230,230,230,0.42)"; g.lineWidth = 2;
  g.beginPath();
  for (let mm = 0; mm <= bed + 1e-6; mm += 10) {
    g.moveTo(X(mm), Y(0)); g.lineTo(X(mm), Y(bed));
    g.moveTo(X(0), Y(mm)); g.lineTo(X(bed), Y(mm));
  }
  g.stroke();
  g.strokeStyle = "rgba(240,240,240,0.7)"; g.lineWidth = 4;
  g.strokeRect(X(0), Y(bed), bed * k, bed * k);
  g.fillStyle = "rgba(240,240,240,0.35)";
  g.font = `600 ${Math.round(7 * k)}px sans-serif`;
  g.textAlign = "right"; g.textBaseline = "bottom";
  g.fillText("KOBRA S1", X(bed - 3), Y(3));
  return c;
}

function cone(r, h, seg = 20) {
  const v = [], s = Math.hypot(r, h);
  for (let i = 0; i < seg; i++) {
    const a = (i / seg) * 2 * Math.PI, b = ((i + 1) / seg) * 2 * Math.PI;
    const n = (t) => [Math.cos(t) * h / s, Math.sin(t) * h / s, r / s];
    v.push(0, 0, 0, ...n((a + b) / 2), 0, 0);
    v.push(r * Math.cos(a), r * Math.sin(a), h, ...n(a), 0, 0);
    v.push(r * Math.cos(b), r * Math.sin(b), h, ...n(b), 0, 0);
    v.push(0, 0, h, 0, 0, 1, 0, 0, r * Math.cos(b), r * Math.sin(b), h, 0, 0, 1, 0, 0, r * Math.cos(a), r * Math.sin(a), h, 0, 0, 1, 0, 0);
  }
  return new Float32Array(v);
}

const hexRgb = (h) => { const s = String(h || "").replace("#", "").padEnd(6, "8"); return [0, 2, 4].map((i) => parseInt(s.slice(i, i + 2), 16) / 255); };

export class PrintView {
  constructor(canvas, onLost) {
    this.canvas = canvas;
    const gl = canvas.getContext("webgl2", { antialias: true, alpha: false, preserveDrawingBuffer: false });
    if (!gl) throw new Error("WebGL2 nicht verfügbar");
    this.gl = gl;
    this.prog = program(gl, VS, FS);
    this.meshProg = program(gl, VS_MESH, FS_MESH);
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
    this._plate(250);
    this._nozzleBuf = this._meshBuffer(cone(2.2, 7));
    canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); this.lost = true; onLost?.(); });
    this._controls();
    this._ro = new ResizeObserver(() => this.redraw());
    this._ro.observe(canvas);
    this._loop = () => { if (this.dirty && !this.lost) { this.dirty = false; this._draw(); } this._raf = requestAnimationFrame(this._loop); };
    this._raf = requestAnimationFrame(this._loop);
  }

  redraw() { this.dirty = true; }

  // ---------------------------------------------------------- Platte
  _meshBuffer(data) {
    const gl = this.gl, p = this.meshProg;
    const vao = gl.createVertexArray(), buf = gl.createBuffer();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    [["a_pos", 3, 0], ["a_n", 3, 12], ["a_uv", 2, 24]].forEach(([name, size, off]) => {
      const loc = gl.getAttribLocation(p, name);
      if (loc < 0) return;
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 32, off);
    });
    gl.bindVertexArray(null);
    return { vao, buf, count: data.length / 8 };
  }

  _plate(bed) {
    if (this.plateBed === bed) return;
    const gl = this.gl;
    this.plateBed = bed;
    [this.plateTop, this.plateSide].forEach((m) => { if (m) { gl.deleteVertexArray(m.vao); gl.deleteBuffer(m.buf); } });
    const m = plateMesh(bed);
    this.plateTop = this._meshBuffer(m.top);
    this.plateSide = this._meshBuffer(m.side);
    if (this.plateTex) gl.deleteTexture(this.plateTex);
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, plateTexture(bed));
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const aniso = gl.getExtension("EXT_texture_filter_anisotropic");
    if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(8, gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT)));
    this.plateTex = tex;
  }

  // ---------------------------------------------------------- Bahnen
  load(geo) {
    const gl = this.gl;
    this.geo = geo;
    this._plate(geo.bed);
    if (this.vaoBox) gl.deleteVertexArray(this.vaoBox);
    if (this.vaoLine) gl.deleteVertexArray(this.vaoLine);
    this.buffers?.forEach((b) => gl.deleteBuffer(b));
    // Schichthoehe je Bahn (1/100 mm) aus den Schichten - die erste Schicht ist meist dicker
    const L = geo.layers, lh = new Float32Array(L.length);
    for (let i = 0; i < L.length; i++) lh[i] = i ? L[i] - L[i - 1] : L[0];
    const gaps = Array.from(lh.slice(1)).sort((a, b) => a - b);
    const typical = gaps.length ? Math.max(0.05, gaps[gaps.length >> 1]) : 0.2;
    const heights = new Uint8Array(geo.n);
    for (let i = 0; i < geo.n; i++) {
      const h = lh[geo.layer[i]];
      heights[i] = Math.min(255, Math.round(100 * (h > 0.02 && h < 1.5 ? h : typical)));
    }
    const buf = (data) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW); return b; };
    const inst = buf(geo.cols), tools = buf(geo.tools), widths = buf(geo.widths), hb = buf(heights);
    const s = strandMesh();
    const mesh = buf(s.v);
    const line = buf(new Float32Array([0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]));
    const ibo = gl.createBuffer();
    this.buffers = [inst, tools, widths, hb, mesh, line, ibo];
    this.strandCount = s.idx.length;
    const p = this.prog;
    const vaoFor = (meshBuf, withIndex) => {
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
      [["a_tool", tools], ["a_width", widths], ["a_height", hb]].forEach(([name, b]) => {
        const loc = gl.getAttribLocation(p, name);
        if (loc < 0) return;
        gl.bindBuffer(gl.ARRAY_BUFFER, b);
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, 1, gl.UNSIGNED_BYTE, false, 0, 0);
        gl.vertexAttribDivisor(loc, 1);
      });
      gl.bindBuffer(gl.ARRAY_BUFFER, meshBuf);
      const vl = gl.getAttribLocation(p, "a_v"), nl = gl.getAttribLocation(p, "a_n");
      gl.enableVertexAttribArray(vl);
      gl.vertexAttribPointer(vl, 4, gl.FLOAT, false, 28, 0);
      if (nl >= 0) { gl.enableVertexAttribArray(nl); gl.vertexAttribPointer(nl, 3, gl.FLOAT, false, 28, 16); }
      if (withIndex) { gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, s.idx, gl.STATIC_DRAW); }
      gl.bindVertexArray(null);
      return vao;
    };
    this.vaoBox = vaoFor(mesh, true);
    this.vaoLine = vaoFor(line, false);
    this.maxLayer = L.length - 1;
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
    this.cam.target = [(x0 + x1) / 2, (y0 + y1) / 2, g.zmax / 3];
    this.cam.dist = size * 2.1;
    this.home = { ...this.cam, target: [...this.cam.target] };
  }

  view(kind) {
    const h = this.home || this.cam;
    this.cam = { ...h, target: [...h.target], ...(kind === "top" ? { yaw: 0, pitch: 1.55 } : kind === "front" ? { yaw: 0, pitch: 0.05 } : { yaw: -0.75, pitch: 0.55 }) };
    this.redraw();
  }

  set(opts) { Object.assign(this, opts); this.redraw(); }
  setColors(hexes) { this.colors = Array.from({ length: 16 }, (_, i) => hexRgb(hexes?.[i] || "cccccc")); this.redraw(); }

  _matrices() {
    const c = this.canvas, aspect = c.width / Math.max(1, c.height);
    const { yaw, pitch, dist, target } = this.cam;
    const eye = [target[0] + dist * Math.cos(pitch) * Math.sin(yaw), target[1] - dist * Math.cos(pitch) * Math.cos(yaw), target[2] + dist * Math.sin(pitch)];
    const up = pitch > 1.5 ? [Math.sin(yaw), Math.cos(yaw), 0] : [0, 0, 1];
    return { view: lookAt(eye, target, up), proj: perspective(0.7, aspect, Math.max(0.5, dist / 200), dist * 6 + 800) };
  }

  _draw() {
    const gl = this.gl, c = this.canvas;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(c.clientWidth * dpr)), h = Math.max(1, Math.round(c.clientHeight * dpr));
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    gl.viewport(0, 0, w, h);
    gl.clearColor(...BG, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    gl.disable(gl.BLEND);
    const m = this._matrices();
    this._drawPlate(m);
    const g = this.geo;
    if (!g || !g.n) return;
    const p = this.prog;
    gl.useProgram(p);
    const u = (n) => gl.getUniformLocation(p, n);
    gl.uniformMatrix4fv(u("u_view"), false, m.view);
    gl.uniformMatrix4fv(u("u_proj"), false, m.proj);
    gl.uniform1f(u("u_bed"), g.bed);
    gl.uniform1f(u("u_zmax"), g.zmax);
    gl.uniform1f(u("u_maxLayer"), this.maxLayer);
    gl.uniform1f(u("u_single"), this.single ? 1 : 0);
    gl.uniform1i(u("u_done"), this.done);
    gl.uniform3fv(u("u_colors"), this.colors.flat());
    const volume = this.mode === "volume";
    gl.uniform1i(u("u_volume"), volume ? 1 : 0);
    gl.uniform1f(u("u_ghostAlpha"), volume ? GHOST_ALPHA : GHOST_ALPHA_LINES);
    const draw = () => {
      if (volume) { gl.bindVertexArray(this.vaoBox); gl.drawElementsInstanced(gl.TRIANGLES, this.strandCount, gl.UNSIGNED_SHORT, 0, g.n); }
      else { gl.bindVertexArray(this.vaoLine); gl.drawArraysInstanced(gl.LINES, 0, 2, g.n); }
    };
    gl.uniform1i(u("u_pass"), 0);
    draw();                                                   // Gedrucktes, deckend
    this._nozzle(m);
    if (this.ghost && this.done < g.n) {
      // Rest blass durchsichtig: erst nur die Tiefe (vorderste Flaeche), dann einmal Farbe darueber blenden -
      // so liegen hintereinander liegende Bahnen nicht mehrfach uebereinander
      gl.useProgram(p);
      gl.uniform1i(u("u_pass"), 1);
      if (volume) {
        gl.colorMask(false, false, false, false);
        draw();
        gl.colorMask(true, true, true, true);
        gl.depthMask(false);
      }
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      draw();
      gl.disable(gl.BLEND);
      gl.depthMask(true);
    }
    gl.bindVertexArray(null);
  }

  _mesh(m, mesh, color, { tex = null, lit = true, offset = [0, 0, 0] } = {}) {
    const gl = this.gl, p = this.meshProg;
    gl.useProgram(p);
    const u = (n) => gl.getUniformLocation(p, n);
    gl.uniformMatrix4fv(u("u_view"), false, m.view);
    gl.uniformMatrix4fv(u("u_proj"), false, m.proj);
    gl.uniform3fv(u("u_offset"), offset);
    gl.uniform4fv(u("u_color"), color);
    gl.uniform1i(u("u_lit"), lit ? 1 : 0);
    gl.uniform1i(u("u_useTex"), tex ? 1 : 0);
    if (tex) { gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex); gl.uniform1i(u("u_tex"), 0); }
    gl.bindVertexArray(mesh.vao);
    gl.drawArrays(gl.TRIANGLES, 0, mesh.count);
    gl.bindVertexArray(null);
  }

  _drawPlate(m) {
    // Platte unbeleuchtet wie Orca (gleichmaessig grau), nur der Rand bekommt Licht fuer die Kante
    this._mesh(m, this.plateTop, [1, 1, 1, 1], { tex: this.plateTex, lit: false });
    this._mesh(m, this.plateSide, [...PLATE_EDGE, 1]);
    // Achsen am Nullpunkt wie in Orca: X rot, Y gruen
    const gl = this.gl;
    gl.useProgram(this.flat);
    if (!this._axisBuf) {
      this._axisVao = gl.createVertexArray();
      gl.bindVertexArray(this._axisVao);
      this._axisBuf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this._axisBuf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 0.05, 25, 0, 0.05, 0, 0, 0.05, 0, 25, 0.05]), gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(this.flat, "a_pos");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 3, gl.FLOAT, false, 0, 0);
    }
    gl.bindVertexArray(this._axisVao);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.flat, "u_view"), false, m.view);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.flat, "u_proj"), false, m.proj);
    gl.uniform4fv(gl.getUniformLocation(this.flat, "u_color"), [0.86, 0.25, 0.25, 1]);
    gl.drawArrays(gl.LINES, 0, 2);
    gl.uniform4fv(gl.getUniformLocation(this.flat, "u_color"), [0.3, 0.78, 0.35, 1]);
    gl.drawArrays(gl.LINES, 2, 2);
    gl.bindVertexArray(null);
  }

  _nozzle(m) {
    const g = this.geo, i = Math.min(this.done, g.n) - 1;
    if (i < 0 || this.single || this.done >= g.n) return;
    const q = g.bed / 65535;
    const pos = [g.x1[i] * q, g.y1[i] * q, g.z[i] / 65535 * g.zmax];
    // Kegel mit der Spitze an der Duese, etwas durchscheinend wie Orcas Werkzeug-Markierung
    const gl = this.gl;
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    this._mesh(m, this._nozzleBuf, [1.0, 0.84, 0.36, 0.9], { offset: pos });
    gl.disable(gl.BLEND);
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
