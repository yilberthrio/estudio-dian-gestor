// Gráficas en SVG/HTML sin dependencias externas (funcionan sin internet).
// Todas se vuelven a dibujar al cambiar el ancho de la ventana y muestran el detalle al pasar el mouse.

const _graficas = [];
let _anchoPrevio = window.innerWidth;
window.addEventListener("resize", () => {
  if (Math.abs(window.innerWidth - _anchoPrevio) < 8) return;
  _anchoPrevio = window.innerWidth;
  _graficas.forEach(f => f());
});
function _registrar(f) { _graficas.push(f); f(); }
function _el(c) { return typeof c === "string" ? document.querySelector(c) : c; }
function _esc(s) { return String(s ?? "").replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch])); }
function _fmt(v, suf = "") { return v === null || v === undefined ? "–" : (Math.round(v * 10) / 10).toLocaleString("es-CO") + suf; }

// ------------------------------------------------------------ Tooltip único
let _tt;
function tooltip(evento, html) {
  if (!_tt) { _tt = document.createElement("div"); _tt.className = "tt"; document.body.appendChild(_tt); }
  if (html === null) { _tt.style.opacity = 0; return; }
  _tt.innerHTML = html;
  _tt.style.opacity = 1;
  const r = _tt.getBoundingClientRect(), m = 14;
  let x = evento.clientX + m, y = evento.clientY + m;
  if (x + r.width > window.innerWidth - 8) x = evento.clientX - r.width - m;
  if (y + r.height > window.innerHeight - 8) y = evento.clientY - r.height - m;
  _tt.style.left = x + "px";
  _tt.style.top = y + "px";
}
// Cualquier elemento con data-tt muestra su texto al pasar el mouse (o al enfocarlo con el teclado).
document.addEventListener("mouseover", e => { const t = e.target.closest("[data-tt]"); if (t) tooltip(e, t.dataset.tt); });
document.addEventListener("mousemove", e => { const t = e.target.closest("[data-tt]"); if (t) tooltip(e, t.dataset.tt); });
document.addEventListener("mouseout", e => { if (e.target.closest("[data-tt]")) tooltip(e, null); });
document.addEventListener("focusin", e => {
  const t = e.target.closest("[data-tt]");
  if (t) { const r = t.getBoundingClientRect(); tooltip({ clientX: r.right, clientY: r.top }, t.dataset.tt); }
});
document.addEventListener("focusout", e => { if (e.target.closest("[data-tt]")) tooltip(e, null); });

function _refs(op) {
  return (op.lineas || op.refs || (op.meta ? [op.meta] : [])).map(r => (typeof r === "number" ? { v: r } : r));
}

// ------------------------------------------------------------ Línea (evolución)
// puntos: [{v, e: etiqueta del eje, t: título del tooltip}] · opciones: {lineas|refs, alto, max, sufijo, vacio}
function graficaLinea(contenedor, puntos, opciones = {}) {
  const el = _el(contenedor);
  if (!el) return;
  _registrar(() => {
    if (!puntos.length) { el.innerHTML = `<div class="vacio">${opciones.vacio || "Aún no hay rondas terminadas."}</div>`; return; }
    const suf = opciones.sufijo ?? "%", max = opciones.max ?? 100;
    const W = el.clientWidth || 600, H = opciones.alto || 220, m = { t: 14, r: 64, b: 26, l: 34 };
    const w = W - m.l - m.r, h = H - m.t - m.b;
    const x = i => m.l + (puntos.length === 1 ? w / 2 : (i * w) / (puntos.length - 1));
    const y = v => m.t + h - (Math.max(0, Math.min(max, v)) / max) * h;
    let s = `<svg class="linea" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${_esc(opciones.aria || "Gráfica de evolución")}">`;
    for (const v of [0, 25, 50, 75, 100].map(p => (p * max) / 100)) {
      s += `<line class="eje" x1="${m.l}" x2="${m.l + w}" y1="${y(v)}" y2="${y(v)}"/>`;
      s += `<text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${_fmt(v)}</text>`;
    }
    for (const r of _refs(opciones)) {
      s += `<line class="meta" x1="${m.l}" x2="${m.l + w}" y1="${y(r.v)}" y2="${y(r.v)}"/>`;
      s += `<text class="ref" x="${m.l + w + 6}" y="${y(r.v) + 4}">${_esc(r.l || _fmt(r.v))}</text>`;
    }
    const d = puntos.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.v)}`).join("");
    s += `<path class="area" d="${d}L${x(puntos.length - 1)},${y(0)}L${x(0)},${y(0)}Z"/>`;
    s += `<path class="trazo" d="${d}"/>`;
    if (puntos.length <= 40) puntos.forEach((p, i) => { s += `<circle class="punto" cx="${x(i)}" cy="${y(p.v)}" r="4"/>`; });
    const ult = puntos[puntos.length - 1];
    s += `<circle class="punto fin" cx="${x(puntos.length - 1)}" cy="${y(ult.v)}" r="5"/>`;
    const paso = Math.ceil(puntos.length / Math.max(2, Math.floor(w / 70)));
    puntos.forEach((p, i) => { if (i % paso === 0) s += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${_esc(p.e)}</text>`; });
    s += `<line class="guia" x1="0" x2="0" y1="${m.t}" y2="${m.t + h}" style="opacity:0"/>`;
    s += `<circle class="punto activo" r="5" cx="0" cy="0" style="opacity:0"/>`;
    s += `<rect class="captura" x="${m.l}" y="${m.t}" width="${w}" height="${h}"/>`;
    el.innerHTML = s + "</svg>" + `<div class="valor-fin">Último: <b>${_fmt(ult.v, suf)}</b></div>`;
    const svg = el.querySelector("svg"), guia = svg.querySelector(".guia"), act = svg.querySelector(".activo");
    svg.querySelector(".captura").addEventListener("mousemove", e => {
      const bx = svg.getBoundingClientRect();
      const i = puntos.length === 1 ? 0 : Math.round(((e.clientX - bx.left - m.l) / w) * (puntos.length - 1));
      const p = puntos[Math.max(0, Math.min(puntos.length - 1, i))], k = puntos.indexOf(p);
      guia.setAttribute("x1", x(k)); guia.setAttribute("x2", x(k)); guia.style.opacity = 1;
      act.setAttribute("cx", x(k)); act.setAttribute("cy", y(p.v)); act.style.opacity = 1;
      tooltip(e, `<b>${_esc(p.t || p.e)}</b><br>${_fmt(p.v, suf)}`);
    });
    svg.querySelector(".captura").addEventListener("mouseleave", e => {
      guia.style.opacity = 0; act.style.opacity = 0; tooltip(e, null);
    });
  });
}

// ------------------------------------------------------------ Barras horizontales
// filas: [{l, sub, v, lo, hi, tt, clase, href, txt}] · opciones: {max, refs, sufijo, vacio}
// lo/hi dibujan el intervalo de confianza (qué tan seguro es el porcentaje con las respuestas que tienes).
function barrasH(contenedor, filas, opciones = {}) {
  const el = _el(contenedor);
  if (!el) return;
  _registrar(() => {
    if (!filas.length) { el.innerHTML = `<div class="vacio">${opciones.vacio || "Sin datos todavía."}</div>`; return; }
    const max = opciones.max ?? 100, suf = opciones.sufijo ?? "%";
    const pos = v => `${(Math.max(0, Math.min(max, v)) / max) * 100}%`;
    const refs = _refs(opciones);
    let s = `<div class="bh">`;
    if (refs.length) {
      s += `<div class="bh-fila bh-cab"><div></div><div class="bh-pista sin-fondo">` +
        [...refs].sort((a, b) => a.v - b.v).map((r, i, t) => `<span class="bh-ref-l ${t.length > 1 ? (i === 0 ? "izq" : "der") : ""}" style="left:${pos(r.v)}">${_esc(r.l || _fmt(r.v))}</span>`).join("") + `</div><div></div></div>`;
    }
    for (const f of filas) {
      const etiqueta = f.href ? `<a href="${f.href}">${_esc(f.l)}</a>` : _esc(f.l);
      const tt = f.tt || `${f.l}: ${_fmt(f.v, suf)}`;
      s += `<div class="bh-fila"><div class="bh-l">${etiqueta}${f.sub ? `<div class="peq suave">${f.sub}</div>` : ""}</div>`;
      s += `<div class="bh-pista" tabindex="0" data-tt="${_esc(tt)}">`;
      s += refs.map(r => `<span class="bh-ref" style="left:${pos(r.v)}"></span>`).join("");
      if (f.v !== null && f.v !== undefined) {
        s += `<span class="bh-barra ${f.clase || "s1"}" style="width:${pos(f.v)}"></span>`;
        if (f.lo !== null && f.lo !== undefined) {
          s += `<span class="bh-ic" style="left:${pos(f.lo)};width:calc(${pos(f.hi)} - ${pos(f.lo)})"></span>`;
        }
      }
      s += `</div><div class="bh-v">${f.txt ?? _fmt(f.v, suf)}</div></div>`;
    }
    el.innerHTML = s + `</div>`;
  });
}

// ------------------------------------------------------------ Columnas
// datos: [{l, v, n, tt, clase}] · opciones: {max, refs, sufijo, alto, vacio, compacta}
// compacta: sin el valor encima de cada columna (para muchas columnas); el detalle queda en el tooltip.
function columnas(contenedor, datos, opciones = {}) {
  const el = _el(contenedor);
  if (!el) return;
  _registrar(() => {
    if (!datos.some(d => d.v !== null && d.v !== undefined)) { el.innerHTML = `<div class="vacio">${opciones.vacio || "Sin datos todavía."}</div>`; return; }
    const suf = opciones.sufijo ?? "%";
    const max = opciones.max ?? (Math.max(...datos.map(d => d.v || 0)) * 1.15 || 1);
    const conRefs = _refs(opciones).length > 0;
    const W = el.clientWidth || 400, H = opciones.alto || 200, m = { t: 22, r: conRefs ? 58 : 10, b: 38, l: 10 };
    const w = W - m.l - m.r, h = H - m.t - m.b, banda = w / datos.length, ancho = Math.min(36, banda * 0.55);
    const y = v => m.t + h - (Math.min(max, v) / max) * h;
    let s = `<svg class="col" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${_esc(opciones.aria || "Gráfica de columnas")}">`;
    s += `<line class="base" x1="${m.l}" x2="${m.l + w}" y1="${m.t + h}" y2="${m.t + h}"/>`;
    for (const r of _refs(opciones)) {
      s += `<line class="meta" x1="${m.l}" x2="${m.l + w}" y1="${y(r.v)}" y2="${y(r.v)}"/>`;
      s += `<text class="ref" x="${m.l + w + 6}" y="${y(r.v) + 4}">${_esc(r.l || _fmt(r.v))}</text>`;
    }
    datos.forEach((d, i) => {
      const cx = m.l + banda * i + banda / 2;
      const tt = d.tt || `${d.l}: ${_fmt(d.v, suf)}${d.n !== undefined ? ` · ${d.n} resp.` : ""}`;
      s += `<g data-tt="${_esc(tt)}" tabindex="0"><rect class="captura" x="${cx - banda / 2}" y="${m.t}" width="${banda}" height="${h}"/>`;
      if (d.v !== null && d.v !== undefined && d.v > 0) {
        const top = y(d.v), alto = m.t + h - top, r = Math.min(4, alto, ancho / 2);
        s += `<path class="barra ${d.clase || "s1"}" d="M${cx - ancho / 2},${m.t + h}V${top + r}q0,-${r} ${r},-${r}H${cx + ancho / 2 - r}q${r},0 ${r},${r}V${m.t + h}Z"/>`;
        if (!opciones.compacta) s += `<text class="valor" x="${cx}" y="${top - 6}" text-anchor="middle">${_fmt(d.v, suf)}</text>`;
      } else if (!opciones.compacta) {
        s += `<text class="valor suave" x="${cx}" y="${m.t + h - 6}" text-anchor="middle">${d.v === 0 ? _fmt(0, suf) : "–"}</text>`;
      }
      s += `<text x="${cx}" y="${m.t + h + 15}" text-anchor="middle">${_esc(d.l)}</text>`;
      if (d.n !== undefined) s += `<text class="n" x="${cx}" y="${m.t + h + 29}" text-anchor="middle">n=${d.n}</text>`;
      s += `</g>`;
    });
    el.innerHTML = s + "</svg>";
  });
}

// ------------------------------------------------------------ Barra apilada (partes de un total)
// segmentos: [{l, v, clase, d: descripción}] · opciones: {sufijo}
function apilada(contenedor, segmentos, opciones = {}) {
  const el = _el(contenedor);
  if (!el) return;
  _registrar(() => {
    const total = segmentos.reduce((a, s) => a + (s.v || 0), 0);
    if (!total) { el.innerHTML = `<div class="vacio">${opciones.vacio || "Sin datos todavía."}</div>`; return; }
    const pctTxt = v => `${Math.round((100 * v) / total)}%`;
    let barra = `<div class="ap">`, ley = `<div class="ap-ley">`;
    for (const s of segmentos) {
      if (!s.v) continue;
      const tt = `${s.l}: ${s.v} (${pctTxt(s.v)})${s.d ? "<br>" + s.d : ""}`;
      barra += `<span class="ap-seg ${s.clase}" style="flex:${s.v}" tabindex="0" data-tt="${_esc(tt)}"></span>`;
    }
    for (const s of segmentos) {
      ley += `<div class="ap-item"><i class="ap-sw ${s.clase}"></i><span>${_esc(s.l)}</span><b>${s.v}</b><span class="suave">${pctTxt(s.v)}</span></div>`;
    }
    el.innerHTML = barra + `</div>` + ley + `</div>`;
  });
}

// ------------------------------------------------------------ Telaraña (radar)
// ejes: [{l, tt}] · series: [{nombre, v: [valor 0–max o null por eje], clase: "s1"|"previo"}] · opciones: {max, alto, vacio}
// La primera serie es la principal: su valor se escribe junto al nombre de cada eje.
function radar(contenedor, ejes, series, opciones = {}) {
  const el = _el(contenedor);
  if (!el) return;
  _registrar(() => {
    if (ejes.length < 3) { el.innerHTML = `<div class="vacio">${opciones.vacio || "Se necesitan al menos 3 ejes."}</div>`; return; }
    const max = opciones.max ?? 100, n = ejes.length, suf = opciones.sufijo ?? "%";
    const W = el.clientWidth || 400, estrecho = W < 440, mx = estrecho ? 66 : 100, my = 44;
    const H = opciones.alto || Math.round(Math.min(400, Math.max(280, W * 0.82)));
    const R = Math.max(50, Math.min(W / 2 - mx, H / 2 - my)), cx = W / 2, cy = H / 2;
    const ang = i => -Math.PI / 2 + (2 * Math.PI * i) / n;
    const pt = (i, v) => {
      const r = (R * Math.max(0, Math.min(max, v))) / max;
      return [cx + Math.cos(ang(i)) * r, cy + Math.sin(ang(i)) * r];
    };
    const f = p => p.map(c => c.toFixed(1)).join(",");
    let s = `<svg class="radar" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${_esc(opciones.aria || "Gráfica de telaraña")}">`;
    for (const p of [25, 50, 75, 100]) {
      s += `<polygon class="anillo${p === 100 ? " ext" : ""}" points="${ejes.map((_, i) => f(pt(i, (p * max) / 100))).join(" ")}"/>`;
      s += `<text class="rd-esc" x="${cx + 4}" y="${pt(0, (p * max) / 100)[1] + 11}">${p}</text>`;
    }
    ejes.forEach((_, i) => { const [ex, ey] = pt(i, max); s += `<line class="eje" x1="${cx}" y1="${cy}" x2="${ex.toFixed(1)}" y2="${ey.toFixed(1)}"/>`; });
    // Series de atrás hacia adelante: la principal queda encima
    [...series].reverse().forEach(se => {
      const completa = se.v.every(v => v !== null && v !== undefined);
      if (completa) {
        s += `<polygon class="rd-area ${se.clase || "s1"}" points="${se.v.map((v, i) => f(pt(i, v))).join(" ")}"/>`;
      } else {
        // Con ejes sin dato se unen solo los vecinos que sí tienen valor
        let d = "";
        for (let k = 0; k <= n; k++) {
          const i = k % n, v = se.v[i], ant = se.v[(k + n - 1) % n];
          if (v === null || v === undefined) continue;
          d += `${k && ant !== null && ant !== undefined ? "L" : "M"}${f(pt(i, v))}`;
        }
        s += `<path class="rd-area linea ${se.clase || "s1"}" d="${d}"/>`;
      }
      se.v.forEach((v, i) => { if (v !== null && v !== undefined) s += `<circle class="rd-p ${se.clase || "s1"}" cx="${pt(i, v)[0].toFixed(1)}" cy="${pt(i, v)[1].toFixed(1)}" r="${se === series[0] ? 4 : 3}"/>`; });
    });
    // Etiquetas (nombre partido en líneas + valor principal) con el detalle al pasar el mouse
    const ancho = estrecho ? 11 : 15, lh = 13;
    ejes.forEach((e, i) => {
      const lineas = [];
      for (const palabra of String(e.l).split(" ")) {
        const u = lineas.length - 1;
        if (u >= 0 && (lineas[u] + " " + palabra).length <= ancho) lineas[u] += " " + palabra; else lineas.push(palabra);
      }
      const c = Math.cos(ang(i)), sn = Math.sin(ang(i));
      const lx = cx + c * (R + 12), ly = cy + sn * (R + 12);
      const anc = c > 0.3 ? "start" : c < -0.3 ? "end" : "middle";
      const total = lineas.length + 1;
      const y0 = sn < -0.3 ? ly - (total - 1) * lh : sn > 0.3 ? ly + lh * 0.75 : ly - ((total - 1) * lh) / 2 + 4;
      const tt = `<b>${_esc(e.l)}</b><br>` + series.map(se => `${_esc(se.nombre)}: ${_fmt(se.v[i], suf)}`).join("<br>") + (e.tt ? `<br>${e.tt}` : "");
      s += `<g class="rd-eje" tabindex="0" data-tt="${_esc(tt)}"><rect class="captura" x="${anc === "start" ? lx - 4 : anc === "end" ? lx - ancho * 7.2 : lx - ancho * 3.6}" y="${y0 - lh}" width="${ancho * 7.6}" height="${total * lh + 4}"/>`;
      s += `<text x="${lx.toFixed(1)}" y="${y0.toFixed(1)}" text-anchor="${anc}">`;
      lineas.forEach((t, k) => { s += `<tspan class="rd-l" x="${lx.toFixed(1)}" dy="${k ? lh : 0}">${_esc(t)}</tspan>`; });
      s += `<tspan class="rd-v" x="${lx.toFixed(1)}" dy="${lh}">${_fmt(series[0].v[i], suf)}</tspan></text></g>`;
    });
    let ley = "";
    if (series.length > 1) {
      ley = `<div class="rd-ley">` + series.map(se => `<span><i class="rd-sw ${se.clase || "s1"}"></i>${_esc(se.nombre)}</span>`).join("") + `</div>`;
    }
    el.innerHTML = s + "</svg>" + ley;
  });
}
