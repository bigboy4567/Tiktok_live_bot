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
from selenium.webdriver.common.keys import Keys
from functools import wraps
import json
import requests
import subprocess
import tkinter as tk
import psutil
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ---------------- Bande Passante ----------------
net_stats = {"last_bytes_sent": 0, "last_bytes_recv": 0}
bandwidth_data = {"time": [], "upload": [], "download": []}

# ---------------- CONFIG JSON ----------------
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config_example.json")

with open(config_path, "r") as f:
    config = json.load(f)

USERNAME = config["USERNAME"]
PASSWORD = config["PASSWORD"]
EMAIL_SENDER = config["EMAIL_SENDER"]
EMAIL_PASSWORD = config["EMAIL_PASSWORD"]
EMAIL_RECEIVER = config["EMAIL_RECEIVER"]
EMAIL_LOGIN_TIKTOK = config["EMAIL_LOGIN_TIKTOK"]
EMAIL_PASSWORD_TIKTOK = config["EMAIL_PASSWORD_TIKTOK"]

# ---------------- BOT CONFIG ----------------
WINDOW_SIZE = tuple(config["WINDOW_SIZE"])
CLICK_INTERVAL_MIN = config["CLICK_INTERVAL_MIN"]
CLICK_INTERVAL_MAX = config["CLICK_INTERVAL_MAX"]
HUMAN_PAUSE_FREQ_MIN = config["HUMAN_PAUSE_FREQ_MIN"]
HUMAN_PAUSE_FREQ_MAX = config["HUMAN_PAUSE_FREQ_MAX"]
HUMAN_PAUSE_MIN = config["HUMAN_PAUSE_MIN"]
HUMAN_PAUSE_MAX = config["HUMAN_PAUSE_MAX"]
CLEAR_INTERVAL = config["CLEAR_INTERVAL"]
HUMAN_DELAYS = config["HUMAN_DELAYS"]

REFRESH_INTERVAL = 20 * 60  # 20 minutes

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

# ---------------- Timings Humains ----------------
def get_human_delay():
    base = random.choice(HUMAN_DELAYS)
    variation = random.uniform(-5, 5)
    delay = max(100, base + variation)
    return delay / 1000.0

# ---------------- Retry Helper ----------------
def try_action(description, func, retries=3, wait=2, fatal=True):
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

def get_bandwidth():
    global net_stats
    counters = psutil.net_io_counters()
    sent = counters.bytes_sent
    recv = counters.bytes_recv

    if net_stats["last_bytes_sent"] == 0:
        net_stats["last_bytes_sent"] = sent
        net_stats["last_bytes_recv"] = recv
        return 0, 0

    upload = (sent - net_stats["last_bytes_sent"]) / 1024
    download = (recv - net_stats["last_bytes_recv"]) / 1024

    net_stats["last_bytes_sent"] = sent
    net_stats["last_bytes_recv"] = recv

    return upload, download

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
                if "live terminé" in driver.page_source.lower():
                    set_status("⚠️ Live terminé détecté !")
                    send_email_alert("Bot TikTok - Live terminé", f"Le live {current_live} est terminé.")
                    running = False
                    continue
                if random.random() < 0.9:
                    actions.send_keys("l").perform()
                    likes_sent += 1
                    set_status(f"💖 Like #{likes_sent}")
                else:
                    set_status("⏭️ Like sauté (simulation humaine)")
            except Exception as e:
                set_status(f"⚠️ Erreur auto_like: {e}")

            if time.time() >= next_pause_time:
                pause_duration = random.randint(HUMAN_PAUSE_MIN, HUMAN_PAUSE_MAX)
                set_status(f"⏸️ Pause humaine pour {pause_duration} sec...")
                time.sleep(pause_duration)
                next_pause_time = time.time() + random.randint(HUMAN_PAUSE_FREQ_MIN, HUMAN_PAUSE_FREQ_MAX)

            time.sleep(get_human_delay())
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
    time.sleep(3)
    driver.refresh()
    set_status("🔄 Page rafraîchie")
    time.sleep(10)
    try_action("Bouton 'Se connecter'", lambda: driver.find_element(
        "xpath", "//div[text()='Se connecter']/ancestor::button"
    ).click())
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

# ---------------- Rafraîchissement Live ----------------
def refresh_live_loop():
    global driver, current_live
    while True:
        time.sleep(REFRESH_INTERVAL)
        try:
            if driver:
                live_url = driver.current_url
                set_status("♻️ Rafraîchissement automatique du live...")
                driver.get(live_url)
                time.sleep(5)
                set_status(f"✅ Live rechargé : {live_url}")
                send_email_alert("Bot TikTok - Rafraîchissement", f"Le live a été rechargé : {live_url}")
            else:
                set_status("⚠️ Aucun driver actif pour rafraîchir le live.")
        except Exception as e:
            set_status(f"⚠️ Erreur refresh_live_loop : {e}")

# ---------------- Envoi message TikTok ----------------
def send_message_to_tiktok(msg):
    global driver
    if driver:
        try:
            chat_box = driver.find_element(
                "xpath",
                "//div[@contenteditable='plaintext-only' and @placeholder='Saisis ton message...']"
            )
            chat_box.click()
            chat_box.send_keys(msg)
            chat_box.send_keys(Keys.ENTER)
            set_status(f"💬 Message envoyé : {msg}")
        except Exception as e:
            set_status(f"⚠️ Erreur envoi message : {e}")
    else:
        set_status("⚠️ Driver non lancé, impossible d'envoyer le message.")

# ---------------- Tkinter ----------------
def launch_tkinter_control():
    global running, bot_start_time, likes_sent

    root = tk.Tk()
    root.title("🖥️ Contrôle TikTok Bot")
    root.geometry("450x300")
    root.configure(bg="#1e1e2f")
    
    btn_style = {"bg": "#00f2ea", "fg": "#121212", "font": ("Arial", 12, "bold"), "width": 15, "bd": 0, "activebackground": "#00bfb3"}
    label_style = {"bg": "#1e1e2f", "fg": "#00f2ea", "font": ("Arial", 12, "bold")}
    
    tk.Label(root, text="🚀 Panel de contrôle TikTok Bot", **label_style).pack(pady=10)

    tk.Label(root, text="Message à envoyer :", **label_style).pack(pady=(10, 0))
    msg_entry = tk.Entry(root, font=("Arial", 12), width=40, bd=2, relief="groove")
    msg_entry.pack(pady=5)

    def on_send():
        msg = msg_entry.get()
        if msg.strip():
            send_message_to_tiktok(msg)
            msg_entry.delete(0, tk.END)
    tk.Button(root, text="💬 Envoyer", command=on_send, **btn_style).pack(pady=5)

    def start_autolike():
        global running, bot_start_time
        running = True
        if not bot_start_time:
            bot_start_time = time.time()
        set_status("▶️ Auto-like démarré")
    
    def stop_autolike():
        global running
        running = False
        set_status("⏸️ Auto-like arrêté")
    
    btn_frame = tk.Frame(root, bg="#1e1e2f")
    btn_frame.pack(pady=10)
    tk.Button(btn_frame, text="▶️ Démarrer Auto-like", command=start_autolike, **btn_style).grid(row=0, column=0, padx=5)
    tk.Button(btn_frame, text="⏸️ Arrêter Auto-like", command=stop_autolike, **btn_style).grid(row=0, column=1, padx=5)

    stat_frame = tk.Frame(root, bg="#121212")
    stat_frame.pack(pady=10, fill="x")
    stat_frame.configure(bd=2, relief="groove")
    
    tk.Label(stat_frame, text="📊 Statistiques", **label_style).pack(pady=5)
    likes_label = tk.Label(stat_frame, text=f"Likes envoyés : {likes_sent}", **label_style)
    likes_label.pack()
    uptime_label = tk.Label(stat_frame, text="Temps de fonctionnement : 0s", **label_style)
    uptime_label.pack()

    def update_stats():
        while True:
            if bot_start_time:
                uptime = int(time.time() - bot_start_time)
            else:
                uptime = 0
            likes_label.config(text=f"Likes envoyés : {likes_sent}")
            uptime_label.config(text=f"Temps de fonctionnement : {uptime}s")
            time.sleep(1)

    threading.Thread(target=update_stats, daemon=True).start()

    root.mainloop()

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
    flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False), daemon=True)
    flask_thread.start()
    threading.Thread(target=launch_ngrok, daemon=True).start()
    threading.Thread(target=launch_tkinter_control, daemon=True).start()
    threading.Thread(target=clear_terminal, daemon=True).start()
    threading.Thread(target=refresh_live_loop, daemon=True).start()
    launch_driver()
    auto_like()
