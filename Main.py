import sys
import time
import os
import threading
import random
import smtplib
from email.mime.text import MIMEText
from flask import Flask, request, render_template_string, Response
import keyboard
import undetected_chromedriver as uc
from selenium.webdriver.common.action_chains import ActionChains
from functools import wraps
import json
import requests
import subprocess

# ---------------- CONFIG JSON ----------------
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

with open(config_path, "r") as f:
    config = json.load(f)

USERNAME = config["USERNAME"]
PASSWORD = config["PASSWORD"]
EMAIL_SENDER = config["EMAIL_SENDER"]
EMAIL_PASSWORD = config["EMAIL_PASSWORD"]
EMAIL_RECEIVER = config["EMAIL_RECEIVER"]
EMAIL_LOGIN_TIKTOK = config["EMAIL_LOGIN_TIKTOK"]
EMAIL_PASSWORD_TIKTOK = config["EMAIL_PASSWORD_TIKTOK"]
UPDATE_URL = config.get("UPDATE_URL", None)  # 🔥 URL d’update (GitHub brut)

# ---------------- AUTO UPDATE ----------------
def auto_update():
    if not UPDATE_URL:
        return
    try:
        # Lire la version locale
        script_path = os.path.abspath(__file__)
        with open(script_path, "r", encoding="utf-8") as f:
            local_code = f.read()

        # Télécharger la version en ligne
        r = requests.get(UPDATE_URL, timeout=10)
        if r.status_code == 200:
            remote_code = r.text
            if remote_code.strip() != local_code.strip():
                print("⬆️ Nouvelle version détectée, mise à jour en cours...")
                backup_path = script_path + ".bak"
                os.rename(script_path, backup_path)  # backup
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(remote_code)
                print("✅ Mise à jour effectuée, redémarrage...")
                os.execv(sys.executable, ["python"] + sys.argv)
        else:
            print(f"⚠️ Impossible de vérifier l’update ({r.status_code})")
    except Exception as e:
        print(f"⚠️ Erreur auto-update: {e}")

# ---------------- BOT CONFIG ----------------
WINDOW_SIZE = tuple(config["WINDOW_SIZE"])
CLICK_INTERVAL_MIN = config["CLICK_INTERVAL_MIN"]
CLICK_INTERVAL_MAX = config["CLICK_INTERVAL_MAX"]
HUMAN_PAUSE_FREQ_MIN = config["HUMAN_PAUSE_FREQ_MIN"]
HUMAN_PAUSE_FREQ_MAX = config["HUMAN_PAUSE_FREQ_MAX"]
HUMAN_PAUSE_MIN = config["HUMAN_PAUSE_MIN"]
HUMAN_PAUSE_MAX = config["HUMAN_PAUSE_MAX"]
CLEAR_INTERVAL = config["CLEAR_INTERVAL"]

running = False
driver = None
current_live = "https://www.tiktok.com/"
ngrok_url = None
status_message = "Bot en attente..."

# ---------------- Stats ----------------
likes_sent = 0
bot_start_time = None
next_pause_time = None

# ---------------- Gestion Status ----------------
def set_status(msg):
    global status_message
    status_message = msg
    print(msg)

# ---------------- Email ----------------
def send_email_alert(subject, body):
    """Envoie un mail si une étape échoue ou si live terminé"""
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        set_status(f"✉️ Email envoyé : {subject}")
    except Exception as e:
        set_status(f"⚠️ Erreur envoi email : {e}")

# ---------------- Retry Helper ----------------
def try_action(description, func, retries=3, wait=2, fatal=True):
    """Réessaye une action Selenium jusqu’à 3 fois"""
    for attempt in range(1, retries + 1):
        try:
            func()
            set_status(f"✔️ {description} réussie (tentative {attempt})")
            return True
        except Exception as e:
            set_status(f"⚠️ {description} échouée (tentative {attempt}): {e}")
            time.sleep(wait)
    if fatal:
        send_email_alert("⚠️ Bot TikTok - Échec critique", f"L’étape '{description}' a échoué après {retries} tentatives.")
    return False

# ---------------- Auth Flask ----------------
def check_auth(username, password):
    return username == USERNAME and password == PASSWORD

def authenticate():
    return Response(
        'Authentification requise', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# ---------------- Fonction Bot ----------------
def toggle_running():
    global running, bot_start_time
    running = not running
    if running:
        if not bot_start_time:
            bot_start_time = time.time()
        set_status("▶️ Bot activé")
    else:
        set_status("⏸️ Bot en pause")

def auto_like():
    global running, driver, likes_sent, next_pause_time
    actions = None
    next_pause_time = time.time() + random.randint(HUMAN_PAUSE_FREQ_MIN, HUMAN_PAUSE_FREQ_MAX)
    while True:
        if running and driver:
            if not actions:
                actions = ActionChains(driver)
            try:
                # Vérifier si le live est terminé
                if "live terminé" in driver.page_source.lower():
                    set_status("⚠️ Live terminé détecté !")
                    send_email_alert("Bot TikTok - Live terminé", f"Le live {current_live} est terminé.")
                    running = False
                    continue

                # Envoi like
                if random.random() < 0.9:
                    actions.send_keys("l").perform()
                    likes_sent += 1
                    set_status(f"💖 Like #{likes_sent}")
                else:
                    set_status("⏭️ Like sauté (simulation humaine)")
            except Exception as e:
                set_status(f"⚠️ Erreur auto_like: {e}")

            # Pause humaine
            if time.time() >= next_pause_time:
                pause_duration = random.randint(HUMAN_PAUSE_MIN, HUMAN_PAUSE_MAX)
                set_status(f"⏸️ Pause humaine pour {pause_duration} sec...")
                time.sleep(pause_duration)
                next_pause_time = time.time() + random.randint(HUMAN_PAUSE_FREQ_MIN, HUMAN_PAUSE_FREQ_MAX)

            interval = random.uniform(CLICK_INTERVAL_MIN, CLICK_INTERVAL_MAX)
            time.sleep(interval)
        else:
            time.sleep(0.1)

def launch_driver():
    global driver, current_live
    if driver:
        try:
            driver.quit()
        except:
            pass
    driver = uc.Chrome()
    driver.set_window_size(WINDOW_SIZE[0], WINDOW_SIZE[1])
    driver.set_window_position(100, 100)
    driver.get(current_live)

    # Refresh une fois
    time.sleep(3)
    driver.refresh()
    set_status("🔄 Page rafraîchie")
    time.sleep(10)  # Attente 10s après refresh

    # Connexion TikTok
    try_action("Bouton 'Ignorer'", lambda: driver.find_element("xpath", "//div[text()='Ignorer']").click())
    try_action("Bouton 'Se connecter'", lambda: driver.find_element("id", "top-right-action-bar-login-button").click())
    try_action("Option 'Utiliser téléphone/email'", lambda: driver.find_element(
        "xpath", "//div[contains(text(),\"Utiliser le téléphone/l'e-mail\")]"
    ).click())
    try_action("Lien 'Connexion email'", lambda: driver.find_element(
        "xpath", "//a[contains(@href,'/login/phone-or-email/email')]"
    ).click())

    def fill_email():
        email_input = driver.find_element("xpath", "//input[@placeholder=\"E-mail ou nom d'utilisateur\"]")
        email_input.clear()
        email_input.send_keys(EMAIL_LOGIN_TIKTOK)
    try_action("Remplissage Email", fill_email)

    def fill_password():
        password_input = driver.find_element("xpath", "//input[@placeholder='Mot de passe']")
        password_input.clear()
        password_input.send_keys(EMAIL_PASSWORD_TIKTOK)
    try_action("Remplissage Mot de passe", fill_password)

    try_action("Bouton 'Se connecter' final", lambda: driver.find_element(
        "xpath", "//button[@data-e2e='login-button']"
    ).click())

# ---------------- Fonction Clear Terminal ----------------
def clear_terminal():
    while True:
        time.sleep(CLEAR_INTERVAL)
        os.system('cls' if os.name == 'nt' else 'clear')
        set_status("🧹 Terminal nettoyé automatiquement.")

# ---------------- Gestion fermeture ----------------
def close_driver():
    global driver
    if driver:
        try:
            driver.quit()
            set_status("✅ Fenêtre Selenium fermée.")
        except:
            pass

# ---------------- Flask ----------------
app = Flask(__name__)

HTML_PAGE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Bot TikTok</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; background: #121212; color: #f5f5f5; text-align: center; margin:0; padding:20px; }
        h1 { color: #00f2ea; }
        .btn { background: #00f2ea; border: none; padding: 12px 20px; margin: 5px; border-radius: 6px; cursor: pointer; font-size: 16px; transition: 0.3s; }
        .btn:hover { background: #00bfb3; }
        input { padding: 10px; margin: 10px; border-radius: 6px; border: none; width: 80%; max-width: 400px; }
        .card { background: #1e1e2f; padding: 20px; border-radius: 10px; margin-top: 20px; }
        #status { margin-top: 20px; font-size: 18px; }
    </style>
</head>
<body>
    <h1>🚀 Bot TikTok</h1>
    <div class="card">
        <form method="post" action="/control">
            <button class="btn" name="action" value="start">▶️ Démarrer</button>
            <button class="btn" name="action" value="stop">⏸️ Arrêter</button>
            <br>
            <input type="text" name="live_url" placeholder="Lien TikTok Live">
            <button class="btn" name="action" value="change_live">🌐 Changer Live</button>
        </form>
    </div>
    <div class="card">
        <h2>📊 Statistiques</h2>
        <p>Likes envoyés : <span id="likes">0</span></p>
        <p>Temps de fonctionnement : <span id="uptime">0s</span></p>
        <p>Prochaine pause prévue : <span id="next_pause">-</span></p>
    </div>
    <h3 id="status">Status: En attente...</h3>
    <script>
        setInterval(function(){
            // On ajoute un timestamp pour éviter le cache
            fetch("/status?_=" + new Date().getTime())
                .then(res => res.json())
                .then(data => {
                    document.getElementById("status").innerText = "Status: " + data.status;
                    document.getElementById("likes").innerText = data.likes;
                    document.getElementById("uptime").innerText = data.uptime;
                    document.getElementById("next_pause").innerText = data.next_pause;
                });
        }, 2000);
    </script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
@requires_auth
def index():
    return render_template_string(HTML_PAGE)

@app.route("/status", methods=["GET"])
@requires_auth
def status():
    global likes_sent, bot_start_time, next_pause_time
    uptime = "0s"
    if bot_start_time:
        uptime = f"{int(time.time()-bot_start_time)}s"
    next_pause_str = "-"
    if next_pause_time:
        next_pause_str = f"{int(next_pause_time - time.time())}s"
    return {
        "status": status_message,
        "likes": likes_sent,
        "uptime": uptime,
        "next_pause": next_pause_str
    }

@app.route("/control", methods=["POST"])
@requires_auth
def control():
    global running, current_live, driver
    action = request.form.get("action")
    live_url = request.form.get("live_url")

    if action == "start":
        toggle_running()
    elif action == "stop":
        running = False
        set_status("⏸️ Bot arrêté via web")
    elif action == "change_live" and live_url:
        current_live = live_url
        if driver:
            driver.get(current_live)
        set_status(f"🌐 Live changé : {current_live}")
    return render_template_string(HTML_PAGE)

# ---------------- Lancement ngrok ----------------
def launch_ngrok():
    global ngrok_url
    try:
        proc = subprocess.Popen(["ngrok", "http", "5000"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(5)
        tunnels = requests.get("http://127.0.0.1:4040/api/tunnels").json()["tunnels"]
        ngrok_url = tunnels[0]["public_url"]
        set_status(f"🌐 URL publique ngrok : {ngrok_url}")
        send_email_alert("Bot TikTok - Ngrok", f"Ton URL ngrok : {ngrok_url}")
    except Exception as e:
        set_status(f"⚠️ Erreur ngrok : {e}")

# ---------------- Lancement ----------------
if __name__ == "__main__":
    auto_update()  # 🔥 Vérifie l’update au lancement

    flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False))
    flask_thread.start()
    time.sleep(3)

    threading.Thread(target=launch_ngrok, daemon=True).start()
    threading.Thread(target=launch_driver).start()
    threading.Thread(target=auto_like, daemon=True).start()
    threading.Thread(target=clear_terminal, daemon=True).start()

    keyboard.add_hotkey("F8", toggle_running)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        set_status("❌ Fermeture du bot...")
        close_driver()
        sys.exit()
