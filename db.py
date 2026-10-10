"""Base de datos SQLite: esquema, catálogo de módulos/sesiones e importador de preguntas."""
import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
DB_PATH = BASE / "estudio.db"
DIR_IMPORTAR = BASE / "preguntas" / "importar"
DIR_IMPORTADAS = BASE / "preguntas" / "importadas"
DIR_INFORMES = BASE / "informes"

LETRAS = ("A", "B", "C", "D")

# Catálogo basado en el Manual de Funciones: Gestor I - AT-FL-3008 (Fiscalización y liquidación)
CATALOGO = [
    ("M1", "Funcionales básicas", "Ejes comunes a los empleos de la DIAN", [
        ("constitucion", "Constitución Política", "Derechos fundamentales, principios y estructura del Estado"),
        ("funcion-publica", "Principios de la función pública", "Art. 209 C.P., Ley 489 de 1998, carrera administrativa"),
        ("integridad", "Código de Buen Gobierno e Integridad", "Valores del servicio público y conflicto de intereses"),
        ("cpaca", "CPACA – Ley 1437 de 2011", "Títulos I, II, III (caps. I y V a VIII): principios, derecho de petición, procedimiento administrativo general"),
        ("transparencia", "Ley de Transparencia", "Ley 1712 de 2014: acceso a la información pública"),
        ("gestion-documental", "Gestión documental", "Ley 594 de 2000, archivos, TRD, ciclo vital del documento"),
        ("mipg", "Modelo Integrado de Planeación y Gestión", "MIPG: dimensiones, políticas, líneas de defensa"),
        ("pqrsf", "PQRSF y servicio al ciudadano", "Sistema PQRSF, términos, políticas de servicio al ciudadano"),
        ("evasion-elusion", "Evasión, elusión y contrabando", "Conceptos, diferencias, abuso en materia tributaria"),
        ("herramientas-informaticas", "Herramientas informáticas", "Ofimática, hojas de cálculo, seguridad de la información"),
    ]),
    ("M2", "Funcionales específicas", "Ejes propios de Fiscalización y liquidación", [
        ("sistema-tac", "Sistema tributario, aduanero y cambiario", "Generalidades: tributos, principios, obligaciones, actores"),
        ("fiscalizacion-intro", "Introducción a la fiscalización y liquidación", "Etapas, actos, términos del proceso de fiscalización"),
        ("determinacion-control", "Determinación y control tributario", "Liquidaciones oficiales, sanciones, firmeza, emplazamientos"),
        ("regimen-cambiario", "Régimen cambiario (competencia DIAN)", "Operaciones de cambio, canalización, infracciones cambiarias"),
        ("fiscalizacion-internacional", "Fiscalización internacional", "Precios de transferencia, intercambio de información, CDI"),
        ("fiscalizacion-aduanera", "Fiscalización aduanera", "Decreto 1165 de 2019, control posterior, aprehensión, decomiso"),
    ]),
    ("M3", "Comportamentales", "Juicio situacional sobre las competencias del empleo", [
        ("etica", "Comportamiento ético", "Nivel 4"),
        ("comunicacion", "Comunicación efectiva", "Nivel 2"),
        ("trabajo-equipo", "Trabajo en equipo", "Nivel 3"),
        ("adaptabilidad", "Adaptabilidad", "Nivel 2"),
        ("orientacion-logro", "Orientación al logro", ""),
        ("orientacion-ciudadano", "Orientación al usuario y al ciudadano", ""),
    ]),
]

CONFIG_DEFAULT = {
    "preguntas_por_ronda": "10",
    "minutos_por_pregunta_simulacro": "2",
    "barajar_opciones": "1",
    "umbral_fortaleza": "80",
    "umbral_debilidad": "60",
    "minimo_respuestas_analisis": "5",
    "modo_autor": "0",  # 1 = los cambios a preguntas desde la app se escriben en banco/ (para publicarlos)
}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS modulos (
    id INTEGER PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, nombre TEXT NOT NULL,
    descripcion TEXT, orden INTEGER
);
CREATE TABLE IF NOT EXISTS sesiones (
    id INTEGER PRIMARY KEY, modulo_id INTEGER NOT NULL REFERENCES modulos(id),
    codigo TEXT UNIQUE NOT NULL, nombre TEXT NOT NULL, descripcion TEXT, orden INTEGER
);
CREATE TABLE IF NOT EXISTS preguntas (
    id INTEGER PRIMARY KEY, sesion_id INTEGER NOT NULL REFERENCES sesiones(id),
    contexto TEXT, enunciado TEXT NOT NULL,
    opcion_a TEXT NOT NULL, opcion_b TEXT NOT NULL, opcion_c TEXT NOT NULL, opcion_d TEXT NOT NULL,
    correcta TEXT NOT NULL CHECK (correcta IN ('A','B','C','D')),
    explicacion TEXT NOT NULL, norma TEXT, dificultad INTEGER DEFAULT 2,
    etiquetas TEXT, activa INTEGER DEFAULT 1, revisar INTEGER DEFAULT 0, nota_revision TEXT,
    hash TEXT UNIQUE, origen TEXT, creada TEXT, uid TEXT
);
CREATE TABLE IF NOT EXISTS rondas (
    id INTEGER PRIMARY KEY, inicio TEXT NOT NULL, fin TEXT, modo TEXT NOT NULL,
    alcance TEXT, modulo_id INTEGER, sesion_id INTEGER, cantidad INTEGER,
    feedback TEXT DEFAULT 'inmediato', tiempo_limite_seg INTEGER
);
CREATE TABLE IF NOT EXISTS ronda_preguntas (
    ronda_id INTEGER NOT NULL REFERENCES rondas(id), pregunta_id INTEGER NOT NULL REFERENCES preguntas(id),
    orden INTEGER NOT NULL, PRIMARY KEY (ronda_id, pregunta_id)
);
CREATE TABLE IF NOT EXISTS respuestas (
    id INTEGER PRIMARY KEY, ronda_id INTEGER NOT NULL REFERENCES rondas(id),
    pregunta_id INTEGER NOT NULL REFERENCES preguntas(id),
    elegida TEXT, correcta INTEGER NOT NULL, confianza TEXT, tiempo_seg REAL, fecha TEXT NOT NULL,
    UNIQUE (ronda_id, pregunta_id)
);
CREATE TABLE IF NOT EXISTS leitner (
    pregunta_id INTEGER PRIMARY KEY REFERENCES preguntas(id), caja INTEGER NOT NULL, proxima TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, ronda_id INTEGER, sesion_id INTEGER NOT NULL,
    respuestas INTEGER, pct_acierto REAL, dominio REAL
);
CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT);
"""


def conectar():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def ahora():
    return datetime.now().isoformat(timespec="seconds")


def inicializar():
    for d in (DIR_IMPORTAR, DIR_IMPORTADAS, DIR_INFORMES):
        d.mkdir(parents=True, exist_ok=True)
    with conectar() as con:
        con.executescript(ESQUEMA)
        if "uid" not in {r["name"] for r in con.execute("PRAGMA table_info(preguntas)")}:
            con.execute("ALTER TABLE preguntas ADD COLUMN uid TEXT")
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_preguntas_uid ON preguntas(uid)")
        for mi, (mcod, mnom, mdesc, sesiones) in enumerate(CATALOGO):
            con.execute(
                "INSERT INTO modulos (codigo, nombre, descripcion, orden) VALUES (?,?,?,?) "
                "ON CONFLICT(codigo) DO UPDATE SET nombre=excluded.nombre, descripcion=excluded.descripcion, orden=excluded.orden",
                (mcod, mnom, mdesc, mi))
            mid = con.execute("SELECT id FROM modulos WHERE codigo=?", (mcod,)).fetchone()["id"]
            for si, (scod, snom, sdesc) in enumerate(sesiones):
                con.execute(
                    "INSERT INTO sesiones (modulo_id, codigo, nombre, descripcion, orden) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(codigo) DO UPDATE SET modulo_id=excluded.modulo_id, nombre=excluded.nombre, "
                    "descripcion=excluded.descripcion, orden=excluded.orden",
                    (mid, scod, snom, sdesc, si))
        for k, v in CONFIG_DEFAULT.items():
            con.execute("INSERT OR IGNORE INTO config (clave, valor) VALUES (?,?)", (k, v))


def config(con):
    return {r["clave"]: r["valor"] for r in con.execute("SELECT clave, valor FROM config")}


def hash_pregunta(enunciado, contexto=""):
    texto = f"{contexto or ''} {enunciado}".lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()


def _validar(p, sesiones_por_codigo, sesion_default):
    """Devuelve (fila_normalizada, error)."""
    cod = p.get("sesion") or sesion_default
    if cod not in sesiones_por_codigo:
        return None, f"sesión desconocida '{cod}'"
    enunciado = (p.get("enunciado") or "").strip()
    if not enunciado:
        return None, "falta 'enunciado'"
    opciones = p.get("opciones")
    if isinstance(opciones, list):
        opciones = dict(zip(LETRAS, opciones))
    if not isinstance(opciones, dict) or any(not str(opciones.get(l, "")).strip() for l in LETRAS):
        return None, "se requieren 4 opciones A, B, C y D"
    correcta = str(p.get("correcta", "")).strip().upper()
    if correcta not in LETRAS:
        return None, "'correcta' debe ser A, B, C o D"
    explicacion = (p.get("explicacion") or "").strip()
    if not explicacion:
        return None, "falta 'explicacion'"
    etiquetas = p.get("etiquetas") or []
    if isinstance(etiquetas, str):
        etiquetas = [e.strip() for e in etiquetas.split(",") if e.strip()]
    return {
        "sesion_id": sesiones_por_codigo[cod],
        "contexto": (p.get("contexto") or "").strip(),
        "enunciado": enunciado,
        "opcion_a": str(opciones["A"]).strip(), "opcion_b": str(opciones["B"]).strip(),
        "opcion_c": str(opciones["C"]).strip(), "opcion_d": str(opciones["D"]).strip(),
        "correcta": correcta, "explicacion": explicacion,
        "norma": (p.get("norma") or "").strip(),
        "dificultad": int(p.get("dificultad") or 2),
        "etiquetas": ", ".join(etiquetas),
    }, None


def sesgo_longitud(opciones, correcta):
    """True si la opción correcta delata la respuesta por ser mucho más larga que las demás."""
    largos = {l: len(t) for l, t in opciones.items()}
    otras = [v for l, v in largos.items() if l != correcta]
    return largos[correcta] > max(otras) and largos[correcta] > 1.3 * sum(otras) / len(otras)


def importar_datos(con, datos, origen):
    """Importa un dict con formato {sesion?, origen?, preguntas:[...]}. Devuelve resumen."""
    sesiones = {r["codigo"]: r["id"] for r in con.execute("SELECT id, codigo FROM sesiones")}
    if isinstance(datos, list):
        datos = {"preguntas": datos}
    origen = datos.get("origen") or origen
    res = {"importadas": 0, "duplicadas": 0, "errores": [], "sesgo": []}
    nuevas = []
    for i, p in enumerate(datos.get("preguntas", []), 1):
        fila, err = _validar(p, sesiones, datos.get("sesion"))
        if err:
            res["errores"].append(f"#{i}: {err}")
            continue
        ops = {l: fila[f"opcion_{l.lower()}"] for l in LETRAS}
        if sesgo_longitud(ops, fila["correcta"]):
            res["sesgo"].append(i)
        h = hash_pregunta(fila["enunciado"], fila["contexto"])
        if con.execute("SELECT 1 FROM preguntas WHERE hash=?", (h,)).fetchone():
            res["duplicadas"] += 1
            continue
        cur = con.execute(
            "INSERT INTO preguntas (sesion_id, contexto, enunciado, opcion_a, opcion_b, opcion_c, opcion_d, "
            "correcta, explicacion, norma, dificultad, etiquetas, hash, origen, creada) "
            "VALUES (:sesion_id, :contexto, :enunciado, :opcion_a, :opcion_b, :opcion_c, :opcion_d, "
            ":correcta, :explicacion, :norma, :dificultad, :etiquetas, :hash, :origen, :creada)",
            {**fila, "hash": h, "origen": origen, "creada": ahora()})
        nuevas.append(cur.lastrowid)
        res["importadas"] += 1
    if nuevas and config(con).get("modo_autor") == "1":
        import banco
        banco.guardar_varias(con, nuevas)
    return res


def importar_pendientes():
    """Importa todos los .json de preguntas/importar y los mueve a preguntas/importadas."""
    resultados = []
    for archivo in sorted(DIR_IMPORTAR.glob("*.json")):
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            resultados.append({"archivo": archivo.name, "importadas": 0, "duplicadas": 0,
                               "errores": [f"JSON inválido: {e}"], "sesgo": []})
            continue
        with conectar() as con:
            res = importar_datos(con, datos, archivo.name)
        res["archivo"] = archivo.name
        resultados.append(res)
        destino = DIR_IMPORTADAS / archivo.name
        if destino.exists():
            destino = DIR_IMPORTADAS / f"{archivo.stem}_{datetime.now():%Y%m%d%H%M%S}{archivo.suffix}"
        shutil.move(str(archivo), destino)
    return resultados
