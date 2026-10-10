// Gráfica de línea simple en SVG (sin dependencias externas, funciona sin internet).
function graficaLinea(contenedor, puntos, opciones = {}) {
  const el = typeof contenedor === "string" ? document.querySelector(contenedor) : contenedor;
  if (!puntos.length) { el.innerHTML = '<div class="vacio">Aún no hay rondas terminadas.</div>'; return; }
  const W = el.clientWidth || 600, H = opciones.alto || 220, m = { t: 12, r: 12, b: 26, l: 34 };
  const w = W - m.l - m.r, h = H - m.t - m.b;
  const x = i => m.l + (puntos.length === 1 ? w / 2 : (i * w) / (puntos.length - 1));
  const y = v => m.t + h - (v / 100) * h;
  let s = `<svg class="linea" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
  for (const v of [0, 25, 50, 75, 100]) {
    s += `<line class="eje" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/>`;
    s += `<text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  }
  if (opciones.meta) s += `<line class="meta" x1="${m.l}" x2="${W - m.r}" y1="${y(opciones.meta)}" y2="${y(opciones.meta)}"/>`;
  const d = puntos.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.v)}`).join("");
  s += `<path class="area" d="${d}L${x(puntos.length - 1)},${y(0)}L${x(0)},${y(0)}Z"/>`;
  s += `<path class="trazo" d="${d}"/>`;
  const paso = Math.ceil(puntos.length / 12);
  puntos.forEach((p, i) => {
    s += `<circle class="punto" cx="${x(i)}" cy="${y(p.v)}" r="4"><title>${p.t}: ${p.v}%</title></circle>`;
    if (i % paso === 0) s += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${p.e}</text>`;
  });
  el.innerHTML = s + "</svg>";
}
