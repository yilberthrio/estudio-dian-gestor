"""Base de datos SQLite: esquema, catálogo de indicadores, importador y reinicio de estadísticas."""
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
DIR_RESPALDOS = BASE / "respaldos"

LETRAS = ("A", "B", "C", "D")  # la prueba real usa 3 opciones (A-C); D se admite por compatibilidad

# Indicadores oficiales del empleo Gestor I (código 236767), Proceso de Selección DIAN 2676.
# (código, nombre, descripción, peso relativo en el simulacro oficial)
CATALOGO = [
    ("PF", "Prueba funcional", "Eliminatoria · 70% · mínimo 70,00 · juicio situacional con 3 opciones", [
        ("procedimiento-fiscalizacion", "Procedimiento de fiscalización y liquidación tributaria y aduanera",
         "Actos, etapas y términos del proceso tributario (ET) y aduanero", 45),
        ("liquidacion-impuestos", "Liquidación de impuestos nacionales",
         "Depuración de renta, IVA, retención en la fuente, anticipos; cálculos", 35),
        ("sanciones", "Imposición de sanciones",
         "Sanciones tributarias, aduaneras y cambiarias; principios y procedimiento sancionatorio", 30),
        ("obligaciones-tributarias", "Obligaciones formales y sustanciales en materia tributaria",
         "RUT, declarar, facturar, informar, contabilidad, conservación de documentos, pago", 30),
        ("auditoria", "Normas y técnicas de auditoría",
         "Evidencia, procedimientos y técnicas de auditoría, muestreo, papeles de trabajo, materialidad", 30),
        ("normativa-cambiaria", "Normativa cambiaria",
         "Régimen cambiario, canalización, competencia de la DIAN, infracciones cambiarias", 25),
        ("lavado-activos", "Lavado de activos, financiación del terrorismo, ROS y denuncias",
         "UIAF, reporte de operaciones sospechosas, deber de denuncia, delitos fuente", 25),
        ("gestion-documental", "Gestión documental y trazabilidad de expedientes",
         "Expediente, TRD, foliación, préstamo, trazabilidad y archivo", 25),
        ("razonamiento-analitico", "Razonamiento analítico",
         "Análisis de datos, tablas, porcentajes, secuencias e inferencias en contexto DIAN", 22),
        ("estructura-dian", "Estructura organizacional de la DIAN",
         "Decreto 1742 de 2020: niveles central y seccional, dependencias y competencias", 18),
        ("misionalidad-dian", "Misionalidad de la DIAN",
         "Naturaleza, objeto, funciones, misión y visión de la entidad", 15),
    ]),
]

# Práctica de la prueba comportamental y de integridad (autoinforme Likert, sin respuestas correctas)
COMPETENCIAS_LIKERT = {
    "comportamental": ["Adaptabilidad", "Comportamiento ético", "Comunicación efectiva", "Orientación al logro",
                       "Orientación al usuario y al ciudadano", "Trabajo en equipo"],
    "integridad": ["Compromiso", "Diligencia", "Honestidad", "Justicia", "Respeto"],
}
ESCALA_LIKERT = {1: "Totalmente en desacuerdo", 2: "En desacuerdo", 3: "De acuerdo", 4: "Totalmente de acuerdo"}

# Marca del reinicio único de estadísticas al pasar al banco v2 (formato de la prueba real).
# Si existe, no se vuelve a reiniciar: las actualizaciones posteriores del banco conservan el progreso.
REINICIO_V2 = "reinicio_v2"

CONFIG_DEFAULT = {
    "preguntas_por_ronda": "10",
    "minutos_por_pregunta_simulacro": "3.5",
    "simulacro_oficial_preguntas": "66",
    "simulacro_oficial_minutos": "240",
    "fecha_prueba": "2026-11-08",
    "puntaje_minimo": "70",
    "meta_puntaje": "86",
    "barajar_opciones": "1",
    "mostrar_resumen_prueba": "1",
    "umbral_fortaleza": "86",
    "umbral_debilidad": "70",
    "minimo_respuestas_analisis": "5",
    "modo_autor": "0",  # 1 = los cambios a preguntas desde la app se escriben en banco/ (para publicarlos)
}

PREGUNTAS_DDL = """
CREATE TABLE IF NOT EXISTS preguntas (
    id INTEGER PRIMARY KEY, sesion_id INTEGER NOT NULL REFERENCES sesiones(id),
    contexto TEXT, enunciado TEXT NOT NULL,
    opcion_a TEXT NOT NULL, opcion_b TEXT NOT NULL, opcion_c TEXT NOT NULL, opcion_d TEXT,
    correcta TEXT NOT NULL CHECK (correcta IN ('A','B','C','D')),
    explicacion TEXT NOT NULL, norma TEXT, dificultad INTEGER DEFAULT 2,
    etiquetas TEXT, activa INTEGER DEFAULT 1, revisar INTEGER DEFAULT 0, nota_revision TEXT,
    hash TEXT UNIQUE, origen TEXT, creada TEXT, uid TEXT
);
"""

ESQUEMA = PREGUNTAS_DDL + """
CREATE TABLE IF NOT EXISTS modulos (
    id INTEGER PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, nombre TEXT NOT NULL,
    descripcion TEXT, orden INTEGER, vigente INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sesiones (
    id INTEGER PRIMARY KEY, modulo_id INTEGER NOT NULL REFERENCES modulos(id),
    codigo TEXT UNIQUE NOT NULL, nombre TEXT NOT NULL, descripcion TEXT, orden INTEGER,
    peso INTEGER DEFAULT 1, vigente INTEGER DEFAULT 1
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
CREATE TABLE IF NOT EXISTS afirmaciones (
    id INTEGER PRIMARY KEY, uid TEXT UNIQUE NOT NULL, prueba TEXT NOT NULL, competencia TEXT NOT NULL,
    nivel INTEGER, texto TEXT NOT NULL, clave TEXT NOT NULL DEFAULT 'directa', conducta TEXT, activa INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS practicas_likert (
    id INTEGER PRIMARY KEY, inicio TEXT NOT NULL, fin TEXT, prueba TEXT, cantidad INTEGER
);
CREATE TABLE IF NOT EXISTS respuestas_likert (
    id INTEGER PRIMARY KEY, practica_id INTEGER NOT NULL REFERENCES practicas_likert(id),
    afirmacion_id INTEGER NOT NULL REFERENCES afirmaciones(id), orden INTEGER, valor INTEGER, fecha TEXT,
    UNIQUE (practica_id, afirmacion_id)
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


def _columnas(con, tabla):
    return {r["name"]: r for r in con.execute(f"PRAGMA table_info({tabla})")}


def _migrar(con):
    """Lleva una BD de versiones anteriores al esquema actual sin perder datos."""
    cols = _columnas(con, "preguntas")
    if "uid" not in cols:
        con.execute("ALTER TABLE preguntas ADD COLUMN uid TEXT")
    for tabla in ("modulos", "sesiones"):
        if "vigente" not in _columnas(con, tabla):
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN vigente INTEGER DEFAULT 1")
    if "peso" not in _columnas(con, "sesiones"):
        con.execute("ALTER TABLE sesiones ADD COLUMN peso INTEGER DEFAULT 1")
    if _columnas(con, "preguntas")["opcion_d"]["notnull"]:
        # La opción D pasa a ser opcional (la prueba real tiene 3 opciones): se reconstruye la tabla.
        con.commit()
        con.execute("PRAGMA foreign_keys = OFF")
        nombres = ", ".join(_columnas(con, "preguntas"))
        # Procedimiento recomendado por SQLite: crear la nueva, copiar, borrar la vieja y renombrar la nueva,
        # para que las referencias de respuestas/leitner/ronda_preguntas sigan apuntando a «preguntas».
        nueva = PREGUNTAS_DDL.replace("CREATE TABLE IF NOT EXISTS preguntas", "CREATE TABLE preguntas_nueva")
        con.executescript(f"""
            BEGIN;
            {nueva}
            INSERT INTO preguntas_nueva ({nombres}) SELECT {nombres} FROM preguntas;
            DROP TABLE preguntas;
            ALTER TABLE preguntas_nueva RENAME TO preguntas;
            COMMIT;""")
        con.execute("PRAGMA foreign_keys = ON")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_preguntas_uid ON preguntas(uid)")


def inicializar():
    for d in (DIR_IMPORTAR, DIR_IMPORTADAS, DIR_INFORMES, DIR_RESPALDOS):
        d.mkdir(parents=True, exist_ok=True)
    with conectar() as con:
        con.executescript(ESQUEMA)
        _migrar(con)
        con.execute("UPDATE modulos SET vigente=0")
        con.execute("UPDATE sesiones SET vigente=0")
        for mi, (mcod, mnom, mdesc, sesiones) in enumerate(CATALOGO):
            con.execute(
                "INSERT INTO modulos (codigo, nombre, descripcion, orden, vigente) VALUES (?,?,?,?,1) "
                "ON CONFLICT(codigo) DO UPDATE SET nombre=excluded.nombre, descripcion=excluded.descripcion, "
                "orden=excluded.orden, vigente=1",
                (mcod, mnom, mdesc, mi))
            mid = con.execute("SELECT id FROM modulos WHERE codigo=?", (mcod,)).fetchone()["id"]
            for si, (scod, snom, sdesc, peso) in enumerate(sesiones):
                con.execute(
                    "INSERT INTO sesiones (modulo_id, codigo, nombre, descripcion, orden, peso, vigente) "
                    "VALUES (?,?,?,?,?,?,1) ON CONFLICT(codigo) DO UPDATE SET modulo_id=excluded.modulo_id, "
                    "nombre=excluded.nombre, descripcion=excluded.descripcion, orden=excluded.orden, "
                    "peso=excluded.peso, vigente=1",
                    (mid, scod, snom, sdesc, si, peso))
        # Las preguntas de indicadores que ya no están en el catálogo quedan fuera del banco activo
        con.execute("UPDATE preguntas SET activa=0 WHERE sesion_id IN (SELECT id FROM sesiones WHERE vigente=0)")
        for k, v in CONFIG_DEFAULT.items():
            con.execute("INSERT OR IGNORE INTO config (clave, valor) VALUES (?,?)", (k, v))
        hecho = con.execute("SELECT 1 FROM config WHERE clave=?", (REINICIO_V2,)).fetchone()
        hay_progreso = any(con.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()
                           for t in ("respuestas", "rondas", "practicas_likert"))
    if hecho:
        return None
    # Única vez: quien venía de la versión 1 (banco de 4 opciones) empieza de cero con el banco v2.
    respaldo = reiniciar_estadisticas() if hay_progreso else None
    with conectar() as con:
        con.execute("INSERT INTO config (clave, valor) VALUES (?,?)", (REINICIO_V2, ahora()))
        if respaldo:
            con.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES ('aviso_reinicio', ?)", (respaldo.name,))
    return respaldo


def config(con):
    return {r["clave"]: r["valor"] for r in con.execute("SELECT clave, valor FROM config")}


def reiniciar_estadisticas():
    """Respalda estudio.db y borra todo el progreso (rondas, respuestas, repaso, historial y práctica Likert).
    Conserva las preguntas, las marcas «revisar» y la configuración. Devuelve la ruta del respaldo."""
    DIR_RESPALDOS.mkdir(exist_ok=True)
    respaldo = DIR_RESPALDOS / f"estudio_antes_reinicio_{datetime.now():%Y-%m-%d_%H%M%S}.db"
    origen, destino = conectar(), sqlite3.connect(respaldo)
    try:
        origen.backup(destino)
    finally:
        destino.close()
        origen.close()
    with conectar() as con:
        for tabla in ("respuestas", "ronda_preguntas", "rondas", "leitner", "snapshots",
                      "respuestas_likert", "practicas_likert"):
            con.execute(f"DELETE FROM {tabla}")
    return respaldo


def hash_pregunta(enunciado, contexto=""):
    texto = f"{contexto or ''} {enunciado}".lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()


def opciones_de(fila):
    """Opciones presentes de una fila de BD (o dict con opcion_x): {'A': texto, ...}"""
    return {l: fila[f"opcion_{l.lower()}"] for l in LETRAS if fila[f"opcion_{l.lower()}"]}


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
    if not isinstance(opciones, dict):
        return None, "'opciones' debe ser un objeto {A, B, C}"
    opciones = {l: str(opciones.get(l) or "").strip() for l in LETRAS}
    if any(not opciones[l] for l in "ABC"):
        return None, "se requieren al menos las opciones A, B y C"
    correcta = str(p.get("correcta", "")).strip().upper()
    if correcta not in LETRAS or not opciones[correcta]:
        return None, "'correcta' debe ser una de las opciones presentes"
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
        "opcion_a": opciones["A"], "opcion_b": opciones["B"], "opcion_c": opciones["C"],
        "opcion_d": opciones["D"] or None,
        "correcta": correcta, "explicacion": explicacion,
        "norma": (p.get("norma") or "").strip(),
        "dificultad": int(p.get("dificultad") or 2),
        "etiquetas": ", ".join(etiquetas),
    }, None


def sesgo_longitud(opciones, correcta):
    """True si la opción correcta delata la respuesta por ser mucho más larga que las demás."""
    largos = {l: len(t) for l, t in opciones.items() if t}
    otras = [v for l, v in largos.items() if l != correcta]
    return largos[correcta] > max(otras) and largos[correcta] > 1.3 * sum(otras) / len(otras)


def importar_datos(con, datos, origen):
    """Importa un dict con formato {sesion?, origen?, preguntas:[...]}. Devuelve resumen."""
    sesiones = {r["codigo"]: r["id"] for r in con.execute("SELECT id, codigo FROM sesiones WHERE vigente=1")}
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
        if sesgo_longitud(opciones_de(fila), fila["correcta"]):
            res["sesgo"].append(i)
        h = hash_pregunta(fila["enunciado"], fila["contexto"])
        if con.execute("SELECT 1 FROM preguntas WHERE hash=?", (h,)).fetchone():
            res["duplicadas"] += 1
            continue
        fila.update(hash=h, origen=origen, creada=ahora())
        cur = con.execute(f"INSERT INTO preguntas ({', '.join(fila)}) VALUES ({', '.join('?' * len(fila))})",
                          list(fila.values()))
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
