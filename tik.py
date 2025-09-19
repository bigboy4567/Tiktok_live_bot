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
from tkinter import ttk, messagebox, simpledialog  # Ajout des imports nécessaires
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

# ---------------- AUTO-MESSAGES CONFIG ----------------
# Charger les messages depuis le config, mais ils seront modifiables dans l'interface
AUTO_MESSAGES = config.get("AUTO_MESSAGES", [])
ENABLE_AUTO_MESSAGES = config.get("ENABLE_AUTO_MESSAGES", False)

running = False
driver = None
current_live = "https://www.tiktok.com/"
ngrok_url = None
status_message = "Bot en attente..."

# ---------------- Stats ----------------
likes_sent = 0
bot_start_time = None
next_pause_time = None

def save_config_to_json():
    """Sauvegarde la configuration actuelle dans le fichier JSON"""
    global config, AUTO_MESSAGES, ENABLE_AUTO_MESSAGES
    try:
        # Mettre à jour les messages dans la config
        config["AUTO_MESSAGES"] = AUTO_MESSAGES
        config["ENABLE_AUTO_MESSAGES"] = ENABLE_AUTO_MESSAGES
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        set_status("✅ Configuration sauvegardée dans le JSON")
        return True
    except Exception as e:
        set_status(f"⚠️ Erreur sauvegarde JSON : {e}")
        return False

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
        send_email_alert("⚠️ Bot TikTok - Échec critique", f"L'étape '{description}' a échoué après {retries} tentatives.")
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

# ---------------- Auto Messages ----------------
def auto_message_loop():
    global ENABLE_AUTO_MESSAGES, AUTO_MESSAGES
    while True:
        if ENABLE_AUTO_MESSAGES and driver and AUTO_MESSAGES:
            msg = random.choice(AUTO_MESSAGES)
            send_message_to_tiktok(msg)
            delay = random.randint(config["AUTO_MESSAGE_DELAY_MIN"], config["AUTO_MESSAGE_DELAY_MAX"])
            set_status(f"💬 Prochain auto-message dans {delay}s")
            time.sleep(delay)
        else:
            time.sleep(1)

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
    time.sleep(7)
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

# ---------------- Tkinter avec onglets ----------------
def launch_tkinter_control():
    global running, bot_start_time, likes_sent, ENABLE_AUTO_MESSAGES, AUTO_MESSAGES

    root = tk.Tk()
    root.title("🖥️ Contrôle TikTok Bot")
    root.geometry("600x630")  # Taille agrandie pour les onglets
    root.configure(bg="#1e1e2f")
    
    btn_style = {"bg": "#00f2ea", "fg": "#121212", "font": ("Arial", 10, "bold"), "width": 18, "bd": 0, "activebackground": "#00bfb3"}
    label_style = {"bg": "#1e1e2f", "fg": "#00f2ea", "font": ("Arial", 11, "bold")}

    # Header principal
    tk.Label(root, text="🚀 Panel de contrôle TikTok Bot", **label_style).pack(pady=10)

    # Création du notebook (système d'onglets)
    style = ttk.Style()
    style.theme_use('default')
    style.configure('TNotebook.Tab', background='#2d2d44', foreground='#00f2ea', padding=[15, 8])
    style.configure('TNotebook', background='#1e1e2f', borderwidth=0)
    style.map('TNotebook.Tab', background=[('selected', '#00f2ea')], foreground=[('selected', '#121212')])

    notebook = ttk.Notebook(root)
    notebook.pack(expand=True, fill='both', padx=10, pady=10)

    # ========== ONGLET 1: CONTRÔLE PRINCIPAL ==========
    main_frame = tk.Frame(notebook, bg="#1e1e2f")
    notebook.add(main_frame, text="   🎮 Contrôle   ")

    # Message entry + send
    tk.Label(main_frame, text="Message à envoyer :", **label_style).pack(pady=(15, 5))
    msg_entry = tk.Entry(main_frame, font=("Arial", 11), width=50, bd=2, relief="groove")
    msg_entry.pack(pady=6)

    def on_send():
        msg = msg_entry.get()
        if msg.strip():
            send_message_to_tiktok(msg)
            msg_entry.delete(0, tk.END)
    tk.Button(main_frame, text="💬 Envoyer", command=on_send, **btn_style).pack(pady=6)

    # Auto-like controls
    btn_frame = tk.Frame(main_frame, bg="#1e1e2f")
    btn_frame.pack(pady=15)
    tk.Button(btn_frame, text="▶️ Démarrer Auto-like", command=lambda: set_running(True), **btn_style).grid(row=0, column=0, padx=6, pady=4)
    tk.Button(btn_frame, text="⏸️ Arrêter Auto-like", command=lambda: set_running(False), **btn_style).grid(row=0, column=1, padx=6, pady=4)

    def set_running(val: bool):
        global running, bot_start_time
        running = val
        if running and not bot_start_time:
            bot_start_time = time.time()
        set_status("▶️ Auto-like démarré" if running else "⏸️ Auto-like arrêté")

    # Auto-messages checkbox
    auto_var = tk.BooleanVar(value=ENABLE_AUTO_MESSAGES)
    def on_auto_toggle(*args):
        global ENABLE_AUTO_MESSAGES
        ENABLE_AUTO_MESSAGES = auto_var.get()
        save_config_to_json()  # ← AJOUT ICI
        set_status(f"🔁 Auto-messages {'activés' if ENABLE_AUTO_MESSAGES else 'désactivés'} et sauvegardé")

    auto_var.trace_add("write", on_auto_toggle)
    chk = tk.Checkbutton(main_frame, text="Activer l'envoi auto de messages", variable=auto_var, bg="#1e1e2f", fg="#00f2ea", selectcolor="#1e1e2f", font=("Arial", 10, "bold"))
    chk.pack(pady=12)

    # Stats card
    stat_frame = tk.Frame(main_frame, bg="#121212")
    stat_frame.pack(pady=8, fill="x", padx=10)
    stat_frame.configure(bd=2, relief="groove")

    tk.Label(stat_frame, text="📊 Statistiques", bg="#121212", fg="#00f2ea", font=("Arial", 11, "bold")).pack(pady=6)
    likes_label = tk.Label(stat_frame, text=f"Likes envoyés : {likes_sent}", bg="#121212", fg="#00f2ea", font=("Arial", 10))
    likes_label.pack()
    uptime_label = tk.Label(stat_frame, text="Temps de fonctionnement : 0s", bg="#121212", fg="#00f2ea", font=("Arial", 10))
    uptime_label.pack()
    next_pause_label = tk.Label(stat_frame, text="Prochaine pause : -", bg="#121212", fg="#00f2ea", font=("Arial", 10))
    next_pause_label.pack()
    auto_status_label = tk.Label(stat_frame, text=f"Auto-messages : {'ON' if ENABLE_AUTO_MESSAGES else 'OFF'}", bg="#121212", fg="#00f2ea", font=("Arial", 10))
    auto_status_label.pack(pady=(4,8))

    # ========== ONGLET 2: GESTION DES MESSAGES ==========
    messages_frame = tk.Frame(notebook, bg="#1e1e2f")
    notebook.add(messages_frame, text="   💬 Messages   ")

    tk.Label(messages_frame, text="🎯 Gestion des Messages Automatiques", **label_style).pack(pady=(15, 10))

    # Frame pour la liste et les boutons
    list_frame = tk.Frame(messages_frame, bg="#1e1e2f")
    list_frame.pack(fill="both", expand=True, padx=15, pady=10)

    # Listbox avec scrollbar pour afficher les messages
    list_container = tk.Frame(list_frame, bg="#1e1e2f")
    list_container.pack(fill="both", expand=True)

    scrollbar = tk.Scrollbar(list_container)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    messages_listbox = tk.Listbox(
        list_container, 
        yscrollcommand=scrollbar.set,
        bg="#121212", 
        fg="#00f2ea", 
        selectbackground="#00f2ea",
        selectforeground="#121212",
        font=("Arial", 9),
        height=12
    )
    messages_listbox.pack(side=tk.LEFT, fill="both", expand=True)
    scrollbar.config(command=messages_listbox.yview)

    # Fonction pour rafraîchir la liste des messages
    def refresh_messages_list():
        messages_listbox.delete(0, tk.END)
        for i, msg in enumerate(AUTO_MESSAGES, 1):
            # Tronquer le message si trop long pour l'affichage
            display_msg = msg[:60] + "..." if len(msg) > 60 else msg
            messages_listbox.insert(tk.END, f"{i}. {display_msg}")

    # Boutons de gestion
    btn_frame_messages = tk.Frame(messages_frame, bg="#1e1e2f")
    btn_frame_messages.pack(pady=10)

    def add_message():
        global AUTO_MESSAGES
        new_msg = simpledialog.askstring("Nouveau Message", "Entrez le nouveau message :", parent=root)
        if new_msg and new_msg.strip():
            AUTO_MESSAGES.append(new_msg.strip())
            refresh_messages_list()
            save_config_to_json()  # ← AJOUT ICI
            set_status(f"✅ Message ajouté et sauvegardé : {new_msg[:30]}...")

    def edit_message():
        global AUTO_MESSAGES
        selection = messages_listbox.curselection()
        if not selection:
            messagebox.showwarning("Sélection", "Veuillez sélectionner un message à modifier.")
            return
        
        index = selection  # ← CORRECTION ICI : extraction de l'index du tuple
        current_msg = AUTO_MESSAGES[index]
        new_msg = simpledialog.askstring("Modifier Message", "Modifiez le message :", initialvalue=current_msg, parent=root)
        if new_msg is not None and new_msg.strip():
            AUTO_MESSAGES[index] = new_msg.strip()
            refresh_messages_list()
            save_config_to_json()
            set_status(f"✅ Message modifié et sauvegardé")

    def delete_message():
        global AUTO_MESSAGES
        selection = messages_listbox.curselection()
        if not selection:
            messagebox.showwarning("Sélection", "Veuillez sélectionner un message à supprimer.")
            return
        
        if messagebox.askyesno("Confirmation", "Êtes-vous sûr de vouloir supprimer ce message ?"):
            index = selection  # ← CORRECTION ICI : extraction de l'index du tuple
            del AUTO_MESSAGES[index]
            refresh_messages_list()
            save_config_to_json()
            set_status("🗑️ Message supprimé et sauvegardé")

    def clear_all_messages():
        global AUTO_MESSAGES
        if messagebox.askyesno("Confirmation", "Êtes-vous sûr de vouloir supprimer TOUS les messages ?"):
            AUTO_MESSAGES.clear()
            refresh_messages_list()
            save_config_to_json()  # ← AJOUT ICI
            set_status("🗑️ Tous les messages supprimés et sauvegardés")

    # Boutons d'action
    tk.Button(btn_frame_messages, text="➕ Ajouter", command=add_message, **btn_style).grid(row=0, column=0, padx=5)
    tk.Button(btn_frame_messages, text="✏️ Modifier", command=edit_message, **btn_style).grid(row=0, column=1, padx=5)
    tk.Button(btn_frame_messages, text="🗑️ Supprimer", command=delete_message, **btn_style).grid(row=0, column=2, padx=5)
    tk.Button(btn_frame_messages, text="🧹 Tout effacer", command=clear_all_messages, **btn_style).grid(row=1, column=0, columnspan=3, pady=8)

    # Informations
    info_frame = tk.Frame(messages_frame, bg="#121212", bd=1, relief="solid")
    info_frame.pack(fill="x", padx=15, pady=5)
    
    messages_count_label = tk.Label(info_frame, text=f"Messages configurés : {len(AUTO_MESSAGES)}", bg="#121212", fg="#00f2ea", font=("Arial", 9))
    messages_count_label.pack(pady=5)

    # Initialiser la liste des messages
    refresh_messages_list()

    # Bandwidth miniature plot 
    fig = Figure(figsize=(5.5, 1.2), dpi=80)
    ax = fig.add_subplot(111)
    ax.set_ylim(0, 100)
    ax.set_title("Upload / Download (KB/s)", fontsize=8)
    ax.get_xaxis().set_visible(False)
    canvas = FigureCanvasTkAgg(fig, master=main_frame)
    canvas.get_tk_widget().pack(pady=(2,6))

    # Update stats loop
    def update_stats():
        global likes_sent, bot_start_time, next_pause_time
        while True:
            try:
                if bot_start_time:
                    uptime = int(time.time() - bot_start_time)
                else:
                    uptime = 0
                likes_label.config(text=f"Likes envoyés : {likes_sent}")
                uptime_label.config(text=f"Temps de fonctionnement : {uptime}s")
                if next_pause_time:
                    remaining = int(next_pause_time - time.time())
                    if remaining < 0:
                        remaining = 0
                    next_pause_label.config(text=f"Prochaine pause : {remaining}s")
                else:
                    next_pause_label.config(text="Prochaine pause : -")
                auto_status_label.config(text=f"Auto-messages : {'ON' if ENABLE_AUTO_MESSAGES else 'OFF'}")
                messages_count_label.config(text=f"Messages configurés : {len(AUTO_MESSAGES)}")

                # update bandwidth plot data
                try:
                    up, down = get_bandwidth()
                    bandwidth_data["time"].append(time.time())
                    bandwidth_data["upload"].append(up)
                    bandwidth_data["download"].append(down)
                    if len(bandwidth_data["upload"]) > 30:
                        bandwidth_data["upload"].pop(0)
                        bandwidth_data["download"].pop(0)
                        bandwidth_data["time"].pop(0)
                    ax.clear()
                    ax.plot(bandwidth_data["upload"], label="up")
                    ax.plot(bandwidth_data["download"], label="down")
                    ax.set_ylim(0, max(100, max(bandwidth_data["upload"] + bandwidth_data["download"] + [0])))
                    ax.get_xaxis().set_visible(False)
                    ax.legend(loc="upper right", fontsize=6)
                    canvas.draw()
                except Exception:
                    pass

                time.sleep(1)
            except Exception:
                time.sleep(1)

    threading.Thread(target=update_stats, daemon=True).start()

    root.mainloop()

# [Toutes les autres fonctions restent identiques...]

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

# ---------------- Flask (partie complète) ----------------
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
        label { display: block; margin: 10px; }
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
            <br>
            <label>
                <input type="checkbox" name="auto_messages" onchange="this.form.submit()" {{'checked' if auto_messages else ''}}>
                Activer l'envoi auto de messages
            </label>
        </form>
    </div>
    <div class="card">
        <h2>📊 Statistiques</h2>
        <p>Likes envoyés : <span id="likes">0</span></p>
        <p>Temps de fonctionnement : <span id="uptime">0s</span></p>
        <p>Prochaine pause prévue : <span id="next_pause">-</span></p>
        <p>Auto-messages : <span id="auto_status">{{ 'ON' if auto_messages else 'OFF' }}</span></p>
        <p>Messages configurés : <span id="message_count">{{ message_count }}</span></p>
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
                    document.getElementById("auto_status").innerText = data.auto_messages ? "ON" : "OFF";
                    document.getElementById("message_count").innerText = data.message_count;
                });
        }, 2000);
    </script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
@requires_auth
def index():
    return render_template_string(HTML_PAGE, auto_messages=ENABLE_AUTO_MESSAGES, message_count=len(AUTO_MESSAGES))

@app.route("/status", methods=["GET"])
@requires_auth
def status():
    global likes_sent, bot_start_time, next_pause_time, ENABLE_AUTO_MESSAGES, AUTO_MESSAGES
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
        "next_pause": next_pause_str,
        "auto_messages": ENABLE_AUTO_MESSAGES,
        "message_count": len(AUTO_MESSAGES)
    }

@app.route("/control", methods=["POST"])
@requires_auth
def control():
    global running, current_live, driver, ENABLE_AUTO_MESSAGES
    action = request.form.get("action")
    live_url = request.form.get("live_url")
    auto_messages_toggle = request.form.get("auto_messages")

    if auto_messages_toggle is not None:
        ENABLE_AUTO_MESSAGES = not ENABLE_AUTO_MESSAGES
        set_status(f"🔁 Auto-messages {'activés' if ENABLE_AUTO_MESSAGES else 'désactivés'}")

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
    return render_template_string(HTML_PAGE, auto_messages=ENABLE_AUTO_MESSAGES, message_count=len(AUTO_MESSAGES))

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
    threading.Thread(target=auto_message_loop, daemon=True).start()
    launch_driver()
    auto_like()
