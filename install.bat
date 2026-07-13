@echo off
rem GenAI Installer starten (Doppelklick). Sucht ein passendes Python.
cd /d "%~dp0"
echo Starte GenAI Installer...
py -3 install.py 2>nul || python install.py 2>nul || "C:\Program Files\Python310\python.exe" install.py
echo.
pause
