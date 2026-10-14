"""Estadísticas, análisis de fortalezas/debilidades, repaso espaciado (Leitner) e informes."""
import math
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


# ---------------------------------------------------------------- Análisis profundo

VENTANA_PROYECCION = 30   # últimas respuestas por indicador que entran en la proyección
VENTANA_CURVA = 20        # respuestas de la media móvil de la curva de aprendizaje
TRAMOS_TIEMPO = [(0, 15, "< 15 s"), (15, 30, "15–30 s"), (30, 60, "30–60 s"), (60, 120, "1–2 min"), (120, None, "> 2 min")]
NOMBRES_DIFICULTAD = {1: "Básica", 2: "Aplicación", 3: "Caso complejo"}


def wilson(k, n, z=1.96):
    """Intervalo de confianza del 95% para un porcentaje de acierto (método de Wilson)."""
    if not n:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return round(100 * max(0.0, c - h), 1), round(100 * min(1.0, c + h), 1)


def _respuestas_vigentes(con):
    """Respuestas de preguntas de indicadores vigentes, de la más antigua a la más reciente."""
    return [dict(r) for r in con.execute("""
        SELECT r.id, r.pregunta_id, r.correcta, r.confianza, r.tiempo_seg, r.fecha,
               p.dificultad, p.etiquetas, p.sesion_id, s.nombre AS sesion
        FROM respuestas r JOIN preguntas p ON p.id=r.pregunta_id JOIN sesiones s ON s.id=p.sesion_id
        WHERE s.vigente=1 ORDER BY r.fecha, r.id""")]


def proyeccion(con, sesiones=None):
    """Puntaje estimado en la prueba funcional: acierto reciente de cada indicador ponderado por su peso
    (la misma estructura del simulacro oficial), con margen de error y los puntos que se pierden frente a la meta."""
    cfg = config(con)
    meta, minimo = float(cfg["meta_puntaje"]), float(cfg["puntaje_minimo"])
    minimo_n = int(cfg["minimo_respuestas_analisis"])
    sesiones = sesiones or por_sesion(con)
    pesos = {r["id"]: r["peso"] or 1 for r in con.execute("SELECT id, peso FROM sesiones WHERE vigente=1")}
    recientes = defaultdict(list)
    for r in reversed(_respuestas_vigentes(con)):
        if len(recientes[r["sesion_id"]]) < VENTANA_PROYECCION:
            recientes[r["sesion_id"]].append(r["correcta"])
    peso_total = sum(pesos.get(s["id"], 1) for s in sesiones) or 1
    filas, suma, peso_datos, var = [], 0.0, 0, 0.0
    for s in sesiones:
        w = pesos.get(s["id"], 1)
        lista = recientes.get(s["id"], [])
        n = len(lista)
        p = pct(sum(lista), n) if n >= minimo_n else None
        lo, hi = wilson(sum(lista), n) if n >= minimo_n else (None, None)
        brecha = round(w / peso_total * max(0.0, meta - p), 2) if p is not None else None
        filas.append({"id": s["id"], "nombre": s["nombre"], "codigo": s["codigo"], "peso": w,
                      "peso_pct": round(100 * w / peso_total, 1), "n": n, "pct": p, "lo": lo, "hi": hi,
                      "brecha": brecha, "estado": s["estado"], "estado_txt": s["estado_txt"]})
        if p is not None:
            suma += w * p
            peso_datos += w
            var += (w ** 2) * (p / 100) * (1 - p / 100) / n
    puntaje = round(suma / peso_datos, 1) if peso_datos else None
    margen = round(196 * (var ** 0.5) / peso_datos, 1) if peso_datos else None
    prioridad = sorted([f for f in filas if f["brecha"]], key=lambda f: -f["brecha"])
    sin_datos = [f for f in filas if f["pct"] is None]
    # Lo que ganarías llevando a la meta las tres prioridades principales
    ganancia_top3 = round(sum(f["brecha"] for f in prioridad[:3]) * peso_total / peso_datos, 1) if peso_datos else None
    return {"puntaje": puntaje, "margen": margen, "meta": meta, "minimo": minimo,
            "cobertura_peso": round(100 * peso_datos / peso_total, 1), "filas": filas,
            "prioridad": prioridad, "sin_datos": sin_datos, "ganancia_top3": ganancia_top3,
            "ventana": VENTANA_PROYECCION}


def curva_aprendizaje(con, resp=None):
    """Media móvil del acierto sobre las últimas VENTANA_CURVA respuestas, en el orden en que respondiste."""
    resp = resp if resp is not None else _respuestas_vigentes(con)
    out, ventana = [], []
    paso = max(1, len(resp) // 150)  # no más de ~150 puntos en la gráfica
    for i, r in enumerate(resp, 1):
        ventana.append(r["correcta"])
        if len(ventana) > VENTANA_CURVA:
            ventana.pop(0)
        if (i % paso == 0 or i == len(resp)) and len(ventana) >= min(10, len(resp)):
            out.append({"i": i, "v": pct(sum(ventana), len(ventana)), "fecha": r["fecha"][:10]})
    return out


def por_dia(con, resp=None):
    resp = resp if resp is not None else _respuestas_vigentes(con)
    dias = {}
    for r in resp:
        d = dias.setdefault(r["fecha"][:10], {"fecha": r["fecha"][:10], "n": 0, "ok": 0, "seg": 0.0})
        d["n"] += 1
        d["ok"] += r["correcta"]
        d["seg"] += r["tiempo_seg"] or 0
    out = []
    for d in dias.values():
        out.append({**d, "pct": pct(d["ok"], d["n"]), "minutos": round(d["seg"] / 60, 1)})
    return out


def _grupo(resp, clave, orden, nombres):
    out = []
    for k in orden:
        sub = [r for r in resp if clave(r) == k]
        ok = sum(r["correcta"] for r in sub)
        lo, hi = wilson(ok, len(sub))
        out.append({"clave": k, "nombre": nombres[k], "n": len(sub), "ok": ok, "pct": pct(ok, len(sub)),
                    "lo": lo, "hi": hi})
    return out


def por_dificultad(resp):
    return _grupo(resp, lambda r: r["dificultad"] or 2, [1, 2, 3], NOMBRES_DIFICULTAD)


def por_tiempo(resp):
    def tramo(r):
        t = r["tiempo_seg"] or 0
        return next(i for i, (a, b, _) in enumerate(TRAMOS_TIEMPO) if t >= a and (b is None or t < b))
    return _grupo(resp, tramo, range(len(TRAMOS_TIEMPO)), {i: t[2] for i, t in enumerate(TRAMOS_TIEMPO)})


def ritmo(con, resp):
    """Tiempo por pregunta frente al presupuesto de la prueba real (minutos del simulacro ÷ preguntas)."""
    cfg = config(con)
    n_prueba, min_prueba = int(cfg["simulacro_oficial_preguntas"]), float(cfg["simulacro_oficial_minutos"])
    tiempos = sorted(r["tiempo_seg"] for r in resp if r["tiempo_seg"])
    if not tiempos:
        return None
    mediana = tiempos[len(tiempos) // 2]
    media = sum(tiempos) / len(tiempos)
    return {"media": round(media), "mediana": round(mediana), "presupuesto": round(60 * min_prueba / n_prueba),
            "minutos_prueba": round(media * n_prueba / 60), "minutos_disponibles": round(min_prueba),
            "n_prueba": n_prueba}


def retencion(resp):
    """Qué pasa cuando vuelves a ver una pregunta: transiciones entre intentos consecutivos."""
    por_pregunta = defaultdict(list)
    for r in resp:
        por_pregunta[r["pregunta_id"]].append(r["correcta"])
    t = {"recuperadas": 0, "persistentes": 0, "olvidadas": 0, "consolidadas": 0}
    primero = [v[0] for v in por_pregunta.values()]
    repetidos = [c for v in por_pregunta.values() for c in v[1:]]
    for v in por_pregunta.values():
        for a, b in zip(v, v[1:]):
            t[{(0, 1): "recuperadas", (0, 0): "persistentes", (1, 0): "olvidadas", (1, 1): "consolidadas"}[(a, b)]] += 1
    return {**t, "transiciones": sum(t.values()),
            "pct_primero": pct(sum(primero), len(primero)), "n_primero": len(primero),
            "pct_repetido": pct(sum(repetidos), len(repetidos)), "n_repetido": len(repetidos),
            "repetidas": sum(1 for v in por_pregunta.values() if len(v) > 1)}


def leitner_cajas(con):
    cajas = {r["caja"]: r["n"] for r in con.execute(
        "SELECT l.caja, COUNT(*) n FROM leitner l JOIN preguntas p ON p.id=l.pregunta_id "
        "JOIN sesiones s ON s.id=p.sesion_id WHERE p.activa=1 AND s.vigente=1 GROUP BY l.caja")}
    nunca = con.execute(
        "SELECT COUNT(*) FROM preguntas p JOIN sesiones s ON s.id=p.sesion_id WHERE p.activa=1 AND s.vigente=1 "
        "AND p.id NOT IN (SELECT pregunta_id FROM leitner)").fetchone()[0]
    return {"nunca": nunca, "cajas": [{"caja": c, "n": cajas.get(c, 0), "dias": INTERVALOS_LEITNER[c]} for c in range(1, 6)]}


def por_etiqueta(resp, minimo=3):
    """Acierto por subtema (etiqueta de la pregunta): señala la confusión concreta dentro de cada indicador."""
    grupos = defaultdict(lambda: {"n": 0, "ok": 0, "sesiones": defaultdict(int), "texto": None})
    for r in resp:
        for x in {x.strip() for x in (r["etiquetas"] or "").split(",") if x.strip()}:
            g = grupos[x.lower()]
            g["texto"] = g["texto"] or x
            g["n"] += 1
            g["ok"] += r["correcta"]
            g["sesiones"][r["sesion"]] += 1
    out = []
    for e, g in grupos.items():
        if g["n"] >= minimo:
            lo, hi = wilson(g["ok"], g["n"])
            out.append({"etiqueta": g["texto"], "n": g["n"], "ok": g["ok"], "pct": pct(g["ok"], g["n"]), "lo": lo, "hi": hi,
                        "sesion": max(g["sesiones"], key=g["sesiones"].get)})
    debiles = sorted(out, key=lambda x: (x["pct"], -x["n"]))
    fuertes = sorted([x for x in out if x["pct"] >= 90], key=lambda x: (-x["pct"], -x["n"]))
    return {"debiles": debiles[:15], "fuertes": fuertes[:10], "total": len(out)}


def confianza_indicadores(calib, g):
    seg = next(c for c in calib if c["confianza"] == "seguro")
    errores = g["errores"] or 0
    errores_seguro = seg["n"] - seg["ok"]
    aciertos = g["aciertos"] or 0
    aciertos_dudosos = sum(c["ok"] for c in calib if c["confianza"] != "seguro")
    return {"exceso": pct(errores_seguro, errores), "errores_seguro": errores_seguro,
            "fragil": pct(aciertos_dudosos, aciertos), "aciertos_dudosos": aciertos_dudosos,
            "pct_seguro": seg["pct"]}


def analisis_completo(con):
    sesiones = por_sesion(con)
    g = resumen_global(con)
    calib = calibracion(con)
    resp = _respuestas_vigentes(con)
    cfg = config(con)
    dias = (date.fromisoformat(cfg["fecha_prueba"]) - date.today()).days
    dias_estudio = len({r["fecha"][:10] for r in resp})
    return {"sesiones": sesiones, "g": g, "calib": calib, "proy": proyeccion(con, sesiones),
            "curva": curva_aprendizaje(con, resp), "dias": por_dia(con, resp),
            "dificultad": por_dificultad(resp), "tiempo": por_tiempo(resp), "ritmo": ritmo(con, resp),
            "retencion": retencion(resp), "leitner": leitner_cajas(con), "etiquetas": por_etiqueta(resp),
            "conf": confianza_indicadores(calib, g), "dias_prueba": max(dias, 0),
            "nuevas_por_dia": -(-g["nunca_vistas"] // dias) if dias > 0 else None,
            "promedio_dia": round(len(resp) / dias_estudio) if dias_estudio else 0}


# ---------------------------------------------------------------- Resultado de una ronda

def _conteo(sub):
    ok = sum(p["acierto"] for p in sub)
    lo, hi = wilson(ok, len(sub))
    return {"n": len(sub), "ok": ok, "pct": pct(ok, len(sub)), "lo": lo, "hi": hi}


def analizar_ronda(con, ronda, preguntas):
    """Explicación detallada de una ronda: dónde se perdieron los puntos, frente a tu histórico, cómo se
    relaciona la confianza con el acierto, el ritmo frente a la prueba real, la fatiga y los subtemas fallados.
    `preguntas` es la lista de preguntas_de_ronda() (en el orden en que se mostraron)."""
    cfg = config(con)
    minimo, meta = float(cfg["puntaje_minimo"]), float(cfg["meta_puntaje"])
    rid = ronda["id"]
    resp = [p for p in preguntas if p["respondida"]]
    n = len(resp)
    total = _conteo(resp)
    # Aciertos que faltaron (o sobraron) para el mínimo y la meta, contando las omisiones como no acertadas
    n_ronda = len(preguntas)
    falta_minimo = math.ceil(minimo / 100 * n_ronda - 1e-9) - total["ok"]
    falta_meta = math.ceil(meta / 100 * n_ronda - 1e-9) - total["ok"]
    valor_pregunta = round(100 / n_ronda, 2) if n_ronda else None

    # Histórico de cada indicador antes de esta ronda
    previo = {r["sesion_id"]: r for r in con.execute("""SELECT p.sesion_id, COUNT(*) n, SUM(r.correcta) ok
        FROM respuestas r JOIN preguntas p ON p.id=r.pregunta_id WHERE r.ronda_id < ? GROUP BY p.sesion_id""", (rid,))}
    pesos = {r["id"]: r["peso"] or 1 for r in con.execute("SELECT id, peso FROM sesiones")}
    indicadores = []
    for sid in dict.fromkeys(p["sesion_id"] for p in resp):
        sub = [p for p in resp if p["sesion_id"] == sid]
        c = _conteo(sub)
        h = previo.get(sid)
        hist = pct(h["ok"], h["n"]) if h and h["n"] >= 5 else None
        indicadores.append({**c, "id": sid, "nombre": sub[0]["sesion"], "peso": pesos.get(sid, 1),
                            "errores": c["n"] - c["ok"], "puntos_perdidos": round((c["n"] - c["ok"]) * 100 / n_ronda, 1),
                            "historico": hist, "cambio": round(c["pct"] - hist, 1) if hist is not None else None})
    indicadores.sort(key=lambda f: (-f["puntos_perdidos"], f["pct"]))

    # Confianza × acierto
    confianza = []
    for conf in ("seguro", "dudoso", "adivine"):
        sub = [p for p in resp if p["confianza"] == conf]
        confianza.append({"confianza": conf, "nombre": NOMBRES_CONFIANZA[conf], **_conteo(sub)})
    sin_conf = [p for p in resp if not p["confianza"]]
    errores_seguro = sum(1 for p in resp if p["confianza"] == "seguro" and not p["acierto"])
    aciertos_fragiles = sum(1 for p in resp if p["confianza"] in ("dudoso", "adivine") and p["acierto"])

    # Ritmo frente a la prueba real y fatiga (acierto por tramos en el orden de la ronda)
    presupuesto = 60 * float(cfg["simulacro_oficial_minutos"]) / int(cfg["simulacro_oficial_preguntas"])
    tiempos = [p["tiempo_seg"] for p in resp if p["tiempo_seg"]]
    tiempo_medio = round(sum(tiempos) / len(tiempos)) if tiempos else None
    rapidas = [p for p in resp if p["tiempo_seg"] and p["tiempo_seg"] < 30]
    lentas = [p for p in resp if p["tiempo_seg"] and p["tiempo_seg"] >= 90]
    # En el orden real en que respondiste (en un simulacro puedes saltar preguntas)
    cronologico = sorted(resp, key=lambda p: p["respuesta_id"])
    tramos = []
    if n >= 9:
        k = 3 if n < 30 else 4
        for i in range(k):
            sub = cronologico[i * n // k:(i + 1) * n // k]
            tramos.append({"l": f"{i * n // k + 1}–{(i + 1) * n // k}", **_conteo(sub),
                           "seg": round(sum(p["tiempo_seg"] or 0 for p in sub) / len(sub))})

    # Primera vez vs. ya vistas antes de esta ronda
    vistas_antes = {r[0] for r in con.execute("SELECT DISTINCT pregunta_id FROM respuestas WHERE ronda_id < ?", (rid,))}
    for p in preguntas:
        p["vista_antes"] = p["id"] in vistas_antes
        p["etiquetas_lista"] = [x.strip() for x in (p["etiquetas"] or "").split(",") if x.strip()]
    nuevas = _conteo([p for p in resp if not p["vista_antes"]])
    repetidas = _conteo([p for p in resp if p["vista_antes"]])

    dificultad = [{"clave": d, "nombre": NOMBRES_DIFICULTAD[d], **_conteo([p for p in resp if (p["dificultad"] or 2) == d])}
                  for d in (1, 2, 3)]

    # Subtemas: etiquetas de las preguntas falladas (las que más se repiten primero)
    subtemas = defaultdict(lambda: {"fallos": 0, "n": 0, "sesion": None})
    for p in resp:
        for e in p["etiquetas_lista"]:
            s = subtemas[e.lower()]
            s["texto"], s["sesion"] = s.get("texto") or e, s["sesion"] or p["sesion"]
            s["n"] += 1
            s["fallos"] += 0 if p["acierto"] else 1
    subtemas_fallados = sorted([s for s in subtemas.values() if s["fallos"]], key=lambda s: (-s["fallos"], -s["n"]))[:12]

    # Evolución: rondas terminadas del mismo modo hasta esta
    evolucion = [{**dict(f), "pct": pct(f["ok"], f["n"]), "actual": f["id"] == rid} for f in con.execute("""
        SELECT ro.id, substr(ro.inicio, 1, 10) fecha, COUNT(r.id) n, COALESCE(SUM(r.correcta), 0) ok
        FROM rondas ro JOIN respuestas r ON r.ronda_id=ro.id
        WHERE ro.modo=? AND ro.id <= ? AND (ro.fin IS NOT NULL OR ro.id=?)
        GROUP BY ro.id ORDER BY ro.id DESC LIMIT 15""", (ronda["modo"], rid, rid))][::-1]

    # Lectura rápida
    lectura = []
    if n and indicadores and indicadores[0]["puntos_perdidos"]:
        top = [f for f in indicadores if f["puntos_perdidos"]][:2]
        lectura.append("Donde más puntos perdiste: " + " y ".join(
            f"{f['nombre']} ({f['errores']} {'error' if f['errores'] == 1 else 'errores'}, −{f['puntos_perdidos']} pts)" for f in top) + ".")
    mejoras = [f for f in indicadores if f["cambio"] is not None and f["n"] >= 3]
    if mejoras:
        mejor = max(mejoras, key=lambda f: f["cambio"])
        peor = min(mejoras, key=lambda f: f["cambio"])
        if mejor["cambio"] >= 10:
            lectura.append(f"Te fue mejor que de costumbre en {mejor['nombre']} ({mejor['pct']:g}% vs. {mejor['historico']:g}% histórico).")
        if peor["cambio"] <= -10:
            lectura.append(f"Te fue peor que de costumbre en {peor['nombre']} ({peor['pct']:g}% vs. {peor['historico']:g}% histórico).")
    if errores_seguro:
        lectura.append(f"{errores_seguro} {'error' if errores_seguro == 1 else 'errores'} con «Seguro»: son conceptos que crees dominar "
                       "pero tienes errados. Son los más valiosos de repasar (filtro «Errores con seguridad»).")
    if aciertos_fragiles:
        lectura.append(f"{aciertos_fragiles} {'acierto fue' if aciertos_fragiles == 1 else 'aciertos fueron'} con duda o adivinando: "
                       "en la prueba podrían convertirse en errores.")
    if nuevas["n"] >= 5 and repetidas["n"] >= 5 and repetidas["pct"] - nuevas["pct"] >= 15:
        lectura.append(f"Aciertas {repetidas['pct']:g}% en preguntas que ya habías visto y {nuevas['pct']:g}% en las nuevas: "
                       "puede que estés recordando respuestas más que dominando el tema.")
    if len(tramos) >= 3 and tramos[0]["pct"] is not None and tramos[-1]["pct"] is not None and tramos[0]["pct"] - tramos[-1]["pct"] >= 15:
        lectura.append(f"Tu acierto bajó de {tramos[0]['pct']:g}% al inicio a {tramos[-1]['pct']:g}% al final: posible fatiga. "
                       "En la prueba real son 5 horas; entrena simulacros completos.")
    if tiempo_medio and tiempo_medio < presupuesto / 3:
        lectura.append(f"Respondiste en {tiempo_medio} s por pregunta de media y la prueba te da ~{round(presupuesto)} s: "
                       "tienes tiempo de sobra para leer el caso con calma.")
    elif tiempo_medio and tiempo_medio > presupuesto:
        lectura.append(f"Respondiste en {tiempo_medio} s por pregunta de media, más que los ~{round(presupuesto)} s de la prueba real: "
                       "practica el ritmo.")
    if rapidas and len(rapidas) >= 3:
        c = _conteo(rapidas)
        if c["pct"] is not None and total["pct"] is not None and c["pct"] < total["pct"] - 10:
            lectura.append(f"En las {c['n']} preguntas que respondiste en menos de 30 s acertaste solo {c['pct']:g}%: "
                           "leer más despacio te daría puntos.")

    return {"total": total, "minimo": minimo, "meta": meta, "falta_minimo": falta_minimo, "falta_meta": falta_meta,
            "valor_pregunta": valor_pregunta, "indicadores": indicadores, "confianza": confianza,
            "sin_confianza": len(sin_conf), "errores_seguro": errores_seguro, "aciertos_fragiles": aciertos_fragiles,
            "presupuesto": round(presupuesto), "tiempo_medio": tiempo_medio, "tramos": tramos,
            "rapidas": _conteo(rapidas), "lentas": _conteo(lentas), "nuevas": nuevas, "repetidas": repetidas,
            "dificultad": dificultad, "subtemas": subtemas_fallados, "evolucion": evolucion, "lectura": lectura,
            "tiempos": [{"i": i + 1, "seg": round(p["tiempo_seg"] or 0), "ok": p["acierto"], "sesion": p["sesion"],
                         "conf": p["confianza"]} for i, p in enumerate(cronologico)]}


# ---------------------------------------------------------------- Informe

def recomendaciones(sesiones, g, calib, extra=None):
    recs = []
    if extra:
        p = extra["proy"]
        if p["puntaje"] is not None:
            frente = ("supera la meta" if p["puntaje"] >= p["meta"] else
                      "aprueba pero está bajo la meta" if p["puntaje"] >= p["minimo"] else "está bajo el mínimo aprobatorio")
            recs.append(f"Tu puntaje estimado en la prueba funcional es **{p['puntaje']}** (±{p['margen']}): {frente} "
                        f"({p['minimo']:g} mínimo, {p['meta']:g} meta).")
        if p["prioridad"]:
            top = ", ".join(f"{f['nombre']} ({f['pct']:g}%)" for f in p["prioridad"][:3])
            recs.append(f"Donde más puntos ganas: {top}. Llevarlos a la meta sumaría unos **{p['ganancia_top3']:g} puntos** al estimado.")
        if p["sin_datos"]:
            recs.append("El estimado no incluye " + ", ".join(f["nombre"] for f in p["sin_datos"])
                        + f": te faltan respuestas allí ({p['cobertura_peso']:g}% del peso de la prueba tiene datos).")
        deb = [e for e in extra["etiquetas"]["debiles"] if e["pct"] < 60][:4]
        if deb:
            recs.append("Subtemas concretos que más fallas: " + ", ".join(f"{e['etiqueta']} ({e['pct']:g}% en {e['n']})" for e in deb) + ".")
        ret = extra["retencion"]
        if ret["persistentes"] >= 3:
            recs.append(f"{ret['persistentes']} veces volviste a fallar una pregunta que ya habías fallado: "
                        "antes de repetirla, relee la explicación y la norma citada.")
        if extra["nuevas_por_dia"]:
            recs.append(f"Para ver todo el banco antes de la prueba necesitas unas **{extra['nuevas_por_dia']} preguntas nuevas por día** "
                        f"(hoy promedias {extra['promedio_dia']} respuestas por día de estudio).")
    debiles = sorted([s for s in sesiones if s["estado"] == "debilidad"], key=lambda s: s["dominio"])
    for s in ([] if extra else debiles[:3]):  # con el análisis completo, la prioridad por puntos ya las cubre
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
    a = analisis_completo(con)
    p, ret, rit = a["proy"], a["retencion"], a["ritmo"]
    L = [f"# Informe de estudio – Concurso DIAN 2676, Gestor I (empleo 236767)",
         f"_Generado: {datetime.now():%Y-%m-%d %H:%M}_", "",
         "## Resumen general", "",
         f"- Preguntas en el banco: **{g['banco']}** (vistas: {g['vistas']}, cobertura {g['cobertura'] or 0}%)",
         f"- Respuestas totales: **{g['respuestas']}** en {g['rondas']} rondas, {g['dias']} días de estudio (racha actual: {g['racha']})",
         f"- Acierto: **{g['pct'] if g['pct'] is not None else '–'}%** · Error: {g['pct_error'] if g['pct_error'] is not None else '–'}%",
         f"- Tiempo promedio por pregunta: {g['tiempo'] or '–'} s", ""]
    if p["puntaje"] is not None:
        L += ["## Puntaje estimado en la prueba funcional", "",
              f"- Estimado: **{p['puntaje']}** ± {p['margen']} (mínimo {p['minimo']:g}, meta {p['meta']:g}); "
              f"últimas {p['ventana']} respuestas de cada indicador, ponderadas por su peso. "
              f"Peso con datos: {p['cobertura_peso']}%.", ""]
        if p["prioridad"]:
            L += ["| Prioridad | Indicador | Peso | Acierto reciente | Puntos que pierdes frente a la meta |", "|---|---|---|---|---|"]
            L += [f"| {i} | {f['nombre']} | {f['peso_pct']}% | {f['pct']}% (n={f['n']}) | {f['brecha']} |"
                  for i, f in enumerate(p["prioridad"], 1)] + [""]
    L += ["## Recomendaciones", ""] + [f"- {r}" for r in recomendaciones(sesiones, g, calib, a)] + [""]
    if a["etiquetas"]["debiles"]:
        L += ["## Subtemas más débiles (etiquetas con al menos 3 respuestas)", "",
              "| Subtema | Indicador | Respuestas | % acierto |", "|---|---|---|---|"]
        L += [f"| {e['etiqueta']} | {e['sesion']} | {e['n']} | {e['pct']}% |" for e in a["etiquetas"]["debiles"]] + [""]
    L += ["## Retención y ritmo", "",
          f"- Acierto en el primer intento: {ret['pct_primero'] if ret['pct_primero'] is not None else '–'}% "
          f"(n={ret['n_primero']}) · en repeticiones: {ret['pct_repetido'] if ret['pct_repetido'] is not None else '–'}% (n={ret['n_repetido']})",
          f"- Al repetir: {ret['recuperadas']} recuperadas, {ret['persistentes']} persistentes, "
          f"{ret['olvidadas']} olvidadas, {ret['consolidadas']} consolidadas"]
    if rit:
        L.append(f"- Ritmo: {rit['media']} s por pregunta (mediana {rit['mediana']} s); presupuesto de la prueba "
                 f"{rit['presupuesto']} s. A ese ritmo, las {rit['n_prueba']} preguntas toman ~{rit['minutos_prueba']} de {rit['minutos_disponibles']} min.")
    L += ["- Acierto por dificultad: " + " · ".join(f"{d['nombre']} {d['pct'] if d['pct'] is not None else '–'}% (n={d['n']})"
                                                     for d in a["dificultad"]), ""]
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

def _escala_100(media):
    """Media en la escala 1–4 → 0–100."""
    return round((media - 1) / 3 * 100)


def _media(valores):
    return sum(valores) / len(valores) if valores else None


def _respuestas_likert(con, condicion, params):
    filas = [dict(r) for r in con.execute(f"""SELECT a.*, r.valor, r.practica_id FROM respuestas_likert r
        JOIN afirmaciones a ON a.id=r.afirmacion_id WHERE {condicion} ORDER BY r.practica_id, r.orden""", params)]
    for f in filas:
        # Disposición: qué tanto la respuesta refleja la conducta deseable (las inversas se cuentan al revés)
        f["disposicion"] = (f["valor"] if f["clave"] == "directa" else 5 - f["valor"]) if f["valor"] else None
    return filas


def _perfil_likert(resp):
    perfil = []
    for prueba, comps in COMPETENCIAS_LIKERT.items():
        for comp in comps:
            items = [f for f in resp if f["competencia"] == comp]
            if not items:
                continue
            directas = [f["valor"] for f in items if f["clave"] == "directa"]
            inversas = [f["valor"] for f in items if f["clave"] == "inversa"]
            disp_d = _media(directas)
            disp_i = 5 - _media(inversas) if inversas else None
            perfil.append({
                "prueba": prueba, "competencia": comp, "n": len(items),
                "n_directas": len(directas), "n_inversas": len(inversas),
                "disposicion": _escala_100(_media([f["disposicion"] for f in items])),
                "disp_directas": _escala_100(disp_d) if directas else None,
                "disp_inversas": _escala_100(disp_i) if inversas else None,
                # Coherencia: las directas y las inversas de una misma competencia deberían dar la misma disposición
                "coherencia": round(100 - abs(disp_d - disp_i) / 3 * 100) if directas and inversas else None,
                # De acuerdo a la vez con conductas deseables y con su contrario: respuesta poco consistente
                "inconsistente": bool(directas and inversas and _media(directas) >= 3 and _media(inversas) >= 3),
            })
    return perfil


def _forma_likert(resp, perfil):
    """Indicadores de la forma de responder (lo que miran las escalas de control)."""
    n = len(resp)
    if not n:
        return {"n": 0, "pct_totalmente": None, "pct_extremos": None, "pct_matiz": None, "disposicion": None,
                "coherencia": None, "por_prueba": {}}
    coherencias = [p["coherencia"] for p in perfil if p["coherencia"] is not None]
    por_prueba = {}
    for prueba in COMPETENCIAS_LIKERT:
        d = [f["disposicion"] for f in resp if f["prueba"] == prueba]
        if d:
            por_prueba[prueba] = _escala_100(_media(d))
    return {
        "n": n,
        "pct_totalmente": round(100 * sum(f["valor"] == 4 for f in resp) / n),
        "pct_extremos": round(100 * sum(f["valor"] in (1, 4) for f in resp) / n),
        "pct_matiz": round(100 * sum(f["valor"] in (2, 3) for f in resp) / n),
        "disposicion": _escala_100(_media([f["disposicion"] for f in resp])),
        "coherencia": round(_media(coherencias)) if coherencias else None,
        "por_prueba": por_prueba,
    }


def _segundos(inicio, fin):
    try:
        return (datetime.fromisoformat(fin) - datetime.fromisoformat(inicio)).total_seconds()
    except (TypeError, ValueError):
        return None


def _plural(n, singular, plural):
    return singular if n == 1 else plural


def analizar_practica(con, practica_id):
    """Perfil de una práctica comportamental/integridad. No hay respuestas correctas: se muestra la disposición
    por competencia, la comparación con las prácticas anteriores y señales que las escalas de control de la
    prueba real podrían detectar."""
    filas = _respuestas_likert(con, "r.practica_id=?", (practica_id,))
    resp = [f for f in filas if f["valor"]]
    perfil = _perfil_likert(resp)
    forma = _forma_likert(resp, perfil)
    n = len(resp)

    # Promedio de las prácticas terminadas anteriores, para comparar
    previas = _respuestas_likert(con, """r.practica_id < ? AND r.valor IS NOT NULL
        AND r.practica_id IN (SELECT id FROM practicas_likert WHERE fin IS NOT NULL)""", (practica_id,))
    previo = {p["competencia"]: p["disposicion"] for p in _perfil_likert(previas)}
    for p in perfil:
        p["previo"] = previo.get(p["competencia"])
        p["cambio"] = p["disposicion"] - p["previo"] if p["previo"] is not None else None

    # Evolución: una fila por práctica terminada (incluida esta)
    evolucion = []
    for pr in con.execute("SELECT * FROM practicas_likert WHERE fin IS NOT NULL OR id=? ORDER BY id",
                          (practica_id,)).fetchall():
        r = _respuestas_likert(con, "r.practica_id=? AND r.valor IS NOT NULL", (pr["id"],))
        if not r:
            continue
        fo = _forma_likert(r, _perfil_likert(r))
        seg = _segundos(pr["inicio"], pr["fin"])
        evolucion.append({"id": pr["id"], "fecha": (pr["inicio"] or "")[:10], "prueba": pr["prueba"],
                          "actual": pr["id"] == practica_id, "seg_item": round(seg / len(r)) if seg else None,
                          **{k: fo[k] for k in ("n", "disposicion", "coherencia", "pct_matiz", "pct_totalmente",
                                                "pct_extremos")}})
    actual = next((e for e in evolucion if e["actual"]), {})

    distribucion = {clave: [sum(f["valor"] == v for f in resp if f["clave"] == clave) for v in (1, 2, 3, 4)]
                    for clave in ("directa", "inversa")}
    for f in filas:
        # Respuestas que se alejan de la conducta deseable: vale la pena releerlas y entender qué evalúan
        f["reflexionar"] = f["disposicion"] is not None and f["disposicion"] <= 2
    n_reflexionar = sum(f["reflexionar"] for f in filas)
    inv_acuerdo = sum(f["clave"] == "inversa" and f["valor"] >= 3 for f in resp)

    alertas = []
    if n and forma["pct_totalmente"] > 70:
        alertas.append(f"Marcaste «Totalmente de acuerdo» en el {forma['pct_totalmente']}% de las afirmaciones. "
                       "La prueba real incluye escalas de control que detectan respuestas exageradamente favorables: "
                       "responde según lo que realmente haces, no según lo que suena ideal.")
    if any(p["inconsistente"] for p in perfil):
        alertas.append("En algunas competencias estuviste de acuerdo con una conducta y también con su contraria. "
                       "Revisa esas afirmaciones: leer con calma cada matiz (por ejemplo, «asumiendo tiempo adicional») evita contradicciones.")

    lectura = []
    if len(perfil) >= 2:
        alto, bajo = max(p["disposicion"] for p in perfil), min(p["disposicion"] for p in perfil)
        if alto > bajo:
            altas = [p["competencia"] for p in perfil if p["disposicion"] == alto]
            bajas = [p["competencia"] for p in perfil if p["disposicion"] == bajo]
            txt_altas = (", ".join(altas) if len(altas) <= 3 else f"{len(altas)} competencias")
            lectura.append(f"Lo más alto: {txt_altas} ({alto}%). Lo más bajo: {', '.join(bajas)} ({bajo}%).")
    if perfil and _media([p["n"] for p in perfil]) < 4:
        lectura.append("Cada competencia tuvo pocas afirmaciones en esta práctica, así que una sola respuesta mueve "
                       "mucho su porcentaje. Compara varias prácticas antes de sacar conclusiones.")
    cambios = [p for p in perfil if p["cambio"] is not None and abs(p["cambio"]) >= 10]
    partes = []
    if cambios and max(p["cambio"] for p in cambios) > 0:
        sube = max(cambios, key=lambda p: p["cambio"])
        partes.append(f"subiste en {sube['competencia']} (+{sube['cambio']} puntos)")
    if cambios and min(p["cambio"] for p in cambios) < 0:
        baja = min(cambios, key=lambda p: p["cambio"])
        partes.append(f"bajaste en {baja['competencia']} ({baja['cambio']} puntos)")
    if partes:
        lectura.append("Frente a tus prácticas anteriores " + " y ".join(partes) + ".")
    if n:
        lectura.append(f"El {forma['pct_matiz']}% de tus respuestas fueron matizadas («De acuerdo» o «En desacuerdo») "
                       f"y el {forma['pct_extremos']}%, extremas.")
    if n_reflexionar:
        lectura.append(f"{n_reflexionar} {_plural(n_reflexionar, 'respuesta se aleja', 'respuestas se alejan')} de la "
                       "conducta que describe la competencia: revísalas abajo con el filtro «Para reflexionar».")
    if inv_acuerdo:
        lectura.append(f"Estuviste de acuerdo con {inv_acuerdo} {_plural(inv_acuerdo, 'afirmación inversa', 'afirmaciones inversas')} "
                       "(describen la conducta contraria a la deseable). Suelen ser las más fáciles de leer mal.")

    return {"items": filas, "perfil": perfil, "n": n, "sin_responder": len(filas) - n,
            "pct_totalmente": forma["pct_totalmente"], "pct_extremos": forma["pct_extremos"], "alertas": alertas,
            "forma": forma, "evolucion": evolucion, "seg_item": actual.get("seg_item"),
            "distribucion": distribucion, "n_reflexionar": n_reflexionar,
            "n_inversas": sum(f["clave"] == "inversa" for f in filas), "lectura": lectura, "hay_previas": bool(previo)}
