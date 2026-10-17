@echo off
setlocal
TITLE Zip Stripper
set SCRIPT_DIR=%~dp0

echo.
echo ================================================================
echo   ZIP STRIPPER - SMART COPY / STRIP / ZIP
echo ================================================================
echo.
echo Starting. The original project will not be modified.
echo Smart mode is on: source stays, dependency/cache junk goes,
echo one best evidence packet copy is kept, duplicate/raw data bloat is reduced.
echo Secret files and API keys are left out, .gitignore is respected,
echo and big images and duplicate files are trimmed.
echo When it is done, the ZIP is copied to your clipboard: press Ctrl+V in your AI chat.
echo Your ZIP Library page opens in the browser too.
echo.

py -3 "%SCRIPT_DIR%zip_stripper.py" %*
if errorlevel 1 (
  echo.
  echo py launcher failed or Zip Stripper returned an error. Trying python directly...
  python "%SCRIPT_DIR%zip_stripper.py" %*
)
if errorlevel 1 (
  echo.
  echo ZIP STRIPPER FAILED. Read the error above.
)
