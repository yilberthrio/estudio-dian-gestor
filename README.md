# Estudio Concurso DIAN – Gestor I

Aplicación local para prepararse para la prueba escrita del concurso de méritos de la DIAN, empleo **Gestor I – Fiscalización y liquidación (ficha AT-FL-3008)**. Respondes preguntas tipo CNSC por rondas, ves la explicación de cada respuesta y la app lleva el registro de tus fortalezas y debilidades.

Funciona en tu computador, sin cuentas ni internet (solo se usa internet para descargar preguntas nuevas).

## Qué incluye

- **Banco de preguntas** organizado en 3 módulos y 22 sesiones, según los ejes temáticos de la ficha del empleo:
  - *Funcionales básicas:* Constitución, función pública, Código de Integridad, CPACA, Ley de Transparencia, gestión documental, MIPG, PQRSF, evasión y contrabando, herramientas informáticas.
  - *Funcionales específicas:* sistema tributario, aduanero y cambiario; fiscalización y liquidación; determinación y sanciones; régimen cambiario; fiscalización internacional; fiscalización aduanera.
  - *Comportamentales:* juicio situacional sobre ética, comunicación, trabajo en equipo, adaptabilidad, orientación al logro y al ciudadano.
- **Rondas** configurables: aleatoria, solo no vistas, solo falladas, enfocada en debilidades, repaso espaciado y simulacro cronometrado.
- **Explicación** de cada respuesta con la norma de referencia.
- **Nivel de confianza** en cada respuesta (seguro / dudoso / adiviné) para detectar aciertos por suerte.
- **Estadísticas**: porcentaje de acierto y error, evolución por ronda, dominio por sesión, preguntas más falladas y un informe de fortalezas y debilidades que se actualiza con cada ronda.

## Requisitos

- [Python 3.10 o superior](https://www.python.org/downloads/). En Windows, marca la casilla **"Add Python to PATH"** al instalarlo.
- [Git](https://git-scm.com/downloads) (recomendado, para recibir preguntas nuevas automáticamente).

## Instalación

```bash
git clone https://github.com/yilberthrio/estudio-dian-gestor.git
cd estudio-dian-gestor
```

Si no tienes Git, puedes usar **Code → Download ZIP** en esta página y descomprimirlo. Funciona igual, pero tendrás que descargarlo de nuevo para obtener preguntas nuevas.

## Cómo iniciarla

- **Windows:** doble clic en `iniciar.bat`.
- **macOS / Linux:** `sh iniciar.sh`
- O manualmente: `pip install -r requirements.txt` y luego `python app.py`.

Se abre el navegador en http://127.0.0.1:5000. La primera vez instala Flask y crea tu base de datos con todas las preguntas.

## Actualizaciones

Cada vez que inicias con `iniciar.bat` o `iniciar.sh`, la app descarga las preguntas nuevas o corregidas del repositorio (si tienes Git e internet) y las agrega a tu banco. **Tu progreso no se pierde.**

Para actualizar manualmente: `git pull` y reinicia la app.

## Tu progreso es privado

Todo lo que respondes se guarda en `estudio.db`, en tu propio computador. Ese archivo no se sube a ningún lado y cada persona empieza desde cero. Para respaldar tu progreso, copia ese archivo.

## Aviso

- Las preguntas fueron elaboradas con apoyo de inteligencia artificial a partir de la normativa citada en cada una. **Contrasta siempre con la norma vigente**: la regulación tributaria, aduanera y cambiaria cambia con frecuencia. Si encuentras un error, márcala con 🚩 en la app o abre un *issue* en este repositorio.
- Este proyecto no está afiliado a la DIAN ni a la CNSC.

## Estructura

```
banco/          Preguntas (un archivo JSON por sesión) – lo que se actualiza en el repositorio
app.py          Aplicación web (Flask)
db.py           Base de datos local, catálogo de módulos y sesiones, importador
banco.py        Sincronización entre banco/ y la base de datos local
analisis.py     Estadísticas, fortalezas/debilidades, repaso espaciado e informe
templates/ static/   Interfaz
```
