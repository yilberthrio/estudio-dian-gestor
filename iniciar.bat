@echo off
title Estudio DIAN
cd /d "%~dp0"
where git >nul 2>nul && if exist ".git" (
  echo Buscando preguntas nuevas...
  git pull --ff-only -q || echo No se pudo actualizar; se usara la version que ya tienes.
)
python -c "import flask" 2>nul || (
  echo Instalando Flask...
  python -m pip install -r requirements.txt
)
echo.
echo  Estudio DIAN en http://127.0.0.1:5000
echo  Cierra esta ventana para detener la aplicacion.
echo.
python app.py %*
pause
