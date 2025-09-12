# -*- coding: utf-8 -*-
import sys
import time
import os
import threading
import random
import smtplib
from email.mime.text import MIMEText
from flask import Flask, request, render_template_string, Response, jsonify
import keyboard
import undetected_chromedriver as uc
from selenium.webdriver.common.action_chains import ActionChains
from functools import wraps
import json
import requests
import subprocess
from datetime import datetime
from TikTokLive import TikTokLiveClient
from TikTokLive.events import GiftEvent, ConnectEvent
try:
    from pynput.keyboard import Key, Controller as PynputController
    PYNPUT_AVAILABLE = True
    pynput_kb = PynputController()
except Exception:
    PYNPUT_AVAILABLE = False
    pynput_kb = None

# ---------------- CONFIG JSON ----------------
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

with open(config_path, "r") as f:
    config = json.load(f)

USERNAME = config.get("USERNAME")
PASSWORD = config.get("PASSWORD")
EMAIL_SENDER = config.get("EMAIL_SENDER")
EMAIL_PASSWORD = config.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = config.get("EMAIL_RECEIVER")
EMAIL_LOGIN_TIKTOK = config.get("EMAIL_LOGIN_TIKTOK")
EMAIL_PASSWORD_TIKTOK = config.get("EMAIL_PASSWORD_TIKTOK")

# ---------------- BOT CONFIG ----------------
WINDOW_SIZE = tuple(config.get("WINDOW_SIZE", (1200, 800)))
CLICK_INTERVAL_MIN = config.get("CLICK_INTERVAL_MIN", 0.9)
CLICK_INTERVAL_MAX = config.get("CLICK_INTERVAL_MAX", 1.2)
HUMAN_PAUSE_FREQ_MIN = config.get("HUMAN_PAUSE_FREQ_MIN", 60)
HUMAN_PAUSE_FREQ_MAX = config.get("HUMAN_PAUSE_FREQ_MAX", 180)
HUMAN_PAUSE_MIN = config.get("HUMAN_PAUSE_MIN", 5)
HUMAN_PAUSE_MAX = config.get("HUMAN_PAUSE_MAX", 12)
CLEAR_INTERVAL = config.get("CLEAR_INTERVAL", 300)
REFRESH_DELAY = config.get("REFRESH_DELAY", 10)  # délai après refresh
LIVE_EVENTS_MAX = config.get("LIVE_EVENTS_MAX", 20)

running = False
driver = None
current_live = "https://www.tiktok.com/"
ngrok_url = None
status_message = "Bot en attente..."

# ---------------- Stats ----------------
likes_sent = 0
bot_start_time = None
next_pause_time = None

# ---------------- Live events (cadeaux) ----------------
live_events = []  # list of dicts: {"time":..., "user":..., "gift":..., "count":...}
live_events_lock = threading.Lock()

# ---------------- Gestion Status ----------------
def set_status(msg):
    global status_message
    status_message = msg
    print(f"[{datetime.now().isoformat()}] {msg}")

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
    """Réessaye une action Selenium jusqu’à 'retries' fois"""
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

# ---------------- Fonction Bot Selenium ----------------
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
                page_src = ""
                try:
                    page_src = driver.page_source or ""
                except Exception:
                    page_src = ""
                if "live terminé" in page_src.lower() or "live ended" in page_src.lower() or "this live has ended" in page_src.lower():
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
    try:
        driver = uc.Chrome()
    except Exception as e:
        set_status(f"⚠️ Impossible d'initialiser undetected_chromedriver: {e}")
        driver = None
        return

    try:
        driver.set_window_size(WINDOW_SIZE[0], WINDOW_SIZE[1])
        driver.set_window_position(100, 100)
        driver.get(current_live)

        # Refresh une fois
        time.sleep(3)
        driver.refresh()
        set_status("🔄 Page rafraîchie")
        time.sleep(REFRESH_DELAY)  # Attente configurable après refresh

        # Connexion TikTok (tentative)
        try_action("Bouton 'Ignorer'", lambda: driver.find_element("xpath", "//div[text()='Ignorer']").click(), fatal=False)
        try_action("Bouton 'Se connecter'", lambda: driver.find_element("id", "top-right-action-bar-login-button").click(), fatal=False)
        try_action("Option 'Utiliser téléphone/email'", lambda: driver.find_element(
            "xpath", "//div[contains(text(),\"Utiliser le téléphone/l'e-mail\")]"
        ).click(), fatal=False)
        try_action("Lien 'Connexion email'", lambda: driver.find_element(
            "xpath", "//a[contains(@href,'/login/phone-or-email/email')]"
        ).click(), fatal=False)

        def fill_email():
            email_input = driver.find_element("xpath", "//input[@placeholder=\"E-mail ou nom d'utilisateur\"]")
            email_input.clear()
            email_input.send_keys(EMAIL_LOGIN_TIKTOK)
        try_action("Remplissage Email", fill_email, fatal=False)

        def fill_password():
            password_input = driver.find_element("xpath", "//input[@placeholder='Mot de passe']")
            password_input.clear()
            password_input.send_keys(EMAIL_PASSWORD_TIKTOK)
        try_action("Remplissage Mot de passe", fill_password, fatal=False)

        try_action("Bouton 'Se connecter' final", lambda: driver.find_element(
            "xpath", "//button[@data-e2e='login-button']"
        ).click(), fatal=False)
    except Exception as e:
        set_status(f"⚠️ Erreur dans launch_driver: {e}")

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

# ---------------- TikTokLive listener ----------------
def add_live_event(user, gift_name, count=1):
    ev = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user,
        "gift": gift_name,
        "count": int(count)
    }
    with live_events_lock:
        live_events.insert(0, ev)
        # limiter la longueur
        if len(live_events) > LIVE_EVENTS_MAX:
            live_events.pop()

def run_tiktok_live_client(username):
    """
    Lance le TikTokLiveClient en thread séparé (bloquant).
    Le client.run() est bloquant, donc on l'entoure dans un thread.
    """
    try:
        client = TikTokLiveClient(unique_id=f"@{username}")
    except Exception as e:
        set_status(f"⚠️ Impossible d'instancier TikTokLiveClient: {e}")
        return

    @client.on("connect")
    async def on_connect(event: ConnectEvent):
        set_status(f"🔌 Connecté au live {username} (room_id: {client.room_id})")

    @client.on("gift")
    async def on_gift(event: GiftEvent):
        try:
            # event.gift.extended_gift.name contient le nom du cadeau dans la plupart des cas
            gift_name = getattr(event.gift, "extended_gift", None)
            gift_name_val = ""
            # essayer d'extraire proprement
            try:
                if hasattr(event.gift, "extended_gift") and event.gift.extended_gift:
                    gift_name_val = event.gift.extended_gift.name
                elif hasattr(event.gift, "gift_name"):
                    gift_name_val = event.gift.gift_name
                else:
                    gift_name_val = str(event.gift)
            except Exception:
                gift_name_val = str(event.gift)

            user_name = getattr(event.user, "uniqueId", getattr(event.user, "nickname", "inconnu"))
            count = getattr(event.gift, "repeat_count", 1)
            add_live_event(user_name, gift_name_val, count)
            set_status(f"🎁 {user_name} a envoyé {count}x {gift_name_val}")

            # Optionnel: simuler une touche (up) quand cadeau reçu, si pynput présent
            if PYNPUT_AVAILABLE:
                try:
                    pynput_kb.press(Key.up)
                    pynput_kb.release(Key.up)
                except Exception as e:
                    set_status(f"⚠️ Erreur pynput: {e}")

            # Alerte email (facultatif, limité pour éviter spam)
            try:
                send_email_alert("Bot TikTok - Cadeau reçu", f"{user_name} a envoyé {count}x {gift_name_val} sur {current_live}")
            except Exception:
                pass
        except Exception as e:
            set_status(f"⚠️ Erreur on_gift handler: {e}")

    # Run (bloquant)
    try:
        client.run()
    except Exception as e:
        set_status(f"⚠️ TikTokLive client crashed: {e}")

# ---------------- Flask ----------------
app = Flask(__name__)

HTML_PAGE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Bot TikTok - Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root{
            --bg:#0f1115;
            --card:#12131a;
            --accent:#00f2ea;
            --muted:#9aa0a6;
            --glass: rgba(255,255,255,0.03);
        }
        body{font-family:Inter,Arial,sans-serif;background:var(--bg);color:#e6eef3;margin:0;padding:16px;}
        .wrap{max-width:1100px;margin:0 auto;display:grid;grid-template-columns:1fr 380px;gap:20px;}
        header{grid-column:1/-1;display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;}
        h1{color:var(--accent);margin:0;font-size:20px;}
        .card{background:linear-gradient(180deg,var(--card),#0d0f13);border-radius:12px;padding:18px;box-shadow:0 6px 18px rgba(0,0,0,0.6);}
        .controls{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end;}
        .controls button{all:unset;padding:10px 14px;background:var(--accent);color:#042022;border-radius:8px;cursor:pointer;font-weight:600;flex:1;}
        .controls input{padding:10px;border-radius:8px;border:none;background:var(--glass);color:#fff;flex:2;min-width:140px;}
        .stats{display:flex;flex-direction:column;gap:10px;}
        .stat-row{display:flex;justify-content:space-between;background:rgba(255,255,255,0.02);padding:10px;border-radius:8px;}
        #events-list{max-height:320px;overflow:auto;padding:0;margin:0;list-style:none;}
        #events-list li{padding:10px;border-bottom:1px solid rgba(255,255,255,0.03);display:flex;justify-content:space-between;align-items:center;}
        .small{font-size:13px;color:var(--muted)}
        footer{grid-column:1/-1;margin-top:14px;color:var(--muted);font-size:13px;text-align:center}

        /* 📱 Mobile */
        @media (max-width: 768px){
            .wrap{grid-template-columns:1fr;}
            .controls{flex-direction:column;}
            .controls input,.controls button{flex:unset;width:100%;}
            h1{font-size:18px;}
            #events-list li{flex-direction:column;align-items:flex-start;gap:6px;}
        }
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <h1>🚀 Bot TikTok — Dashboard</h1>
            <div class="small">Status: <span id="status_txt">En attente...</span></div>
        </header>

        <main>
            <div class="card">
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;margin-bottom:12px;gap:10px;">
                    <div>
                        <div class="small">Live actif</div>
                        <div id="current_live" style="font-weight:700;color:#fff;">{{ current_live_display }}</div>
                    </div>
                    <div class="controls">
                        <form method="post" action="/control" style="display:flex;flex-wrap:wrap;gap:8px;width:100%;">
                            <input type="text" name="live_url" id="live_url_input" placeholder="Lien TikTok Live" />
                            <button class="btn" name="action" value="change_live">🌐 Changer</button>
                        </form>
                        <button id="start_btn" onclick="postControl('start')">▶️ Démarrer</button>
                        <button id="stop_btn" onclick="postControl('stop')">⏸️ Arrêter</button>
                    </div>
                </div>

                <div class="stats">
                    <div class="stat-row"><div>Likes envoyés</div><div id="likes">0</div></div>
                    <div class="stat-row"><div>Temps de fonctionnement</div><div id="uptime">0s</div></div>
                    <div class="stat-row"><div>Prochaine pause (s)</div><div id="next_pause">-</div></div>
                </div>
            </div>

            <div class="card" style="margin-top:16px;">
                <h3 style="margin:0 0 10px 0;">📦 Cadeaux récents</h3>
                <ul id="events-list"></ul>
            </div>
        </main>

        <aside>
            <div class="card">
                <h3 style="margin-top:0">Infos</h3>
                <div class="small" style="margin-bottom:10px;">URL publique ngrok (si active):</div>
                <div id="ngrok_url" class="small" style="word-break:break-all;">{{ ngrok_url_display }}</div>
                <hr style="margin:12px 0;border:none;border-top:1px solid rgba(255,255,255,0.03)" />
                <div class="small">Derniers logs:</div>
                <pre id="recent_log" style="height:200px;overflow:auto;background:transparent;border:none;color:var(--muted);padding-top:8px;">{{ status_message }}</pre>
            </div>
        </aside>

        <footer>Bot développé — affichage des cadeaux en temps réel • Ne partage pas tes credentials</footer>
    </div>

<script>
function formatEvent(ev){
    return `<li><div><strong>${ev.user}</strong> <span class="small">a envoyé</span> <em>${ev.count}x ${ev.gift}</em></div><div class="small">${ev.time}</div></li>`;
}

async function refreshStatus(){
    try{
        let res = await fetch('/status');
        let data = await res.json();
        document.getElementById('status_txt').innerText = data.status;
        document.getElementById('likes').innerText = data.likes;
        document.getElementById('uptime').innerText = data.uptime;
        document.getElementById('next_pause').innerText = data.next_pause;
        document.getElementById('recent_log').innerText = data.status;
        if(data.ngrok) document.getElementById('ngrok_url').innerText = data.ngrok;
    }catch(e){ console.warn('status fetch error', e); }
}

async function refreshEvents(){
    try{
        let res = await fetch('/events');
        let evs = await res.json();
        let html = '';
        evs.forEach(ev => { html += formatEvent(ev); });
        document.getElementById('events-list').innerHTML = html;
    }catch(e){ console.warn('events fetch error', e); }
}

async function postControl(action){
    let form = new FormData();
    form.append('action', action);
    if(action === 'change_live'){
        form.append('live_url', document.getElementById('live_url_input').value || '');
    }
    await fetch('/control', {method:'POST', body: form, credentials: 'same-origin'});
}

setInterval(refreshStatus, 2000);
setInterval(refreshEvents, 2000);
refreshStatus();
refreshEvents();
</script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
@requires_auth
def index():
    return render_template_string(HTML_PAGE,
                                  current_live_display=current_live,
                                  ngrok_url_display=(ngrok_url or "—"),
                                  status_message=status_message)

@app.route("/status", methods=["GET"])
@requires_auth
def status():
    global likes_sent, bot_start_time, next_pause_time, ngrok_url
    uptime = "0s"
    if bot_start_time:
        elapsed = int(time.time() - bot_start_time)
        # formattage simple H:M:S si besoin
        hrs = elapsed // 3600
        mins = (elapsed % 3600) // 60
        secs = elapsed % 60
        uptime = f"{hrs}h {mins}m {secs}s" if hrs else f"{mins}m {secs}s"
    next_pause_str = "-"
    if next_pause_time:
        delta = int(next_pause_time - time.time())
        next_pause_str = f"{delta}s" if delta > 0 else "à venir"
    return jsonify({
        "status": status_message,
        "likes": likes_sent,
        "uptime": uptime,
        "next_pause": next_pause_str,
        "ngrok": ngrok_url or ""
    })

@app.route("/events", methods=["GET"])
@requires_auth
def events():
    with live_events_lock:
        return jsonify(live_events)

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
            try:
                driver.get(current_live)
                set_status(f"🌐 Live changé : {current_live}")
            except Exception as e:
                set_status(f"⚠️ Erreur changement live: {e}")
        else:
            set_status(f"🌐 Live changé (driver non prêt) : {current_live}")
    return ("", 204)

# ---------------- Lancement ngrok ----------------
def launch_ngrok():
    global ngrok_url
    try:
        proc = subprocess.Popen(["ngrok", "http", "5000"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(5)
        tunnels = requests.get("http://127.0.0.1:4040/api/tunnels").json().get("tunnels", [])
        if tunnels:
            ngrok_url = tunnels[0].get("public_url")
            set_status(f"🌐 URL publique ngrok : {ngrok_url}")
            try:
                send_email_alert("Bot TikTok - Ngrok", f"Ton URL ngrok : {ngrok_url}")
            except Exception:
                pass
        else:
            set_status("⚠️ ngrok lancé mais aucun tunnel trouvé.")
    except Exception as e:
        set_status(f"⚠️ Erreur ngrok : {e}")

# ---------------- Lancement principal ----------------
if __name__ == "__main__":
    # Start Flask in a thread
    flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False))
    flask_thread.start()
    time.sleep(2)

    # Start ngrok (daemon)
    threading.Thread(target=launch_ngrok, daemon=True).start()

    # Start Selenium driver in a thread
    threading.Thread(target=launch_driver, daemon=True).start()

    # Start auto-like loop
    threading.Thread(target=auto_like, daemon=True).start()

    # Start terminal cleaner
    threading.Thread(target=clear_terminal, daemon=True).start()

    # Start TikTokLive client in a separate thread (ask username)
    def start_live_client_prompt():
        try:
            # si current_live contient @username on tente d'extraire le nom, sinon demande en console
            guessed = None
            if current_live and "tiktok.com/@" in current_live:
                try:
                    guessed = current_live.split("tiktok.com/@")[1].split("/")[0]
                except:
                    guessed = None
            username = guessed or input("Entrez l'identifiant TikTok (sans @) pour écouter les cadeaux: ")
            set_status(f"🔎 Lancement écoute live pour @{username}")
            run_tiktok_live_client(username)
        except Exception as e:
            set_status(f"⚠️ Erreur thread live client: {e}")

    threading.Thread(target=start_live_client_prompt, daemon=True).start()

    # Hotkey pour toggle
    keyboard.add_hotkey("F8", toggle_running)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        set_status("❌ Fermeture du bot...")
        close_driver()
        sys.exit()
