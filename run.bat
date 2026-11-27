@echo off
rem One command for Windows: double-click run.bat, or in cmd:  run.bat --offline
rem Stops at the first failing step instead of printing "Bitti".
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv 2>nul || python -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat || goto :fail
python -m pip install --upgrade pip -q || goto :fail
python -m pip install -r requirements.txt -q || goto :fail
python run_all.py %* || goto :fail
python fill_report.py || goto :fail
python run_phase2.py || goto :fail
python run_scenario.py || goto :fail
python run_extra.py || goto :fail
python tools\build_paper.py || goto :fail
python tools\build_final_report.py || goto :fail
echo Bitti: Final_Paper_Overleaf.zip (Overleaf: New Project > Upload Project)
pause
exit /b 0
:fail
echo HATA: bir adim basarisiz oldu; yukaridaki mesaja bakin. Rapor dosyasi guncellenmedi.
pause
exit /b 1
