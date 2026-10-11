"""Estadísticas, análisis de fortalezas/debilidades, repaso espaciado (Leitner) e informes."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from db import COMPETENCIAS_LIKERT, DIR_INFORMES, ahora, config

# Valor de una respuesta según acierto y confianza: un acierto "adivinado" no es dominio real.
PESO_CONFIANZA = {"seguro": 1.0, "dudoso": 0.75, "adivine": 0.4}
DECAIMIENTO = 0.9  # las respuestas recientes pesan más (0.9^i, i = posición desde la más reciente)
INTERVALOS_LEITNER = {1: 0, 2: 1, 3: 3, 4: 7, 5: 15}  # días hasta el siguiente repaso por caja
NOMBRES_CONFIANZA = {"seguro": "Seguro", "dudoso": "Dudoso", "adivine": "Adiviné"}


def valor_respuesta(correcta, confianza):
    return PESO_CONFIANZA.get(confianza, 1.0) if correcta else 0.0


def pct(a, b):
    return round(100 * a / b, 1) if b else None


# ---------------------------------------------------------------- Leitner

def leitner_actualizar(con, pregunta_id, correcta, confianza):
    fila = con.execute("SELECT caja FROM leitner WHERE pregunta_id=?", (pregunta_id,)).fetchone()
    caja = fila["caja"] if fila else 1
    if not correcta:
        caja = 1
    elif confianza != "adivine":
        caja = min(caja + 1, 5)
    proxima = (date.today() + timedelta(days=INTERVALOS_LEITNER[caja])).isoformat()
    con.execute("INSERT INTO leitner (pregunta_id, caja, proxima) VALUES (?,?,?) "
                "ON CONFLICT(pregunta_id) DO UPDATE SET caja=excluded.caja, proxima=excluded.proxima",
                (pregunta_id, caja, proxima))


def pendientes_repaso(con):
    return con.execute(
        "SELECT COUNT(*) FROM leitner l JOIN preguntas p ON p.id=l.pregunta_id "
        "WHERE p.activa=1 AND l.proxima<=?", (date.today().isoformat(),)).fetchone()[0]


# ---------------------------------------------------------------- Agregados

def _respuestas_por_sesion(con):
    """{sesion_id: [(correcta, confianza), ...] de la más reciente a la más antigua}"""
    out = defaultdict(list)
    for r in con.execute(
            "SELECT p.sesion_id, r.correcta, r.confianza FROM respuestas r "
            "JOIN preguntas p ON p.id=r.pregunta_id ORDER BY r.fecha DESC, r.id DESC"):
        out[r["sesion_id"]].append((r["correcta"], r["confianza"]))
    return out


def _dominio(lista):
    if not lista:
        return None
    num = den = 0.0
    for i, (c, conf) in enumerate(lista):
        w = DECAIMIENTO ** i
        num += w * valor_respuesta(c, conf)
        den += w
    return round(100 * num / den, 1)


def clasificar(dominio, n, cfg):
    if dominio is None or n < int(cfg["minimo_respuestas_analisis"]):
        return "sin-datos"
    if dominio >= float(cfg["umbral_fortaleza"]):
        return "fortaleza"
    if dominio < float(cfg["umbral_debilidad"]):
        return "debilidad"
    return "en-desarrollo"


ETIQUETA_ESTADO = {"fortaleza": "Fortaleza", "en-desarrollo": "En desarrollo",
                   "debilidad": "Debilidad", "sin-datos": "Sin datos suficientes"}


def por_sesion(con):
    cfg = config(con)
    resp = _respuestas_por_sesion(con)
    filas = con.execute("""
        SELECT s.id, s.codigo, s.nombre, m.codigo AS mcod, m.nombre AS modulo,
          (SELECT COUNT(*) FROM preguntas p WHERE p.sesion_id=s.id AND p.activa=1) AS banco,
          (SELECT COUNT(DISTINCT r.pregunta_id) FROM respuestas r JOIN preguntas p ON p.id=r.pregunta_id
             WHERE p.sesion_id=s.id AND p.activa=1) AS vistas,
          (SELECT AVG(r.tiempo_seg) FROM respuestas r JOIN preguntas p ON p.id=r.pregunta_id
             WHERE p.sesion_id=s.id) AS tiempo
        FROM sesiones s JOIN modulos m ON m.id=s.modulo_id WHERE s.vigente=1 ORDER BY m.orden, s.orden""").fetchall()
    out = []
    for f in filas:
        lista = resp.get(f["id"], [])
        n = len(lista)
        aciertos = sum(c for c, _ in lista)
        dom = _dominio(lista)
        recientes, previas = lista[:10], lista[10:20]
        tendencia = None
        if len(recientes) >= 5 and len(previas) >= 5:
            tendencia = round(pct(sum(c for c, _ in recientes), len(recientes))
                              - pct(sum(c for c, _ in previas), len(previas)), 1)
        estado = clasificar(dom, n, cfg)
        out.append({**dict(f), "respuestas": n, "aciertos": aciertos, "errores": n - aciertos,
                    "pct": pct(aciertos, n), "dominio": dom, "estado": estado,
                    "estado_txt": ETIQUETA_ESTADO[estado], "tendencia": tendencia,
                    "cobertura": pct(f["vistas"], f["banco"]),
                    "tiempo": round(f["tiempo"], 1) if f["tiempo"] else None})
    return out


def por_modulo(sesiones):
    mods = {}
    for s in sesiones:
        m = mods.setdefault(s["mcod"], {"codigo": s["mcod"], "nombre": s["modulo"], "banco": 0,
                                        "vistas": 0, "respuestas": 0, "aciertos": 0})
        for k in ("banco", "vistas", "respuestas", "aciertos"):
            m[k] += s[k]
    for m in mods.values():
        m["pct"] = pct(m["aciertos"], m["respuestas"])
        m["cobertura"] = pct(m["vistas"], m["banco"])
    return list(mods.values())


def racha_dias(con):
    dias = {date.fromisoformat(r[0][:10]) for r in con.execute("SELECT DISTINCT substr(fecha,1,10) FROM respuestas")}
    d = date.today()
    if d not in dias:
        d -= timedelta(days=1)
    racha = 0
    while d in dias:
        racha += 1
        d -= timedelta(days=1)
    return racha


def resumen_global(con):
    g = con.execute("""SELECT
        (SELECT COUNT(*) FROM preguntas WHERE activa=1) AS banco,
        (SELECT COUNT(DISTINCT r.pregunta_id) FROM respuestas r JOIN preguntas p ON p.id=r.pregunta_id
           WHERE p.activa=1) AS vistas,
        (SELECT COUNT(*) FROM respuestas) AS respuestas,
        (SELECT COALESCE(SUM(correcta),0) FROM respuestas) AS aciertos,
        (SELECT COUNT(*) FROM rondas WHERE fin IS NOT NULL) AS rondas,
        (SELECT AVG(tiempo_seg) FROM respuestas) AS tiempo,
        (SELECT COUNT(*) FROM preguntas WHERE revisar=1) AS revisar,
        (SELECT COUNT(DISTINCT substr(fecha,1,10)) FROM respuestas) AS dias""").fetchone()
    g = dict(g)
    g["errores"] = g["respuestas"] - g["aciertos"]
    g["pct"] = pct(g["aciertos"], g["respuestas"])
    g["pct_error"] = pct(g["errores"], g["respuestas"])
    g["cobertura"] = pct(g["vistas"], g["banco"])
    g["tiempo"] = round(g["tiempo"], 1) if g["tiempo"] else None
    g["racha"] = racha_dias(con)
    g["repaso_hoy"] = pendientes_repaso(con)
    g["nunca_vistas"] = g["banco"] - g["vistas"]
    return g


def evolucion_rondas(con, limite=30):
    filas = con.execute("""
        SELECT ro.id, ro.inicio, ro.modo, ro.alcance, COUNT(r.id) AS n, COALESCE(SUM(r.correcta),0) AS ok
        FROM rondas ro JOIN respuestas r ON r.ronda_id=ro.id
        WHERE ro.fin IS NOT NULL GROUP BY ro.id ORDER BY ro.id DESC LIMIT ?""", (limite,)).fetchall()
    return [{**dict(f), "pct": pct(f["ok"], f["n"])} for f in reversed(filas)]


def calibracion(con):
    out = []
    for conf in ("seguro", "dudoso", "adivine"):
        f = con.execute("SELECT COUNT(*) n, COALESCE(SUM(correcta),0) ok FROM respuestas WHERE confianza=?",
                        (conf,)).fetchone()
        out.append({"confianza": conf, "nombre": NOMBRES_CONFIANZA[conf], "n": f["n"], "ok": f["ok"],
                    "pct": pct(f["ok"], f["n"])})
    return out


def mas_falladas(con, limite=10):
    return [dict(f) for f in con.execute("""
        SELECT p.id, p.enunciado, s.nombre AS sesion, COUNT(r.id) AS intentos,
               SUM(1-r.correcta) AS fallos, p.correcta, p.norma
        FROM respuestas r JOIN preguntas p ON p.id=r.pregunta_id JOIN sesiones s ON s.id=p.sesion_id
        WHERE p.activa=1 GROUP BY p.id HAVING fallos>0
        ORDER BY fallos DESC, intentos ASC LIMIT ?""", (limite,))]


def errores_con_seguridad(con, limite=10):
    """Preguntas falladas marcadas como 'seguro': conceptos que crees saber pero tienes errados."""
    return [dict(f) for f in con.execute("""
        SELECT p.id, p.enunciado, s.nombre AS sesion, COUNT(*) AS veces
        FROM respuestas r JOIN preguntas p ON p.id=r.pregunta_id JOIN sesiones s ON s.id=p.sesion_id
        WHERE r.correcta=0 AND r.confianza='seguro' AND p.activa=1
        GROUP BY p.id ORDER BY veces DESC LIMIT ?""", (limite,))]


def historial_snapshots(con):
    """{sesion_id: [(fecha, dominio), ...]} para ver la evolución del dominio por sesión."""
    out = defaultdict(list)
    for r in con.execute("SELECT sesion_id, fecha, dominio FROM snapshots ORDER BY id"):
        out[r["sesion_id"]].append((r["fecha"], r["dominio"]))
    return out


def guardar_snapshot(con, ronda_id):
    """Al cerrar una ronda guarda el estado de las sesiones tocadas en ella."""
    tocadas = {r[0] for r in con.execute(
        "SELECT DISTINCT p.sesion_id FROM respuestas r JOIN preguntas p ON p.id=r.pregunta_id "
        "WHERE r.ronda_id=?", (ronda_id,))}
    fecha = ahora()
    for s in por_sesion(con):
        if s["id"] in tocadas:
            con.execute("INSERT INTO snapshots (fecha, ronda_id, sesion_id, respuestas, pct_acierto, dominio) "
                        "VALUES (?,?,?,?,?,?)", (fecha, ronda_id, s["id"], s["respuestas"], s["pct"], s["dominio"]))


# ---------------------------------------------------------------- Informe

def recomendaciones(sesiones, g, calib):
    recs = []
    debiles = sorted([s for s in sesiones if s["estado"] == "debilidad"], key=lambda s: s["dominio"])
    for s in debiles[:3]:
        recs.append(f"Prioriza **{s['nombre']}** (dominio {s['dominio']}%). Haz rondas de solo esa sesión y pide preguntas nuevas sobre ella.")
    sin_datos = [s for s in sesiones if s["estado"] == "sin-datos" and s["banco"] > 0]
    if sin_datos:
        recs.append("Aún no tienes datos suficientes en: " + ", ".join(s["nombre"] for s in sin_datos[:6])
                    + (" …" if len(sin_datos) > 6 else "") + ".")
    vacias = [s for s in sesiones if s["banco"] == 0]
    if vacias:
        recs.append("Sesiones sin preguntas en el banco: " + ", ".join(s["nombre"] for s in vacias) + ".")
    seg = next(c for c in calib if c["confianza"] == "seguro")
    if seg["n"] >= 10 and seg["pct"] is not None and seg["pct"] < 85:
        recs.append(f"Cuando marcas *Seguro* aciertas solo el {seg['pct']}%: hay exceso de confianza. Revisa la lista de errores con seguridad.")
    adiv = next(c for c in calib if c["confianza"] == "adivine")
    if adiv["n"] >= 5:
        recs.append(f"Has adivinado {adiv['n']} veces: esas preguntas vuelven en el modo *Repaso espaciado* aunque las aciertes.")
    if g["repaso_hoy"]:
        recs.append(f"Tienes {g['repaso_hoy']} preguntas pendientes de repaso hoy.")
    if not recs:
        recs.append("Vas bien: mantén las rondas mixtas y aumenta la dificultad pidiendo preguntas de nivel 3.")
    return recs


def generar_informe_md(con):
    sesiones = por_sesion(con)
    g = resumen_global(con)
    calib = calibracion(con)
    fall = mas_falladas(con, 10)
    seg = errores_con_seguridad(con, 10)
    hist = historial_snapshots(con)
    L = [f"# Informe de estudio – Concurso DIAN 2676, Gestor I (empleo 236767)",
         f"_Generado: {datetime.now():%Y-%m-%d %H:%M}_", "",
         "## Resumen general", "",
         f"- Preguntas en el banco: **{g['banco']}** (vistas: {g['vistas']}, cobertura {g['cobertura'] or 0}%)",
         f"- Respuestas totales: **{g['respuestas']}** en {g['rondas']} rondas, {g['dias']} días de estudio (racha actual: {g['racha']})",
         f"- Acierto: **{g['pct'] if g['pct'] is not None else '–'}%** · Error: {g['pct_error'] if g['pct_error'] is not None else '–'}%",
         f"- Tiempo promedio por pregunta: {g['tiempo'] or '–'} s", ""]
    L += ["## Recomendaciones", ""] + [f"- {r}" for r in recomendaciones(sesiones, g, calib)] + [""]
    for estado, titulo in (("debilidad", "Debilidades"), ("en-desarrollo", "En desarrollo"), ("fortaleza", "Fortalezas")):
        grupo = sorted([s for s in sesiones if s["estado"] == estado], key=lambda s: s["dominio"])
        L += [f"## {titulo}", ""]
        if not grupo:
            L += ["_Ninguna por ahora._", ""]
            continue
        L += ["| Sesión | Código | Dominio | % acierto | Respuestas | Tendencia | Evolución del dominio |",
              "|---|---|---|---|---|---|---|"]
        for s in grupo:
            evo = " → ".join(f"{d:.0f}" for _, d in hist.get(s["id"], [])[-6:] if d is not None) or "–"
            tend = f"{s['tendencia']:+.1f}" if s["tendencia"] is not None else "–"
            L.append(f"| {s['nombre']} | `{s['codigo']}` | {s['dominio']}% | {s['pct']}% | {s['respuestas']} | {tend} | {evo} |")
        L.append("")
    L += ["## Calibración de confianza", "", "| Confianza | Respuestas | % acierto |", "|---|---|---|"]
    L += [f"| {c['nombre']} | {c['n']} | {c['pct'] if c['pct'] is not None else '–'}% |" for c in calib] + [""]
    if seg:
        L += ["## Errores con seguridad (conceptos que crees saber)", ""]
        L += [f"- [{s['sesion']}] #{s['id']}: {s['enunciado'][:160]} ({s['veces']}x)" for s in seg] + [""]
    if fall:
        L += ["## Preguntas más falladas", ""]
        L += [f"- [{f['sesion']}] #{f['id']}: {f['enunciado'][:160]} — {f['fallos']}/{f['intentos']} fallos"
              + (f" ({f['norma']})" if f["norma"] else "") for f in fall] + [""]
    L += ["## Detalle por sesión", "", "| Módulo | Sesión | Código | Banco | Vistas | Respuestas | % acierto | Dominio | Estado |",
          "|---|---|---|---|---|---|---|---|---|"]
    for s in sesiones:
        L.append(f"| {s['mcod']} | {s['nombre']} | `{s['codigo']}` | {s['banco']} | {s['vistas']} | {s['respuestas']} | "
                 f"{s['pct'] if s['pct'] is not None else '–'} | {s['dominio'] if s['dominio'] is not None else '–'} | {s['estado_txt']} |")
    texto = "\n".join(L) + "\n"
    DIR_INFORMES.mkdir(exist_ok=True)
    (DIR_INFORMES / "ultimo_informe.md").write_text(texto, encoding="utf-8")
    return texto


# ---------------------------------------------------------------- Práctica Likert

def analizar_practica(con, practica_id):
    """Perfil de una práctica comportamental/integridad. No hay respuestas correctas: se muestra la disposición
    por competencia y señales que las escalas de control de la prueba real podrían detectar."""
    filas = [dict(r) for r in con.execute("""SELECT a.*, r.valor FROM respuestas_likert r
        JOIN afirmaciones a ON a.id=r.afirmacion_id WHERE r.practica_id=? ORDER BY r.orden""", (practica_id,))]
    resp = [f for f in filas if f["valor"]]
    for f in resp:
        f["disposicion"] = f["valor"] if f["clave"] == "directa" else 5 - f["valor"]
    perfil = []
    for prueba, comps in COMPETENCIAS_LIKERT.items():
        for comp in comps:
            items = [f for f in resp if f["competencia"] == comp]
            if not items:
                continue
            directas = [f["valor"] for f in items if f["clave"] == "directa"]
            inversas = [f["valor"] for f in items if f["clave"] == "inversa"]
            media = sum(f["disposicion"] for f in items) / len(items)
            perfil.append({
                "prueba": prueba, "competencia": comp, "n": len(items),
                "disposicion": round((media - 1) / 3 * 100),
                # De acuerdo a la vez con conductas deseables y con su contrario: respuesta poco consistente
                "inconsistente": bool(directas and inversas and sum(directas) / len(directas) >= 3
                                      and sum(inversas) / len(inversas) >= 3),
            })
    n = len(resp)
    totalmente_acuerdo = sum(f["valor"] == 4 for f in resp)
    extremos = sum(f["valor"] in (1, 4) for f in resp)
    alertas = []
    if n and totalmente_acuerdo / n > 0.7:
        alertas.append(f"Marcaste «Totalmente de acuerdo» en el {round(100 * totalmente_acuerdo / n)}% de las afirmaciones. "
                       "La prueba real incluye escalas de control que detectan respuestas exageradamente favorables: "
                       "responde según lo que realmente haces, no según lo que suena ideal.")
    if any(p["inconsistente"] for p in perfil):
        alertas.append("En algunas competencias estuviste de acuerdo con una conducta y también con su contraria. "
                       "Revisa esas afirmaciones: leer con calma cada matiz (por ejemplo, «asumiendo tiempo adicional») evita contradicciones.")
    return {"items": filas, "perfil": perfil, "n": n, "sin_responder": len(filas) - n,
            "pct_totalmente": round(100 * totalmente_acuerdo / n) if n else None,
            "pct_extremos": round(100 * extremos / n) if n else None, "alertas": alertas}
