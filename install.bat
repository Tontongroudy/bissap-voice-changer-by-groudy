@echo off
title Installation - Bissap Voice Changer by Groudy
echo Installation des dependances...
pip install numpy scipy customtkinter keyboard soundfile sounddevice
echo.
echo Tentative d'installation de PyAudio (peut echouer sur Python 3.14+)...
pip install pyaudio 2>nul || echo PyAudio non installe - sounddevice sera utilise comme backend audio.
echo.
echo Tentative d'installation de pygame pour le soundboard...
pip install pygame 2>nul || echo pygame non installe - soundboard desactive.
echo.
echo Installation terminee !
echo Lancez l'application avec : python main.py
echo ou double-cliquez sur launch.bat
pause
