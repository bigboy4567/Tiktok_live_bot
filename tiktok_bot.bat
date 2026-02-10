@echo off
REM =====================================================
REM Lancement du script Python run.py
REM Dossier : C:\Users\youtu\Documents\mon projet\tiktok\développement
REM =====================================================

REM Force l'encodage UTF-8 (important pour les accents)
chcp 65001 > nul

REM Se placer dans le bon dossier
cd /d "C:\Users\youtu\Documents\mon projet\tiktok\développement"

REM Lancer le script Python
python run.py

REM Empêche la fenêtre de se fermer immédiatement
pause
