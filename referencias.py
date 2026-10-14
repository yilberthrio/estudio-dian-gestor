"""«Dónde confirmarlo»: descompone el campo `norma` de una pregunta en fuentes legibles (qué norma, qué
artículo, sobre qué tema) y agrega el nombre oficial de las normas más citadas, para que cualquiera pueda
buscar el texto y comprobar la respuesta."""
import re

# (patrón de la fuente citada, nombre o descripción oficial). Solo normas cuya identidad es inequívoca.
NORMAS = [
    (r"^Estatuto Tributario$", "Decreto 624 de 1989"),
    (r"^Decreto 1625 de 2016", "Decreto Único Reglamentario en materia tributaria"),
    (r"^Decreto 1742 de 2020", "modifica la estructura de la DIAN"),
    (r"^Decreto Ley 2245 de 2011", "régimen sancionatorio y procedimiento administrativo cambiario a cargo de la DIAN"),
    (r"^Ley 594 de 2000", "Ley General de Archivos"),
    (r"^Res(\.|olución) Externa 1 de 2018", "Junta Directiva del Banco de la República: régimen de cambios internacionales"),
    (r"^Circular DCIN-83", "Circular Reglamentaria Externa del Banco de la República sobre las operaciones de cambio"),
    (r"^Ley 9 de 1991", "ley marco del régimen cambiario"),
    (r"^Ley 31 de 1992", "ley del Banco de la República"),
    (r"^Decreto 1165 de 2019", "régimen de aduanas"),
    (r"^Decreto 920 de 2023", "régimen sancionatorio y de decomiso de mercancías en materia aduanera"),
    (r"^Ley 1609 de 2013", "ley marco de aduanas"),
    (r"^Ley 1762 de 2015", "ley anticontrabando"),
    (r"^Acuerdo de Valoración de la OMC", "Acuerdo relativo a la aplicación del artículo VII del GATT de 1994"),
    (r"^Ley 1437 de 2011", "Código de Procedimiento Administrativo y de lo Contencioso Administrativo (CPACA)"),
    (r"^Ley 1755 de 2015", "derecho fundamental de petición"),
    (r"^Constitución Política", "de Colombia, 1991"),
    (r"^Código Penal", "Ley 599 de 2000"),
    (r"^Ley 906 de 2004", "Código de Procedimiento Penal"),
    (r"^Ley 1708 de 2014", "Código de Extinción de Dominio"),
    (r"^Ley 1952 de 2019", "Código General Disciplinario"),
    (r"^Ley 526 de 1999", "crea la Unidad de Información y Análisis Financiero (UIAF)"),
    (r"^Estatuto Orgánico del Sistema Financiero", "Decreto 663 de 1993"),
    (r"^Código de Comercio", "Decreto 410 de 1971"),
    (r"^Decreto 1068 de 2015", "Decreto Único Reglamentario del sector Hacienda y Crédito Público"),
    (r"^(Recomendaci[oó]n(es)?\b.*\bGAFI\b|GAFI\b|GAFILAT\b)", "Grupo de Acción Financiera: estándares internacionales contra el lavado de activos y la financiación del terrorismo"),
    (r"^NIA \d", "Normas Internacionales de Auditoría, incorporadas en Colombia por el Decreto 2420 de 2015"),
    (r"^Decreto 2420 de 2015", "Decreto Único Reglamentario de las normas de contabilidad, información financiera y aseguramiento"),
    (r"^Ley 1712 de 2014", "Ley de Transparencia y del Derecho de Acceso a la Información Pública"),
    (r"^Ley 527 de 1999", "comercio electrónico, mensajes de datos y firmas digitales"),
    (r"^Decreto 1080 de 2015", "Decreto Único Reglamentario del sector Cultura (incluye la gestión documental)"),
    (r"AGN|Archivo General de la Naci[oó]n", "Archivo General de la Nación"),
    (r"^Ley 87 de 1993", "control interno en las entidades del Estado"),
    (r"^Decreto 1499 de 2017", "Modelo Integrado de Planeación y Gestión (MIPG)"),
    (r"^Código de Integridad DIAN", "documento institucional de la DIAN"),
]

# Preguntas de razonamiento: se comprueban con el procedimiento, no con una norma
SIN_NORMA = re.compile(r"^Razonamiento (cuantitativo|l[oó]gico|anal[ií]tico)", re.I)
UBICACION = re.compile(
    r"[,\s]+((?:arts?\.|art[ií]culos?|numerales?|num\.|par[aá]grafos?|literal|lit\.|Libro|T[ií]tulo|Cap[ií]tulo)\s.*)$", re.I)
TEMA = re.compile(r"\s+[–-]\s+(.+)$")


def _parte(texto):
    texto = texto.strip().rstrip(".")
    tema = None
    m = TEMA.search(texto)
    if m:
        texto, tema = texto[:m.start()].strip(), m.group(1).strip()
    donde = None
    m = UBICACION.search(texto)
    if m:
        texto, donde = texto[:m.start()].strip(" ,"), m.group(1).strip()
    elif re.match(r"^arts?\.\s", texto, re.I):
        texto, donde = "", texto
    nombre = next((desc for pat, desc in NORMAS if re.search(pat, texto, re.I)), None)
    if nombre and nombre.lower() in texto.lower():
        nombre = None  # la cita ya dice el nombre completo
    return {"fuente": texto, "nombre": nombre, "donde": donde, "tema": tema}


def desglosar(norma):
    """'Estatuto Tributario, arts. 639 y 640; Decreto 1742 de 2020' →
    {"sin_norma": False, "tema": None, "fuentes": [{"fuente": "Estatuto Tributario", "nombre": "Decreto 624 de 1989",
     "donde": "arts. 639 y 640", "tema": None}, ...]}"""
    norma = (norma or "").strip()
    if not norma:
        return {"sin_norma": False, "tema": None, "fuentes": []}
    m = SIN_NORMA.match(norma)
    if m:
        tema = TEMA.search(norma)
        return {"sin_norma": True, "tema": tema.group(1) if tema else None, "fuentes": []}
    fuentes = []
    for texto in norma.split(";"):
        if not texto.strip():
            continue
        f = _parte(texto)
        if not f["fuente"] and fuentes:
            # «art. 555-2» suelto: es otro artículo de la fuente anterior
            f["fuente"], f["nombre"] = fuentes[-1]["fuente"], fuentes[-1]["nombre"]
        fuentes.append(f)
    return {"sin_norma": False, "tema": None, "fuentes": fuentes}
