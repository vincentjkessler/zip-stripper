@echo off
rem Zip Stripper setup: adds "Strip & Zip for AI Upload" to the folder right-click menu,
rem starts the Library page with Windows and opens it. Nothing is copied; it runs from this folder.
where py >/dev/null 2>nul
if errorlevel 1 (
  echo Zip Stripper needs Python 3.10 or newer: https://www.python.org/downloads/
  echo Tick "Add python.exe to PATH" while installing, then run this again.
  pause
  exit /b 1
)
py -3 "%~dp0zip_stripper_web.py" --install
if errorlevel 1 pause
