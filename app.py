"""Estudio Concurso DIAN – aplicación local. Ejecutar: python app.py"""
import json
import random
import re
import sys
import threading
import webbrowser
from datetime import date, datetime

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template, request,
                   url_for)

import analisis as an
import banco as banco_compartido
from db import (ESCALA_LIKERT, LETRAS, ahora, config, conectar, hash_pregunta,
                importar_datos, importar_pendientes, inicializar, opciones_de, reiniciar_estadisticas,
                sesgo_longitud)

app = Flask(__name__)
app.secret_key = "estudio-local"

MODOS = {
    "aleatorio": "Aleatorio",
    "no_vistas": "Solo no vistas",
    "falladas": "Solo falladas / adivinadas",
    "debilidades": "Enfocado en debilidades",
    "repaso": "Repaso espaciado (pendientes hoy)",
    "simulacro": "Simulacro cronometrado",
    "simulacro_oficial": "Simulacro oficial",
    "repetir": "Repetir falladas de una ronda",
}


@app.template_filter("fecha")
def filtro_fecha(iso):
    if not iso:
        return "–"
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")


@app.template_filter("num")
def filtro_num(v, sufijo=""):
    return "–" if v is None else f"{v:g}{sufijo}"


@app.context_processor
def globales():
    return {"MODOS": MODOS}


def modulos_y_sesiones(con):
    mods = [dict(m) for m in con.execute("SELECT * FROM modulos WHERE vigente=1 ORDER BY orden")]
    for m in mods:
        m["sesiones"] = [dict(s) for s in con.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM preguntas p WHERE p.sesion_id=s.id AND p.activa=1) AS banco "
            "FROM sesiones s WHERE modulo_id=? AND vigente=1 ORDER BY orden", (m["id"],))]
        m["banco"] = sum(s["banco"] for s in m["sesiones"])
    return mods


# ---------------------------------------------------------------- Selección de preguntas

def _filtro_alcance(modulo_id, sesion_id):
    if sesion_id:
        return " AND p.sesion_id=?", [sesion_id]
    if modulo_id:
        return " AND s.modulo_id=?", [modulo_id]
    return "", []


def candidatos(con, modo, modulo_id=None, sesion_id=None):
    filtro, params = _filtro_alcance(modulo_id, sesion_id)
    base = ("SELECT p.id, p.sesion_id FROM preguntas p JOIN sesiones s ON s.id=p.sesion_id "
            "WHERE p.activa=1 AND s.vigente=1" + filtro)
    if modo == "no_vistas":
        return con.execute(base + " AND NOT EXISTS (SELECT 1 FROM respuestas r WHERE r.pregunta_id=p.id)",
                           params).fetchall()
    if modo == "falladas":
        return con.execute(base + """ AND EXISTS (SELECT 1 FROM respuestas r WHERE r.pregunta_id=p.id
            AND r.id=(SELECT MAX(r2.id) FROM respuestas r2 WHERE r2.pregunta_id=p.id)
            AND (r.correcta=0 OR r.confianza='adivine'))""", params).fetchall()
    if modo == "repaso":
        return con.execute(base.replace("WHERE", "JOIN leitner l ON l.pregunta_id=p.id WHERE")
                           + " AND l.proxima<=? ORDER BY l.caja, l.proxima",
                           params + [date.today().isoformat()]).fetchall()
    return con.execute(base, params).fetchall()


def seleccionar(con, modo, cantidad, modulo_id=None, sesion_id=None):
    filas = candidatos(con, modo, modulo_id, sesion_id)
    if modo == "simulacro_oficial":
        return seleccion_estratificada(con, filas, cantidad)
    if modo == "repaso":
        return [f["id"] for f in filas[:cantidad]]
    if modo != "debilidades":
        ids = [f["id"] for f in filas]
        random.shuffle(ids)
        return ids[:cantidad]
    # Debilidades: muestreo ponderado por (100 - dominio) de la sesión, priorizando falladas y no vistas
    dominio = {s["id"]: s["dominio"] for s in an.por_sesion(con)}
    falladas = {f["id"] for f in candidatos(con, "falladas", modulo_id, sesion_id)}
    vistas = {r[0] for r in con.execute("SELECT DISTINCT pregunta_id FROM respuestas")}
    pool = []
    for f in filas:
        d = dominio.get(f["sesion_id"])
        w = (100 - d + 5) if d is not None else 60
        if f["id"] in falladas:
            w *= 2.5
        elif f["id"] not in vistas:
            w *= 1.5
        pool.append((f["id"], w))
    elegidas = []
    while pool and len(elegidas) < cantidad:
        i = random.choices(range(len(pool)), weights=[w for _, w in pool])[0]
        elegidas.append(pool.pop(i)[0])
    return elegidas


def seleccion_estratificada(con, filas, cantidad):
    """Reparte las preguntas entre indicadores según su peso (como la estructura de la prueba real)."""
    pesos = {r["id"]: r["peso"] for r in con.execute("SELECT id, peso FROM sesiones WHERE vigente=1")}
    por_sesion = {}
    for f in filas:
        por_sesion.setdefault(f["sesion_id"], []).append(f["id"])
    for ids in por_sesion.values():
        random.shuffle(ids)
    total_peso = sum(pesos.get(s, 1) for s in por_sesion) or 1
    cuota = {s: min(len(ids), int(cantidad * pesos.get(s, 1) / total_peso)) for s, ids in por_sesion.items()}
    # Reparte el sobrante (redondeos o indicadores con pocas preguntas) entre los que aún tienen disponibles
    while sum(cuota.values()) < min(cantidad, len(filas)):
        s = max((s for s in por_sesion if cuota[s] < len(por_sesion[s])),
                key=lambda s: pesos.get(s, 1) / (cuota[s] + 1))
        cuota[s] += 1
    elegidas = [pid for s, ids in por_sesion.items() for pid in ids[:cuota[s]]]
    random.shuffle(elegidas)
    return elegidas


def crear_ronda(con, modo, ids, alcance, modulo_id=None, sesion_id=None, feedback="inmediato"):
    cfg = config(con)
    limite = None
    if modo == "simulacro":
        feedback = "final"
        limite = int(float(cfg["minutos_por_pregunta_simulacro"]) * 60 * len(ids))
    elif modo == "simulacro_oficial":
        feedback = "final"
        limite = int(float(cfg["simulacro_oficial_minutos"]) * 60)
    cur = con.execute(
        "INSERT INTO rondas (inicio, modo, alcance, modulo_id, sesion_id, cantidad, feedback, tiempo_limite_seg) "
        "VALUES (?,?,?,?,?,?,?,?)", (ahora(), modo, alcance, modulo_id, sesion_id, len(ids), feedback, limite))
    rid = cur.lastrowid
    con.executemany("INSERT INTO ronda_preguntas (ronda_id, pregunta_id, orden) VALUES (?,?,?)",
                    [(rid, pid, i) for i, pid in enumerate(ids)])
    return rid


def opciones_ordenadas(p, ronda_id, barajar):
    ops = [{"orig": l, "texto": t} for l, t in opciones_de(p).items()]
    if barajar:
        random.Random(ronda_id * 100003 + p["id"]).shuffle(ops)
    for letra, o in zip(LETRAS, ops):
        o["letra"] = letra
    return ops


def explicacion_mostrada(explicacion, ops):
    """Las justificaciones vienen marcadas con la letra original ([A], [B], [C]). Como las opciones se barajan,
    se traducen a la letra que ve el usuario y se ordenan por esa letra."""
    mapa = {o["orig"]: o["letra"] for o in ops}
    texto = re.sub(r"\[([ABCD])\]", lambda m: f"[{mapa.get(m.group(1), m.group(1))}]", explicacion or "")
    lineas = texto.split("\n")
    marcadas = [l for l in lineas if re.match(r"\[[ABCD]\]", l)]
    if len(marcadas) > 1:
        resto = [l for l in lineas if l not in marcadas]
        texto = "\n".join(resto + sorted(marcadas))
    return texto


def letra_mostrada(ops, orig):
    return next((o["letra"] for o in ops if o["orig"] == orig), None)


def preguntas_de_ronda(con, rid):
    cfg = config(con)
    barajar = cfg["barajar_opciones"] == "1"
    filas = con.execute("""
        SELECT p.*, s.nombre AS sesion, m.nombre AS modulo, rp.orden,
               r.elegida, r.correcta AS acierto, r.confianza, r.tiempo_seg, r.id AS respuesta_id
        FROM ronda_preguntas rp JOIN preguntas p ON p.id=rp.pregunta_id
        JOIN sesiones s ON s.id=p.sesion_id JOIN modulos m ON m.id=s.modulo_id
        LEFT JOIN respuestas r ON r.ronda_id=rp.ronda_id AND r.pregunta_id=p.id
        WHERE rp.ronda_id=? ORDER BY rp.orden""", (rid,)).fetchall()
    out = []
    for p in filas:
        ops = opciones_ordenadas(p, rid, barajar)
        out.append({**dict(p), "opciones": ops, "explicacion": explicacion_mostrada(p["explicacion"], ops),
                    "letra_correcta": letra_mostrada(ops, p["correcta"]),
                    "letra_elegida": letra_mostrada(ops, p["elegida"]) if p["elegida"] else None,
                    "respondida": p["respuesta_id"] is not None})
    return out


# ---------------------------------------------------------------- Páginas

@app.route("/")
def inicio():
    with conectar() as con:
        sesiones = an.por_sesion(con)
        abiertas = con.execute("""SELECT ro.*, (SELECT COUNT(*) FROM respuestas r WHERE r.ronda_id=ro.id) AS hechas
            FROM rondas ro WHERE fin IS NULL ORDER BY id DESC LIMIT 5""").fetchall()
        cfg = config(con)
        if cfg.get("aviso_reinicio"):
            flash("Se actualizó el banco al formato de la prueba real (300 preguntas de 3 opciones por indicador oficial), "
                  "por eso tus estadísticas empezaron de cero. Tu historial anterior quedó respaldado en "
                  f"respaldos/{cfg['aviso_reinicio']}.", "info")
            con.execute("DELETE FROM config WHERE clave='aviso_reinicio'")
        dias = (date.fromisoformat(cfg["fecha_prueba"]) - date.today()).days
        simulacros = [dict(r) for r in con.execute("""SELECT ro.id, ro.inicio, COUNT(r.id) n, COALESCE(SUM(r.correcta),0) ok
            FROM rondas ro JOIN respuestas r ON r.ronda_id=ro.id WHERE ro.modo='simulacro_oficial' AND ro.fin IS NOT NULL
            GROUP BY ro.id ORDER BY ro.id DESC LIMIT 5""")]
        for x in simulacros:
            x["pct"] = an.pct(x["ok"], x["n"])
        return render_template("inicio.html", g=an.resumen_global(con), sesiones=sesiones,
                               modulos=an.por_modulo(sesiones), evolucion=an.evolucion_rondas(con),
                               calib=an.calibracion(con), abiertas=abiertas, cfg=cfg, dias=dias,
                               simulacros=simulacros)


@app.route("/ronda/nueva", methods=["GET", "POST"])
def nueva_ronda():
    with conectar() as con:
        cfg = config(con)
        if request.method == "POST":
            modo = request.form.get("modo", "aleatorio")
            alcance_val = request.form.get("alcance", "")
            modulo_id = sesion_id = None
            alcance = "Todo el temario"
            if alcance_val.startswith("m:"):
                modulo_id = int(alcance_val[2:])
                alcance = con.execute("SELECT nombre FROM modulos WHERE id=?", (modulo_id,)).fetchone()[0]
            elif alcance_val.startswith("s:"):
                sesion_id = int(alcance_val[2:])
                alcance = con.execute("SELECT nombre FROM sesiones WHERE id=?", (sesion_id,)).fetchone()[0]
            cantidad = max(1, int(request.form.get("cantidad") or cfg["preguntas_por_ronda"]))
            if modo == "simulacro_oficial":
                cantidad, modulo_id, sesion_id = int(cfg["simulacro_oficial_preguntas"]), None, None
                alcance = "Prueba funcional completa"
            ids = seleccionar(con, modo, cantidad, modulo_id, sesion_id)
            if not ids:
                flash(f"No hay preguntas disponibles para «{MODOS[modo]}» en «{alcance}».", "aviso")
                return redirect(url_for("nueva_ronda"))
            if len(ids) < cantidad:
                flash(f"Solo había {len(ids)} preguntas disponibles con ese filtro.", "info")
            rid = crear_ronda(con, modo, ids, alcance, modulo_id, sesion_id, request.form.get("feedback", "inmediato"))
            return redirect(url_for("ronda", rid=rid))
        conteos = {m: len(candidatos(con, m)) for m in ("aleatorio", "no_vistas", "falladas", "repaso")}
        return render_template("nueva_ronda.html", modulos=modulos_y_sesiones(con), cfg=cfg, conteos=conteos,
                               preseleccion=request.args.get("alcance", ""), modo_pre=request.args.get("modo", ""))


@app.route("/api/conteos")
def api_conteos():
    alcance = request.args.get("alcance", "")
    modulo_id = int(alcance[2:]) if alcance.startswith("m:") else None
    sesion_id = int(alcance[2:]) if alcance.startswith("s:") else None
    with conectar() as con:
        return jsonify({m: len(candidatos(con, m, modulo_id, sesion_id))
                        for m in ("aleatorio", "no_vistas", "falladas", "repaso")})


@app.route("/ronda/<int:rid>")
def ronda(rid):
    with conectar() as con:
        r = con.execute("SELECT * FROM rondas WHERE id=?", (rid,)).fetchone()
        if not r:
            abort(404)
        if r["fin"]:
            return redirect(url_for("resultado", rid=rid))
        return render_template("ronda.html", ronda=r)


@app.route("/api/ronda/<int:rid>")
def api_ronda(rid):
    with conectar() as con:
        r = con.execute("SELECT * FROM rondas WHERE id=?", (rid,)).fetchone()
        if not r:
            abort(404)
        ps = []
        for p in preguntas_de_ronda(con, rid):
            item = {k: p[k] for k in ("id", "contexto", "enunciado", "sesion", "modulo", "dificultad",
                                      "revisar", "respondida")}
            item["opciones"] = [{"letra": o["letra"], "orig": o["orig"], "texto": o["texto"]} for o in p["opciones"]]
            if p["respondida"]:
                item.update(elegida=p["elegida"], acierto=bool(p["acierto"]), confianza=p["confianza"])
                if r["feedback"] == "inmediato":
                    item.update(correcta=p["correcta"], explicacion=p["explicacion"], norma=p["norma"])
            ps.append(item)
        transcurrido = (datetime.now() - datetime.fromisoformat(r["inicio"])).total_seconds()
        return jsonify({"ronda": dict(r), "preguntas": ps, "transcurrido": transcurrido})


@app.post("/api/ronda/<int:rid>/responder")
def api_responder(rid):
    d = request.get_json()
    pid = int(d["pregunta_id"])
    elegida = d.get("elegida")
    confianza = d.get("confianza") if d.get("confianza") in an.PESO_CONFIANZA else None
    with conectar() as con:
        r = con.execute("SELECT * FROM rondas WHERE id=?", (rid,)).fetchone()
        if not r or r["fin"]:
            return jsonify({"error": "La ronda ya terminó"}), 400
        if not con.execute("SELECT 1 FROM ronda_preguntas WHERE ronda_id=? AND pregunta_id=?", (rid, pid)).fetchone():
            abort(400)
        p = con.execute("SELECT * FROM preguntas WHERE id=?", (pid,)).fetchone()
        ops = opciones_ordenadas(p, rid, config(con)["barajar_opciones"] == "1")
        acierto = int(elegida == p["correcta"])
        con.execute("INSERT INTO respuestas (ronda_id, pregunta_id, elegida, correcta, confianza, tiempo_seg, fecha) "
                    "VALUES (?,?,?,?,?,?,?) ON CONFLICT(ronda_id, pregunta_id) DO NOTHING",
                    (rid, pid, elegida, acierto, confianza, d.get("tiempo"), ahora()))
        an.leitner_actualizar(con, pid, acierto, confianza)
        out = {"acierto": bool(acierto)}
        if r["feedback"] == "inmediato":
            out.update(correcta=p["correcta"], explicacion=explicacion_mostrada(p["explicacion"], ops), norma=p["norma"])
        return jsonify(out)


@app.post("/api/ronda/<int:rid>/finalizar")
def api_finalizar(rid):
    d = request.get_json(silent=True) or {}
    with conectar() as con:
        r = con.execute("SELECT * FROM rondas WHERE id=?", (rid,)).fetchone()
        if not r:
            abort(404)
        if not r["fin"]:
            if d.get("sin_responder_como_error"):
                pendientes = con.execute("""SELECT pregunta_id FROM ronda_preguntas rp WHERE ronda_id=?
                    AND NOT EXISTS (SELECT 1 FROM respuestas x WHERE x.ronda_id=rp.ronda_id AND x.pregunta_id=rp.pregunta_id)""",
                                         (rid,)).fetchall()
                for (pid,) in pendientes:
                    con.execute("INSERT INTO respuestas (ronda_id, pregunta_id, elegida, correcta, confianza, tiempo_seg, fecha) "
                                "VALUES (?,?,NULL,0,NULL,NULL,?)", (rid, pid, ahora()))
                    an.leitner_actualizar(con, pid, 0, None)
            con.execute("UPDATE rondas SET fin=? WHERE id=?", (ahora(), rid))
            an.guardar_snapshot(con, rid)
            an.generar_informe_md(con)
    return jsonify({"ok": True, "url": url_for("resultado", rid=rid)})


@app.route("/ronda/<int:rid>/resultado")
def resultado(rid):
    with conectar() as con:
        r = con.execute("SELECT * FROM rondas WHERE id=?", (rid,)).fetchone()
        if not r:
            abort(404)
        ps = preguntas_de_ronda(con, rid)
        resp = [p for p in ps if p["respondida"]]
        ok = sum(p["acierto"] for p in resp)
        tiempo_total = (datetime.fromisoformat(r["fin"] or ahora()) - datetime.fromisoformat(r["inicio"])).total_seconds()
        por_ses = {}
        for p in resp:
            s = por_ses.setdefault(p["sesion"], {"n": 0, "ok": 0})
            s["n"] += 1
            s["ok"] += p["acierto"]
        g = an.resumen_global(con)
        return render_template("resultado.html", ronda=r, preguntas=ps, n=len(resp), ok=ok,
                               pct=an.pct(ok, len(resp)), tiempo_total=tiempo_total, por_sesion=por_ses,
                               global_pct=g["pct"], fallos=[p["id"] for p in resp if not p["acierto"]],
                               conf_nombres=an.NOMBRES_CONFIANZA, cfg=config(con))


@app.post("/ronda/<int:rid>/repetir")
def repetir(rid):
    with conectar() as con:
        ids = [r[0] for r in con.execute("SELECT pregunta_id FROM respuestas WHERE ronda_id=? AND correcta=0", (rid,))]
        if not ids:
            flash("Esa ronda no tiene preguntas falladas.", "info")
            return redirect(url_for("resultado", rid=rid))
        random.shuffle(ids)
        nid = crear_ronda(con, "repetir", ids, f"Falladas de la ronda #{rid}")
    return redirect(url_for("ronda", rid=nid))


@app.route("/rondas")
def historial():
    with conectar() as con:
        filas = con.execute("""SELECT ro.*, COUNT(r.id) AS n, COALESCE(SUM(r.correcta),0) AS ok,
            AVG(r.tiempo_seg) AS tprom FROM rondas ro LEFT JOIN respuestas r ON r.ronda_id=ro.id
            GROUP BY ro.id ORDER BY ro.id DESC""").fetchall()
        return render_template("historial.html", rondas=[{**dict(f), "pct": an.pct(f["ok"], f["n"])} for f in filas])


@app.post("/ronda/<int:rid>/eliminar")
def eliminar_ronda(rid):
    with conectar() as con:
        con.execute("DELETE FROM respuestas WHERE ronda_id=?", (rid,))
        con.execute("DELETE FROM ronda_preguntas WHERE ronda_id=?", (rid,))
        con.execute("DELETE FROM snapshots WHERE ronda_id=?", (rid,))
        con.execute("DELETE FROM rondas WHERE id=?", (rid,))
    flash(f"Ronda #{rid} eliminada.", "info")
    return redirect(url_for("historial"))


# ---------------------------------------------------------------- Banco de preguntas

@app.route("/banco")
def banco():
    q = request.args.get("q", "").strip()
    sesion = request.args.get("sesion", "")
    estado = request.args.get("estado", "")
    sql = """SELECT p.*, s.nombre AS sesion, s.codigo AS sesion_codigo,
               (SELECT COUNT(*) FROM respuestas r WHERE r.pregunta_id=p.id) AS intentos,
               (SELECT SUM(correcta) FROM respuestas r WHERE r.pregunta_id=p.id) AS aciertos
             FROM preguntas p JOIN sesiones s ON s.id=p.sesion_id WHERE 1=1"""
    params = []
    if q:
        sql += " AND (p.enunciado LIKE ? OR p.contexto LIKE ? OR p.norma LIKE ? OR p.etiquetas LIKE ?)"
        params += [f"%{q}%"] * 4
    if sesion:
        sql += " AND s.codigo=?"
        params.append(sesion)
    if estado == "revisar":
        sql += " AND p.revisar=1"
    elif estado == "inactivas":
        sql += " AND p.activa=0"
    elif estado == "nunca":
        sql += " AND NOT EXISTS (SELECT 1 FROM respuestas r WHERE r.pregunta_id=p.id)"
    if estado != "inactivas":
        sql += " AND p.activa=1 AND s.vigente=1"
    sql += " ORDER BY s.modulo_id, s.orden, p.id"
    with conectar() as con:
        filas = con.execute(sql, params).fetchall()
        if estado == "sesgo":
            filas = [p for p in filas if es_sesgada(p)]
        activas = con.execute("SELECT * FROM preguntas WHERE activa=1").fetchall()
        sesgadas = sum(es_sesgada(p) for p in activas)
        return render_template("banco.html", preguntas=filas, modulos=modulos_y_sesiones(con),
                               q=q, sesion=sesion, estado=estado, total=len(activas),
                               sesgadas=sesgadas, pct_sesgo=an.pct(sesgadas, len(activas)))


def es_sesgada(p):
    return sesgo_longitud(opciones_de(p), p["correcta"])


@app.post("/importar")
def importar():
    with conectar() as con:
        sync = banco_compartido.sincronizar(con)
        banco_compartido.sincronizar_likert(con)
    if any(sync[k] for k in ("nuevas", "actualizadas", "retiradas")) or sync["errores"]:
        flash(resumen_sync(sync), "aviso" if sync["errores"] else "ok")
    resultados = importar_pendientes()
    archivo = request.files.get("archivo")
    if archivo and archivo.filename:
        try:
            datos = json.loads(archivo.read().decode("utf-8"))
            with conectar() as con:
                res = importar_datos(con, datos, archivo.filename)
            res["archivo"] = archivo.filename
            resultados.append(res)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            resultados.append({"archivo": archivo.filename, "importadas": 0, "duplicadas": 0,
                               "errores": [str(e)], "sesgo": []})
    if not resultados and not any(sync[k] for k in ("nuevas", "actualizadas", "retiradas")):
        flash("El banco ya estaba sincronizado y no había archivos nuevos en preguntas/importar.", "info")
    for r in resultados:
        msg = f"{r['archivo']}: {r['importadas']} importadas, {r['duplicadas']} duplicadas"
        if r["errores"]:
            msg += f", {len(r['errores'])} con error ({'; '.join(r['errores'][:5])})"
        if r["sesgo"]:
            msg += f". Ojo: en {len(r['sesgo'])} la correcta es mucho más larga que las demás (n.º {', '.join(map(str, r['sesgo'][:10]))})"
        flash(msg, "aviso" if r["errores"] or r["sesgo"] else "ok")
    return redirect(request.referrer or url_for("banco"))


def resumen_sync(r):
    msg = (f"Banco sincronizado: {r['nuevas']} preguntas nuevas, {r['actualizadas']} actualizadas, "
           f"{r['retiradas']} retiradas")
    if r["errores"]:
        msg += f", {len(r['errores'])} con error ({'; '.join(r['errores'][:5])})"
    return msg


def modo_autor(con):
    return config(con).get("modo_autor") == "1"


def _form_pregunta():
    f = request.form
    return {
        "sesion_id": int(f["sesion_id"]), "contexto": f.get("contexto", "").strip(),
        "enunciado": f["enunciado"].strip(),
        "opcion_a": f["opcion_a"].strip(), "opcion_b": f["opcion_b"].strip(),
        "opcion_c": f["opcion_c"].strip(), "opcion_d": f.get("opcion_d", "").strip() or None,
        "correcta": f["correcta"], "explicacion": f["explicacion"].strip(), "norma": f.get("norma", "").strip(),
        "dificultad": int(f.get("dificultad") or 2), "etiquetas": f.get("etiquetas", "").strip(),
        "activa": 1 if f.get("activa") else 0, "revisar": 1 if f.get("revisar") else 0,
        "nota_revision": f.get("nota_revision", "").strip(),
    }


@app.route("/pregunta/nueva", methods=["GET", "POST"])
@app.route("/pregunta/<int:pid>/editar", methods=["GET", "POST"])
def editar_pregunta(pid=None):
    with conectar() as con:
        if request.method == "POST":
            d = _form_pregunta()
            d["hash"] = hash_pregunta(d["enunciado"], d["contexto"])
            otro = con.execute("SELECT id FROM preguntas WHERE hash=?", (d["hash"],)).fetchone()
            if otro and otro["id"] != pid:
                flash(f"Ya existe una pregunta idéntica (#{otro['id']}).", "aviso")
                return redirect(request.url)
            cols = list(d)
            if pid:
                con.execute(f"UPDATE preguntas SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                            [d[c] for c in cols] + [pid])
                flash(f"Pregunta #{pid} actualizada.", "ok")
            else:
                cur = con.execute(f"INSERT INTO preguntas ({', '.join(cols)}, origen, creada) VALUES "
                                  f"({', '.join('?' * len(cols))}, 'manual', ?)", [d[c] for c in cols] + [ahora()])
                pid = cur.lastrowid
                flash(f"Pregunta #{pid} creada.", "ok")
            if modo_autor(con):
                uid = banco_compartido.guardar_pregunta(con, pid)
                flash(f"Guardada en banco/ como {uid}: quedará incluida en la próxima publicación.", "info")
            return redirect(request.form.get("volver") or url_for("banco"))
        p = con.execute("SELECT * FROM preguntas WHERE id=?", (pid,)).fetchone() if pid else None
        if pid and not p:
            abort(404)
        historial_p = con.execute("SELECT r.*, ro.modo FROM respuestas r JOIN rondas ro ON ro.id=r.ronda_id "
                                  "WHERE pregunta_id=? ORDER BY r.id DESC", (pid,)).fetchall() if pid else []
        return render_template("pregunta_form.html", p=p, modulos=modulos_y_sesiones(con),
                               historial=historial_p, volver=request.referrer,
                               conf_nombres=an.NOMBRES_CONFIANZA, autor=modo_autor(con))


@app.post("/api/pregunta/<int:pid>/revisar")
def api_revisar(pid):
    d = request.get_json(silent=True) or {}
    with conectar() as con:
        con.execute("UPDATE preguntas SET revisar=?, nota_revision=COALESCE(?, nota_revision) WHERE id=?",
                    (1 if d.get("revisar", True) else 0, d.get("nota"), pid))
    return jsonify({"ok": True})


@app.post("/pregunta/<int:pid>/activa")
def toggle_activa(pid):
    with conectar() as con:
        con.execute("UPDATE preguntas SET activa=1-activa WHERE id=?", (pid,))
    return redirect(request.referrer or url_for("banco"))


@app.post("/pregunta/<int:pid>/eliminar")
def eliminar_pregunta(pid):
    with conectar() as con:
        uid = con.execute("SELECT uid FROM preguntas WHERE id=?", (pid,)).fetchone()["uid"]
        if uid and modo_autor(con):
            banco_compartido.quitar_pregunta(uid)
            flash(f"{uid} se quitó de banco/: dejará de aparecer a los demás en la próxima publicación.", "info")
        elif uid:
            flash("Esta pregunta viene del banco compartido: se desactivó solo en tu copia.", "info")
            con.execute("UPDATE preguntas SET activa=0 WHERE id=?", (pid,))
            return redirect(url_for("banco"))
        if con.execute("SELECT 1 FROM respuestas WHERE pregunta_id=?", (pid,)).fetchone():
            flash("La pregunta tiene respuestas registradas: se desactivó en lugar de eliminarse para no perder historial.", "info")
            con.execute("UPDATE preguntas SET activa=0 WHERE id=?", (pid,))
        else:
            con.execute("DELETE FROM leitner WHERE pregunta_id=?", (pid,))
            con.execute("DELETE FROM preguntas WHERE id=?", (pid,))
            flash(f"Pregunta #{pid} eliminada.", "ok")
    return redirect(url_for("banco"))


# ---------------------------------------------------------------- Informe y configuración

@app.route("/informe")
def informe():
    with conectar() as con:
        sesiones = an.por_sesion(con)
        g = an.resumen_global(con)
        calib = an.calibracion(con)
        an.generar_informe_md(con)
        return render_template("informe.html", g=g, sesiones=sesiones, calib=calib,
                               recs=an.recomendaciones(sesiones, g, calib),
                               falladas=an.mas_falladas(con, 15), seguras=an.errores_con_seguridad(con, 10),
                               hist=an.historial_snapshots(con), cfg=config(con))


@app.route("/informe.md")
def informe_md():
    with conectar() as con:
        texto = an.generar_informe_md(con)
    return Response(texto, mimetype="text/markdown",
                    headers={"Content-Disposition": f"attachment; filename=informe_{date.today()}.md"})


@app.route("/config", methods=["GET", "POST"])
def configuracion():
    with conectar() as con:
        if request.method == "POST":
            for k in ("preguntas_por_ronda", "minutos_por_pregunta_simulacro", "simulacro_oficial_preguntas",
                      "simulacro_oficial_minutos", "fecha_prueba", "puntaje_minimo", "meta_puntaje",
                      "umbral_fortaleza", "umbral_debilidad", "minimo_respuestas_analisis"):
                if request.form.get(k):
                    con.execute("UPDATE config SET valor=? WHERE clave=?", (request.form[k], k))
            for k in ("barajar_opciones", "modo_autor", "mostrar_resumen_prueba"):
                con.execute("UPDATE config SET valor=? WHERE clave=?", ("1" if request.form.get(k) else "0", k))
            flash("Configuración guardada.", "ok")
            return redirect(url_for("configuracion"))
        return render_template("config.html", cfg=config(con), modulos=modulos_y_sesiones(con))


@app.post("/config/reiniciar")
def reiniciar():
    if request.form.get("confirmar") != "REINICIAR":
        flash("Para reiniciar escribe REINICIAR en la casilla de confirmación.", "aviso")
        return redirect(url_for("configuracion"))
    respaldo = reiniciar_estadisticas()
    flash(f"Estadísticas reiniciadas. Se guardó un respaldo en respaldos/{respaldo.name}.", "ok")
    return redirect(url_for("inicio"))


# ---------------------------------------------------------------- Práctica comportamental e integridad (Likert)

@app.route("/practica", methods=["GET", "POST"])
def practica_nueva():
    with conectar() as con:
        if request.method == "POST":
            prueba = request.form.get("prueba", "ambas")
            cantidad = max(1, int(request.form.get("cantidad") or 30))
            filtro = "" if prueba == "ambas" else " AND prueba=?"
            ids = [r[0] for r in con.execute(f"SELECT id FROM afirmaciones WHERE activa=1{filtro}",
                                             [] if prueba == "ambas" else [prueba])]
            if not ids:
                flash("No hay afirmaciones disponibles todavía.", "aviso")
                return redirect(url_for("practica_nueva"))
            random.shuffle(ids)
            ids = ids[:cantidad]
            pid = con.execute("INSERT INTO practicas_likert (inicio, prueba, cantidad) VALUES (?,?,?)",
                              (ahora(), prueba, len(ids))).lastrowid
            con.executemany("INSERT INTO respuestas_likert (practica_id, afirmacion_id, orden) VALUES (?,?,?)",
                            [(pid, aid, i) for i, aid in enumerate(ids)])
            return redirect(url_for("practica", pid=pid))
        disponibles = {r["prueba"]: r["n"] for r in con.execute(
            "SELECT prueba, COUNT(*) n FROM afirmaciones WHERE activa=1 GROUP BY prueba")}
        anteriores = con.execute("""SELECT pl.*, (SELECT COUNT(valor) FROM respuestas_likert r WHERE r.practica_id=pl.id) hechas
            FROM practicas_likert pl ORDER BY id DESC LIMIT 10""").fetchall()
        return render_template("practica_nueva.html", disponibles=disponibles, anteriores=anteriores)


@app.route("/practica/<int:pid>", methods=["GET", "POST"])
def practica(pid):
    with conectar() as con:
        pr = con.execute("SELECT * FROM practicas_likert WHERE id=?", (pid,)).fetchone()
        if not pr:
            abort(404)
        if request.method == "POST":
            for k, v in request.form.items():
                if k.startswith("a") and v in ("1", "2", "3", "4"):
                    con.execute("UPDATE respuestas_likert SET valor=?, fecha=? WHERE practica_id=? AND afirmacion_id=?",
                                (int(v), ahora(), pid, int(k[1:])))
            con.execute("UPDATE practicas_likert SET fin=? WHERE id=?", (ahora(), pid))
            return redirect(url_for("practica_resultado", pid=pid))
        items = con.execute("""SELECT a.*, r.valor FROM respuestas_likert r JOIN afirmaciones a ON a.id=r.afirmacion_id
            WHERE r.practica_id=? ORDER BY r.orden""", (pid,)).fetchall()
        return render_template("practica.html", pr=pr, items=items, escala=ESCALA_LIKERT)


@app.route("/practica/<int:pid>/resultado")
def practica_resultado(pid):
    with conectar() as con:
        pr = con.execute("SELECT * FROM practicas_likert WHERE id=?", (pid,)).fetchone()
        if not pr:
            abort(404)
        return render_template("practica_resultado.html", pr=pr, r=an.analizar_practica(con, pid), escala=ESCALA_LIKERT)


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    respaldo = inicializar()
    if respaldo:
        print(f"Nueva versión del banco: estadísticas reiniciadas (respaldo en respaldos/{respaldo.name}).")
    with conectar() as con:
        sync = banco_compartido.sincronizar(con)
        sync_likert = banco_compartido.sincronizar_likert(con)
    print(resumen_sync(sync))
    for e in sync["errores"] + sync_likert["errores"]:
        print("   ", e)
    for r in importar_pendientes():
        print(f"Importado {r['archivo']}: {r['importadas']} nuevas, {r['duplicadas']} duplicadas, "
              f"{len(r['errores'])} errores, {len(r['sesgo'])} con sesgo de longitud")
        for e in r["errores"]:
            print("   ", e)
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(port=5000, debug=False)
