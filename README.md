# Estudio Concurso DIAN – Gestor I

Aplicación local para prepararse para la prueba escrita del **Proceso de Selección DIAN 2676**, empleo **Gestor I – Fiscalización y liquidación** (código 236767, ficha AT-FL-3008). Replica el formato de la prueba real y lleva el registro de tus fortalezas y debilidades por indicador.

Funciona en tu computador, sin cuentas ni internet (solo se usa internet para descargar preguntas nuevas).

## Qué incluye

- **410 preguntas de juicio situacional** con el formato de la prueba real: un caso, un enunciado y **3 opciones**, con la justificación de cada opción y la norma de referencia. Están organizadas por los **11 indicadores oficiales** del empleo: procedimiento de fiscalización y liquidación (tributaria y aduanera), liquidación de impuestos, sanciones, obligaciones tributarias, auditoría, normativa cambiaria, lavado de activos y ROS, gestión documental, razonamiento analítico, estructura y misionalidad de la DIAN.
- **Simulacro oficial:** 66 preguntas repartidas entre los indicadores según su peso, en 4 horas, con el puntaje frente al mínimo aprobatorio (70) y una meta configurable.
- **Rondas a tu medida:** eliges el indicador, la cantidad de preguntas y el modo (aleatorio, no vistas, falladas, enfocado en debilidades, repaso espaciado o simulacro).
- **Práctica comportamental e integridad:** 100 afirmaciones (las de integridad basadas en las pautas del Código de Integridad de la DIAN) con la escala de 4 niveles de la prueba real, con un perfil por competencia y alertas de respuestas extremas o contradictorias (la prueba real no tiene respuestas correctas).
- **Estadísticas:** acierto por indicador, dominio, evolución, calibración de confianza (seguro / dudoso / adiviné), preguntas más falladas y cuenta regresiva a la prueba.

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

### Desde el celular o la tableta (misma wifi)

Inicia con `iniciar_red.bat` (o `sh iniciar.sh --red`, o `python app.py --red`). La consola muestra la dirección para abrir en el otro dispositivo, por ejemplo `http://192.168.1.17:5000`. El progreso es el mismo en todos los dispositivos porque se guarda en este computador.

- La primera vez Windows pregunta si permite el acceso de Python: acepta en **Redes privadas**. Si tu wifi figura como red pública, cámbiala a privada en *Configuración → Red e Internet → Wi-Fi → (tu red) → Tipo de perfil de red*.
- Úsalo solo en una red de confianza: mientras esté abierta, cualquiera conectado a esa wifi puede usar la app. Con `iniciar.bat` normal sigue siendo accesible solo desde este computador.

## Actualizaciones

Cada vez que inicias con `iniciar.bat` o `iniciar.sh`, la app descarga las preguntas nuevas o corregidas del repositorio (si tienes Git e internet) y las agrega a tu banco. **Tu progreso no se pierde.**

Para actualizar manualmente: `git pull` y reinicia la app.

## Tu progreso es privado

Todo lo que respondes se guarda en `estudio.db`, en tu propio computador. Ese archivo no se sube a ningún lado y cada persona empieza desde cero. Para respaldar tu progreso, copia ese archivo. En **Configuración → Reiniciar estadísticas** puedes empezar de cero cuando quieras (se guarda un respaldo automático).

## Aviso

- Las preguntas fueron elaboradas con apoyo de inteligencia artificial a partir de la normativa citada en cada una y de los indicadores publicados para el empleo. No son preguntas reales de la prueba (que es reservada). **Contrasta siempre con la norma vigente**: la regulación tributaria, aduanera y cambiaria cambia con frecuencia. Si encuentras un error, márcala con 🚩 en la app o abre un *issue* en este repositorio.
- Este proyecto no está afiliado a la DIAN ni a la CNSC.

## Estructura

```
banco/          Preguntas (un JSON por indicador) y banco/likert/ (afirmaciones) – lo que se actualiza en el repositorio
app.py          Aplicación web (Flask)
db.py           Base de datos local, catálogo de módulos y sesiones, importador
banco.py        Sincronización entre banco/ y la base de datos local
analisis.py     Estadísticas, fortalezas/debilidades, repaso espaciado e informe
templates/ static/   Interfaz
```
