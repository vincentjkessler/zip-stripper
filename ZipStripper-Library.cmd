@echo off
rem Opens the Zip Stripper Library page: every ZIP you have made, newest first.
rem Bookmark it: http://127.0.0.1:47811/
start "" pyw -3 "%~dp0zip_stripper_web.py"
if errorlevel 1 start "" py -3 "%~dp0zip_stripper_web.py"
