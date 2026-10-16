@echo off
rem Removes the Zip Stripper right-click item and Windows autostart. Your ZIPs stay.
py -3 "%~dp0zip_stripper_web.py" --uninstall
pause
