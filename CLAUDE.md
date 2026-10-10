# Estudio Concurso DIAN – Gestor I (AT-FL-3008)

App local (Flask + SQLite) para practicar preguntas tipo CNSC para el empleo Gestor I, Fiscalización y liquidación (ficha AT-FL-3008). Se abre con `iniciar.bat` → http://127.0.0.1:5000. Repositorio público: https://github.com/yilberthrio/estudio-dian-gestor

- `app.py` rutas y selección de preguntas · `db.py` esquema, catálogo de módulos/sesiones, importador · `banco.py` sincronización banco/ ↔ BD · `analisis.py` estadísticas, dominio, Leitner, informe
- **`banco/<sesion>.json` es la fuente de verdad de las preguntas** (se publica en GitHub). Cada pregunta tiene un `id` estable (`cpaca-001`). Al iniciar (o con «Sincronizar e importar») la app aplica banco/ a la BD: agrega nuevas, actualiza editadas, desactiva retiradas.
- `estudio.db` es el progreso personal del usuario (respuestas, rondas, repaso, marcas): está en `.gitignore`, nunca borrarlo, recrearlo ni subirlo.
- En la BD del usuario `modo_autor=1`: editar/crear/importar/eliminar desde la app escribe también en banco/.
- `informes/ultimo_informe.md` se regenera al terminar cada ronda (fortalezas/debilidades, más falladas, errores con seguridad).

## Cuando el usuario pida preguntas nuevas

1. Escribir un JSON (formato abajo, sin `id`) en `preguntas/importar/` con nombre descriptivo, p. ej. `cpaca_2026-10-12.json`, y verificarlo con `python revisar_preguntas.py preguntas/importar/<archivo>.json`. Al pulsar «Sincronizar e importar» o reiniciar, la app lo importa, le asigna ids y lo escribe en banco/. Si la app no está abierta, se puede importar directamente: `python -c "import db; db.inicializar(); print(db.importar_pendientes())"`.
2. Si pide preguntas «según mis debilidades», leer primero `informes/ultimo_informe.md`.
3. Si pide revisar preguntas marcadas: `SELECT id, uid, enunciado, nota_revision FROM preguntas WHERE revisar=1` en `estudio.db`; corregir la pregunta en `banco/<sesion>.json` (buscar por `uid`), sincronizar (`banco.sincronizar(con)`) y poner `revisar=0` en la BD.
4. Antes de generar, revisar las existentes de esa sesión en `banco/<sesion>.json` para no repetir. Duplicados exactos se descartan solos por hash.
5. **Publicar solo cuando el usuario lo pida** («súbelo»): `git add banco && git commit && git push`. Revisar `git status` antes: nunca subir `estudio.db`, `informes/`, `respaldos/`, `preguntas/`, `Manual.pdf` ni `Proposito.txt`. Los demás reciben los cambios con el `git pull` automático de `iniciar.bat`.

### Formato

```json
{
  "origen": "Claude AAAA-MM-DD – tema",
  "sesion": "cpaca",
  "preguntas": [
    {
      "sesion": "cpaca",
      "contexto": "Caso opcional (situación tipo CNSC).",
      "enunciado": "Pregunta",
      "opciones": {"A": "...", "B": "...", "C": "...", "D": "..."},
      "correcta": "B",
      "explicacion": "Por qué la correcta lo es y por qué las otras no; incluir datos clave (términos, artículos).",
      "norma": "Ley 1437 de 2011, art. 14",
      "dificultad": 2,
      "etiquetas": ["derecho de petición", "términos"]
    }
  ]
}
```

- **Sin pistas por longitud (regla pedida por el usuario):** las 4 opciones deben tener largo y nivel de detalle similares. La correcta NO debe ser sistemáticamente la más larga ni la más detallada: que sea la más larga en ≤25% de las preguntas y a veces la más corta; dar a los distractores el mismo grado de precisión (cifras, artículos, matices). Evitar también otras pistas: «todas las anteriores», absolutos solo en distractores («siempre», «nunca», «únicamente»), o repetir palabras del enunciado solo en la correcta. Verificar antes de entregar: `python revisar_preguntas.py preguntas/importar/<archivo>.json`.
- Siempre 4 opciones (A–D), una sola correcta; variar la letra correcta. `sesion` a nivel raíz es el valor por defecto; cada pregunta puede sobrescribirlo.
- `dificultad`: 1 básica (definición), 2 media (aplicación/términos), 3 alta (caso complejo, excepciones).
- Distractores plausibles (términos cercanos, normas confundibles). Explicación didáctica y con fuente. Señalar cuando una norma haya sido modificada.
- Comportamentales: casos de juicio situacional con una respuesta claramente mejor según la competencia.

### Códigos de sesión

| Módulo | Código | Tema |
|---|---|---|
| M1 Funcionales básicas | `constitucion` | Constitución: derechos fundamentales, principios, estructura del Estado |
| | `funcion-publica` | Principios de la función pública |
| | `integridad` | Código de Buen Gobierno y Código de Integridad |
| | `cpaca` | Ley 1437/2011: Tít. I, II, III (caps. I, V–VIII) |
| | `transparencia` | Ley 1712 de 2014 |
| | `gestion-documental` | Ley 594/2000, archivos, TRD |
| | `mipg` | Modelo Integrado de Planeación y Gestión |
| | `pqrsf` | PQRSF y políticas de servicio al ciudadano |
| | `evasion-elusion` | Evasión, elusión, contrabando, abuso, LA/FT |
| | `herramientas-informaticas` | Ofimática, Excel, seguridad de la información |
| M2 Funcionales específicas | `sistema-tac` | Generalidades del sistema tributario, aduanero y cambiario |
| | `fiscalizacion-intro` | Introducción al proceso de fiscalización y liquidación |
| | `determinacion-control` | Determinación y control tributario, sanciones, firmeza |
| | `regimen-cambiario` | Régimen cambiario (competencia DIAN) |
| | `fiscalizacion-internacional` | Precios de transferencia, CDI, intercambio de información |
| | `fiscalizacion-aduanera` | Decreto 1165/2019, control posterior, aprehensión, decomiso |
| M3 Comportamentales | `etica` · `comunicacion` · `trabajo-equipo` · `adaptabilidad` · `orientacion-logro` · `orientacion-ciudadano` | Juicio situacional |

Para agregar una sesión nueva: añadirla a `CATALOGO` en `db.py` (se sincroniza al iniciar).
