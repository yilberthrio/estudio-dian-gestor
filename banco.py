"""Banco de preguntas versionado: carpeta banco/, un JSON por sesión.

Es lo que se publica en GitHub. El progreso de cada persona (respuestas, rondas, repaso, marcas)
vive aparte en estudio.db, que no se sube. Al iniciar, la app sincroniza banco/ -> estudio.db.
En «modo autor» los cambios hechos desde la app (editar, importar, eliminar) se escriben en banco/.
"""
import json
import sqlite3

from db import BASE, COMPETENCIAS_LIKERT, _validar, ahora, hash_pregunta, opciones_de

DIR_BANCO = BASE / "banco"
DIR_LIKERT = DIR_BANCO / "likert"


def _ruta(codigo):
    return DIR_BANCO / f"{codigo}.json"


def leer(codigo):
    ruta = _ruta(codigo)
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return {"sesion": codigo, "preguntas": []}


def escribir(codigo, data):
    DIR_BANCO.mkdir(exist_ok=True)
    _ruta(codigo).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def leer_todo():
    return {r.stem: json.loads(r.read_text(encoding="utf-8")) for r in sorted(DIR_BANCO.glob("*.json"))}


def _a_json(p, uid):
    return {
        "id": uid,
        "contexto": p["contexto"] or "",
        "enunciado": p["enunciado"],
        "opciones": opciones_de(p),
        "correcta": p["correcta"],
        "explicacion": p["explicacion"],
        "norma": p["norma"] or "",
        "dificultad": p["dificultad"],
        "etiquetas": [e.strip() for e in (p["etiquetas"] or "").split(",") if e.strip()],
        "origen": p["origen"] or "",
    }


def _siguiente_uid(con, codigo, todos):
    usados = {r[0] for r in con.execute("SELECT uid FROM preguntas WHERE uid IS NOT NULL")}
    usados |= {q["id"] for data in todos.values() for q in data["preguntas"]}
    n = max([int(u.rsplit("-", 1)[1]) for u in usados
             if u.startswith(codigo + "-") and u.rsplit("-", 1)[1].isdigit()] or [0])
    return f"{codigo}-{n + 1:03d}"


def guardar_pregunta(con, pid, todos=None, escribir_archivos=True):
    """Escribe (o actualiza) en banco/ la pregunta pid de la BD, asignándole uid si no tiene."""
    p = con.execute("SELECT p.*, s.codigo FROM preguntas p JOIN sesiones s ON s.id=p.sesion_id WHERE p.id=?",
                    (pid,)).fetchone()
    todos = leer_todo() if todos is None else todos
    uid = p["uid"] or _siguiente_uid(con, p["codigo"], todos)
    if not p["uid"]:
        con.execute("UPDATE preguntas SET uid=? WHERE id=?", (uid, pid))
    tocados = set()
    for codigo, data in todos.items():  # si cambió de sesión, sale del archivo anterior
        if codigo != p["codigo"] and any(q["id"] == uid for q in data["preguntas"]):
            data["preguntas"] = [q for q in data["preguntas"] if q["id"] != uid]
            tocados.add(codigo)
    data = todos.setdefault(p["codigo"], {"sesion": p["codigo"], "preguntas": []})
    nueva = _a_json(p, uid)
    for i, q in enumerate(data["preguntas"]):
        if q["id"] == uid:
            data["preguntas"][i] = nueva
            break
    else:
        data["preguntas"].append(nueva)
    tocados.add(p["codigo"])
    if escribir_archivos:
        for codigo in tocados:
            escribir(codigo, todos[codigo])
    return uid


def guardar_varias(con, pids):
    todos = leer_todo()
    for pid in pids:
        guardar_pregunta(con, pid, todos, escribir_archivos=False)
    codigos = {r[0] for r in con.execute(
        f"SELECT DISTINCT s.codigo FROM preguntas p JOIN sesiones s ON s.id=p.sesion_id "
        f"WHERE p.id IN ({','.join('?' * len(pids))})", pids)}
    for codigo in codigos:
        escribir(codigo, todos[codigo])


def quitar_pregunta(uid):
    for codigo, data in leer_todo().items():
        antes = len(data["preguntas"])
        data["preguntas"] = [q for q in data["preguntas"] if q["id"] != uid]
        if len(data["preguntas"]) != antes:
            escribir(codigo, data)


def exportar_todo(con):
    """Vuelca todas las preguntas de la BD a banco/ (se usa una vez, al migrar a este esquema)."""
    todos = leer_todo()
    filas = con.execute("SELECT p.id FROM preguntas p JOIN sesiones s ON s.id=p.sesion_id "
                        "JOIN modulos m ON m.id=s.modulo_id ORDER BY m.orden, s.orden, p.id").fetchall()
    for (pid,) in filas:
        guardar_pregunta(con, pid, todos, escribir_archivos=False)
    for codigo, data in todos.items():
        escribir(codigo, data)
    return len(filas)


def sincronizar(con):
    """Aplica banco/ a la BD local: agrega nuevas, actualiza editadas y desactiva las retiradas.
    No toca respuestas, rondas, repaso ni las marcas personales (activa/revisar)."""
    res = {"nuevas": 0, "actualizadas": 0, "retiradas": 0, "errores": []}
    todos = leer_todo()
    if not todos:
        return res
    sesiones = {r["codigo"]: r["id"] for r in con.execute("SELECT id, codigo FROM sesiones WHERE vigente=1")}
    vistos = set()
    for codigo, data in todos.items():
        for q in data.get("preguntas", []):
            uid = q.get("id")
            fila, err = _validar(q, sesiones, codigo)
            if err or not uid:
                res["errores"].append(f"banco/{codigo}.json {uid or '(sin id)'}: {err or 'falta id'}")
                continue
            vistos.add(uid)
            fila["hash"] = hash_pregunta(fila["enunciado"], fila["contexto"])
            actual = (con.execute("SELECT * FROM preguntas WHERE uid=?", (uid,)).fetchone()
                      or con.execute("SELECT * FROM preguntas WHERE hash=? AND uid IS NULL", (fila["hash"],)).fetchone())
            try:
                if actual:
                    cambios = {k: v for k, v in fila.items() if actual[k] != v}
                    if cambios or actual["uid"] != uid:
                        cambios["uid"] = uid
                        con.execute(f"UPDATE preguntas SET {', '.join(k + '=?' for k in cambios)} WHERE id=?",
                                    [*cambios.values(), actual["id"]])
                        res["actualizadas"] += len(cambios) > 1
                else:
                    fila.update(uid=uid, origen=q.get("origen") or f"banco/{codigo}.json", creada=ahora())
                    con.execute(f"INSERT INTO preguntas ({', '.join(fila)}) VALUES ({', '.join('?' * len(fila))})",
                                list(fila.values()))
                    res["nuevas"] += 1
            except sqlite3.IntegrityError as e:
                res["errores"].append(f"{uid}: {e}")
    for r in con.execute("SELECT id, uid FROM preguntas WHERE uid IS NOT NULL AND activa=1").fetchall():
        if r["uid"] not in vistos:
            con.execute("UPDATE preguntas SET activa=0 WHERE id=?", (r["id"],))
            res["retiradas"] += 1
    return res


def sincronizar_likert(con):
    """Aplica banco/likert/*.json (afirmaciones de la práctica comportamental y de integridad) a la BD."""
    res = {"nuevas": 0, "actualizadas": 0, "retiradas": 0, "errores": []}
    archivos = sorted(DIR_LIKERT.glob("*.json"))
    if not archivos:
        return res
    vistos = set()
    for ruta in archivos:
        data = json.loads(ruta.read_text(encoding="utf-8"))
        prueba = data.get("prueba")
        for a in data.get("afirmaciones", []):
            uid, comp = a.get("id"), a.get("competencia")
            if prueba not in COMPETENCIAS_LIKERT or comp not in COMPETENCIAS_LIKERT[prueba] or not uid or not a.get("texto"):
                res["errores"].append(f"likert/{ruta.name} {uid or '(sin id)'}: prueba, competencia, id o texto inválidos")
                continue
            vistos.add(uid)
            fila = {"prueba": prueba, "competencia": comp, "nivel": a.get("nivel"), "texto": a["texto"].strip(),
                    "clave": a.get("clave", "directa"), "conducta": a.get("conducta", "")}
            actual = con.execute("SELECT * FROM afirmaciones WHERE uid=?", (uid,)).fetchone()
            if actual:
                cambios = {k: v for k, v in fila.items() if actual[k] != v}
                if cambios or not actual["activa"]:
                    cambios["activa"] = 1
                    con.execute(f"UPDATE afirmaciones SET {', '.join(k + '=?' for k in cambios)} WHERE id=?",
                                [*cambios.values(), actual["id"]])
                    res["actualizadas"] += 1
            else:
                fila["uid"] = uid
                con.execute(f"INSERT INTO afirmaciones ({', '.join(fila)}) VALUES ({', '.join('?' * len(fila))})",
                            list(fila.values()))
                res["nuevas"] += 1
    for r in con.execute("SELECT id, uid FROM afirmaciones WHERE activa=1").fetchall():
        if r["uid"] not in vistos:
            con.execute("UPDATE afirmaciones SET activa=0 WHERE id=?", (r["id"],))
            res["retiradas"] += 1
    return res
