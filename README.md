# TikTok Bot - Setup et Exploitation

## Prerequis
- Windows + Google Chrome installe
- Python 3.10+
- `ngrok` installe et disponible dans le `PATH` (optionnel mais recommande)

## Installation
1. Creer un environnement virtuel:
   - `python -m venv .venv`
   - `.\.venv\Scripts\Activate.ps1`
2. Installer les dependances:
   - `pip install -r requirements.txt`
3. Configurer les variables sensibles:
   - Copier `.env.example` vers `.env` et renseigner:
     - `BOT_USERNAME`, `BOT_PASSWORD`
     - `EMAIL_*` (si alertes mail)
     - `TIKTOK_EMAIL_LOGIN`, `TIKTOK_EMAIL_PASSWORD`

## Demarrage
- En mode Python: `python run.py`
- Ou via batch: `tiktok_bot.bat`

## Fichiers de configuration
- `config.json`: valeurs par defaut (non sensibles)
- `config_perso.json`: surcharges locales persistantes
- `.env`: secrets et identifiants (ignore par git)

## Logs
- Les logs runtime sont ecrits dans `bot.log`
- Niveau configurable via `BOT_LOG_LEVEL` (`INFO`, `WARNING`, `ERROR`, etc.)

## Troubleshooting
- Si ngrok ne demarre pas:
  - verifier `ngrok version`
  - verifier l'URL locale `http://127.0.0.1:4040/api/tunnels`
- Si Selenium ne se connecte pas:
  - verifier les identifiants TikTok dans `.env`
  - verifier la version Chrome
  - verifier que `chrome_profile` est accessible si `USE_CHROME_PROFILE=true`
- Si le terminal se vide trop souvent:
  - mettre `ENABLE_TERMINAL_CLEAR=false` dans `.env` ou `config_perso.json`
