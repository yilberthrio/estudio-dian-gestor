# Estudio Concurso DIAN 2676 – Gestor I (empleo 236767, ficha AT-FL-3008)

App local (Flask + SQLite) para preparar la prueba escrita del Proceso de Selección DIAN 2676 para Gestor I, Fiscalización y liquidación. Se abre con `iniciar.bat` → http://127.0.0.1:5000. Repositorio público: https://github.com/yilberthrio/estudio-dian-gestor

## La prueba real (Guía de orientación al aspirante, oct. 2026)

- Fecha: 8 de noviembre de 2026, 8:00 a.m.–1:00 p.m. (5 horas, una sola sesión).
- Empleo sin experiencia requerida → Funcional 70% (eliminatoria, mínimo 70,00/100) · Comportamental 20% · Integridad 10%. Sin valoración de antecedentes.
- Hoja de respuestas nivel profesional (ilustrativa): 66 ítems funcionales (A–C) + 60 comportamentales + 30 de integridad (escala de 4 niveles).
- Funcional: Prueba de Juicio Situacional (PJS) = 1 caso + 1 enunciado + 3 opciones; una sola es «la solución efectiva». Opciones del mismo largo y estructura.
- Comportamental e integridad: autoinforme Likert (Totalmente en desacuerdo → Totalmente de acuerdo), sin respuestas correctas, con 2 subescalas de control de respuestas exageradamente favorables.
- Solo entran normas vigentes y expedidas antes del 19 de junio de 2026. Las omisiones no suman ni restan.

## Arquitectura

- `app.py` rutas, selección de preguntas (incl. simulacro oficial estratificado por peso), práctica Likert · `db.py` esquema, migraciones, `CATALOGO` de indicadores (con peso), importador, `reiniciar_estadisticas()` · `banco.py` sincronización banco/ ↔ BD (preguntas y Likert) · `analisis.py` estadísticas, dominio, Leitner, informe, perfil Likert y `analisis_completo()` (puntaje estimado por peso, prioridad en puntos, curva de aprendizaje, calibración, dificultad, tiempo, retención, subtemas por etiqueta) que alimenta la página Análisis (`/informe`) · `static/graficas.js` gráficas SVG/HTML sin dependencias (línea, barras horizontales con intervalo, columnas, apilada).
- **`banco/<indicador>.json` es la fuente de verdad de las preguntas** (se publica en GitHub). Cada pregunta tiene `id` estable (`sanciones-012`). Al iniciar (o con «Sincronizar e importar») la app aplica banco/ a la BD: agrega nuevas, actualiza editadas, desactiva retiradas.
- `banco/likert/comportamental.json` y `banco/likert/integridad.json`: afirmaciones de la práctica Likert. Las de integridad (40) se basan en las pautas «lo que hago / lo que no hago» del Código de Integridad de la DIAN (CG-TAH-0002 v3, PDF local en `documentos/`, no versionado); `misionalidad-dian` incluye su filosofía institucional (valores aspiracionales: valentía–oso de anteojos, objetividad–lechuza, templanza–jaguar, providencia–colibrí).
- `documentos/` (ignorada en git): PDFs de referencia (guía de la prueba, consulta de indicadores con el número de inscripción, Código de Integridad, manual) y `Proposito.txt`. La app no los usa.
- `archivo/banco_v1/`: banco anterior (230 preguntas de 4 opciones), retirado; no se sincroniza.
- `estudio.db` es el progreso personal del usuario: está en `.gitignore`, nunca borrarlo, recrearlo ni subirlo. Para empezar de cero usar `db.reiniciar_estadisticas()` (o Configuración → Reiniciar), que respalda antes.
- Reinicio único v2: `db.inicializar()` reinicia (con respaldo) las estadísticas de quien venía de la versión 1 y guarda la marca `reinicio_v2` en `config`. No borrar ni renombrar esa marca: así, agregar preguntas en el futuro conserva el progreso de todos. Solo crear un nuevo reinicio obligatorio si el usuario lo pide expresamente.
- En la BD del usuario `modo_autor=1`: editar/crear/importar/eliminar desde la app escribe también en banco/.
- `informes/ultimo_informe.md` se regenera al terminar cada ronda.

## Cuando el usuario pida preguntas nuevas

1. Escribir un JSON (formato abajo, sin `id`) en `preguntas/importar/` con nombre descriptivo (p. ej. `sanciones_2026-10-20.json`). Verificarlo con `python revisar_preguntas.py preguntas/importar/<archivo>.json`. Importar con la app («Sincronizar e importar») o con `python -c "import db; db.inicializar(); print(db.importar_pendientes())"`: asigna ids y escribe en banco/.
2. Si pide preguntas «según mis debilidades», leer primero `informes/ultimo_informe.md` y consultar en `estudio.db` las respuestas falladas o adivinadas (qué eligió vs. qué era correcto) para atacar la confusión concreta.
3. Si pide revisar preguntas marcadas: `SELECT id, uid, enunciado, nota_revision FROM preguntas WHERE revisar=1`; corregir en `banco/<indicador>.json` por `uid`, sincronizar (`banco.sincronizar(con)`) y poner `revisar=0`.
4. Antes de generar, revisar las existentes del indicador en `banco/<indicador>.json` para no repetir.
5. **Publicar solo cuando el usuario lo pida** («súbelo»): `git add banco && git commit && git push`. Revisar `git status` antes: nunca subir `estudio.db`, `informes/`, `respaldos/`, `preguntas/` ni ningún `.pdf` (el PDF de indicadores tiene el número de inscripción del usuario).

### Formato de pregunta (PJS, 3 opciones)

```json
{
  "origen": "Claude AAAA-MM-DD – tema",
  "sesion": "sanciones",
  "preguntas": [
    {
      "contexto": "Caso: situación hipotética del trabajo en la DIAN, con los datos necesarios.",
      "enunciado": "Tarea incompleta, p. ej. «Al profesional le corresponde…»",
      "opciones": {"A": "acción…", "B": "acción…", "C": "acción…"},
      "correcta": "B",
      "explicacion": "Idea clave (una línea).\n[A] Incorrecta. Por qué…\n[B] Correcta. Por qué, con norma…\n[C] Incorrecta. Por qué…",
      "norma": "Estatuto Tributario, art. 641",
      "dificultad": 2,
      "etiquetas": ["extemporaneidad", "cálculo"]
    }
  ]
}
```

- **Justificar cada opción con los marcadores `[A]`, `[B]`, `[C]` al inicio de línea** (la app los traduce a la letra mostrada cuando baraja las opciones y los ordena). No usar «A.» sin corchetes.
- **Sin pistas por longitud (regla pedida por el usuario):** las 3 opciones con largo y estructura similares. La correcta debe ser la más larga en ≤33% y la más corta en ≤33% de las preguntas (al escribir hay tendencia a alargar la correcta: revisar siempre). Distractores con la misma precisión (cifras, artículos). Evitar absolutos solo en distractores y «todas las anteriores».
- Preferir casos aplicados (qué acto procede, cálculo de sanciones/plazos/impuestos, qué técnica aplicar) sobre memoria pura. Variar la letra correcta.
- `dificultad`: 1 básica, 2 aplicación, 3 caso complejo/excepciones. Señalar normas modificadas.

### Indicadores (códigos de sesión) y peso en el simulacro oficial

| Código | Indicador oficial | Peso |
|---|---|---|
| `procedimiento-fiscalizacion` | Procedimiento de fiscalización y liquidación tributaria y aduanera | 45 |
| `liquidacion-impuestos` | Liquidación de impuestos nacionales | 35 |
| `sanciones` | Imposición de sanciones | 30 |
| `obligaciones-tributarias` | Obligaciones formales y sustanciales en materia tributaria | 30 |
| `auditoria` | Normas y técnicas de auditoría | 30 |
| `normativa-cambiaria` | Normativa cambiaria | 25 |
| `lavado-activos` | Lavado de activos, financiación del terrorismo, ROS y denuncias | 25 |
| `gestion-documental` | Gestión documental y trazabilidad de expedientes | 25 |
| `razonamiento-analitico` | Razonamiento analítico | 22 |
| `estructura-dian` | Estructura organizacional de la DIAN | 18 |
| `misionalidad-dian` | Misionalidad de la DIAN | 15 |

Para agregar un indicador: añadirlo a `CATALOGO` en `db.py` (se sincroniza al iniciar).

### Formato Likert (`banco/likert/*.json`)

`{"prueba": "comportamental"|"integridad", "afirmaciones": [{"id": "lkc-061", "competencia": "Adaptabilidad", "nivel": 2, "clave": "directa"|"inversa", "texto": "Afirmación en primera persona, con matiz…", "conducta": "Qué evalúa y por qué"}]}`. Competencias válidas en `db.COMPETENCIAS_LIKERT`. Comportamentales del empleo: Adaptabilidad N1–N2, Comportamiento ético N1 y N4, Comunicación efectiva N1–N2, Orientación al logro N1, Orientación al usuario y al ciudadano N1, Trabajo en equipo N1 y N3. Integridad: Compromiso, Diligencia, Honestidad, Justicia, Respeto.
