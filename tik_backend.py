import json
import logging
import os
import random
import smtplib
import threading
import time
from email.mime.text import MIMEText
from functools import wraps

import psutil
from flask import Flask, Response, request
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# ---------------- Paths & Config ----------------
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")
config_perso_path = os.path.join(script_dir, "config_perso.json")
dotenv_path = os.path.join(script_dir, ".env")


def _load_dotenv(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key:
                    os.environ.setdefault(key, value)
    except Exception:
        pass


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


_load_dotenv(dotenv_path)

with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

config_perso = {}
if os.path.exists(config_perso_path):
    with open(config_perso_path, "r", encoding="utf-8") as f:
        config_perso = json.load(f)
    config.update(config_perso)


def _env_or_config(env_key, config_key, default=""):
    return os.getenv(env_key, config.get(config_key, default))


# ---------------- Logging ----------------
log_level = _env_or_config("BOT_LOG_LEVEL", "LOG_LEVEL", "INFO").upper()
log_file = os.path.join(script_dir, "bot.log")
logger = logging.getLogger("tiktok_bot")
if not logger.handlers:
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False


# ---------------- Globals ----------------
auto_like_pause_event = threading.Event()
auto_like_pause_event.set()

net_stats = {"last_bytes_sent": 0, "last_bytes_recv": 0}
bandwidth_data = {"time": [], "upload": [], "download": []}

USERNAME = _env_or_config("BOT_USERNAME", "USERNAME", "admin")
PASSWORD = _env_or_config("BOT_PASSWORD", "PASSWORD", "admin")
EMAIL_SENDER = _env_or_config("EMAIL_SENDER", "EMAIL_SENDER", "")
EMAIL_PASSWORD = _env_or_config("EMAIL_PASSWORD", "EMAIL_PASSWORD", "")
EMAIL_RECEIVER = _env_or_config("EMAIL_RECEIVER", "EMAIL_RECEIVER", "")
EMAIL_LOGIN_TIKTOK = _env_or_config("TIKTOK_EMAIL_LOGIN", "EMAIL_LOGIN_TIKTOK", "")
EMAIL_PASSWORD_TIKTOK = _env_or_config(
    "TIKTOK_EMAIL_PASSWORD", "EMAIL_PASSWORD_TIKTOK", ""
)

WINDOW_SIZE = tuple(config.get("WINDOW_SIZE", [1200, 1000]))
CLICK_INTERVAL_MIN = float(config.get("CLICK_INTERVAL_MIN", 0.4))
CLICK_INTERVAL_MAX = float(config.get("CLICK_INTERVAL_MAX", 1.1))
HUMAN_PAUSE_FREQ_MIN = int(config.get("HUMAN_PAUSE_FREQ_MIN", 90))
HUMAN_PAUSE_FREQ_MAX = int(config.get("HUMAN_PAUSE_FREQ_MAX", 150))
HUMAN_PAUSE_MIN = int(config.get("HUMAN_PAUSE_MIN", 5))
HUMAN_PAUSE_MAX = int(config.get("HUMAN_PAUSE_MAX", 60))
CLEAR_INTERVAL = int(config.get("CLEAR_INTERVAL", 150))
HUMAN_DELAYS = config.get(
    "HUMAN_DELAYS",
    [160.0, 134.8, 150.0, 182.8, 166.5, 150.1, 150.2, 166.3, 151.9, 164.9],
)
REFRESH_INTERVAL = int(config.get("REFRESH_INTERVAL_SECONDS", 200 * 60 * 60))
ENABLE_TERMINAL_CLEAR = _as_bool(
    _env_or_config("ENABLE_TERMINAL_CLEAR", "ENABLE_TERMINAL_CLEAR", True), True
)
USE_CHROME_PROFILE = _as_bool(
    _env_or_config("USE_CHROME_PROFILE", "USE_CHROME_PROFILE", True), True
)
CHROME_PROFILE_DIR = _env_or_config(
    "CHROME_PROFILE_DIR",
    "CHROME_PROFILE_DIR",
    os.path.join(script_dir, "chrome_profile"),
)

AUTO_MESSAGES = config.get("AUTO_MESSAGES", [])
ENABLE_AUTO_MESSAGES = _as_bool(config.get("ENABLE_AUTO_MESSAGES", False), False)

running = False
driver = None
current_live = "https://www.tiktok.com/"
ngrok_url = None
status_message = "Bot en attente..."
likes_sent = 0
bot_start_time = None
next_pause_time = None

app = Flask(__name__)


# ---------------- Helpers ----------------
def _persistable_config_values():
    return {
        "AUTO_MESSAGES": AUTO_MESSAGES,
        "ENABLE_AUTO_MESSAGES": ENABLE_AUTO_MESSAGES,
        "ENABLE_TERMINAL_CLEAR": ENABLE_TERMINAL_CLEAR,
        "USE_CHROME_PROFILE": USE_CHROME_PROFILE,
        "CHROME_PROFILE_DIR": CHROME_PROFILE_DIR,
    }


def save_config_to_json():
    global config_perso
    try:
        data = {}
        if os.path.exists(config_perso_path):
            with open(config_perso_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data.update(_persistable_config_values())
        with open(config_perso_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        config_perso = data
        config.update(data)
        set_status("Configuration sauvegardee dans config_perso.json")
        return True
    except Exception as e:
        set_status(f"Erreur sauvegarde JSON: {e}")
        return False


def set_status(msg):
    global status_message
    status_message = msg
    logger.info(msg)


def send_email_alert(subject, body):
    if not (EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER):
        set_status("Email non envoye: variables EMAIL_* manquantes.")
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        set_status(f"Email envoye: {subject}")
    except Exception as e:
        set_status(f"Erreur envoi email: {e}")


def get_human_delay():
    base = random.choice(HUMAN_DELAYS)
    variation = random.uniform(-5, 5)
    delay = max(100, base + variation)
    return delay / 1000.0


def try_action(description, func, retries=3, wait=2, fatal=True):
    for attempt in range(1, retries + 1):
        try:
            func()
            set_status(f"{description} reussie (tentative {attempt})")
            return True
        except Exception as e:
            set_status(f"{description} echouee (tentative {attempt}): {e}")
            time.sleep(wait)
    if fatal:
        send_email_alert(
            "Bot TikTok - Echec critique",
            f"L'etape '{description}' a echoue apres {retries} tentatives.",
        )
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


# ---------------- Flask Auth ----------------
def check_auth(username, password):
    return username == USERNAME and password == PASSWORD


def authenticate():
    return Response(
        "Authentification requise",
        401,
        {"WWW-Authenticate": 'Basic realm="Login Required"'},
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)

    return decorated


# ---------------- Bot Core ----------------
def toggle_running():
    global running, bot_start_time
    running = not running
    if running:
        if not bot_start_time:
            bot_start_time = time.time()
        set_status("Bot active")
    else:
        set_status("Bot en pause")


def auto_like():
    global running, driver, likes_sent, next_pause_time, auto_like_pause_event
    actions = None
    next_pause_time = time.time() + random.randint(
        HUMAN_PAUSE_FREQ_MIN, HUMAN_PAUSE_FREQ_MAX
    )
    while True:
        if running and driver:
            auto_like_pause_event.wait()
            if not actions:
                actions = ActionChains(driver)
            try:
                if "live termine" in driver.page_source.lower():
                    set_status("Live termine detecte.")
                    send_email_alert(
                        "Bot TikTok - Live termine",
                        f"Le live {current_live} est termine.",
                    )
                    running = False
                    continue
                if random.random() < 0.9:
                    actions.send_keys("l").perform()
                    likes_sent += 1
                    set_status(f"Like #{likes_sent}")
                else:
                    set_status("Like saute (simulation humaine)")
            except Exception as e:
                set_status(f"Erreur auto_like: {e}")
            if time.time() >= next_pause_time:
                pause_duration = random.randint(HUMAN_PAUSE_MIN, HUMAN_PAUSE_MAX)
                set_status(f"Pause humaine pour {pause_duration}s")
                time.sleep(pause_duration)
                next_pause_time = time.time() + random.randint(
                    HUMAN_PAUSE_FREQ_MIN, HUMAN_PAUSE_FREQ_MAX
                )
            time.sleep(get_human_delay())
        else:
            time.sleep(0.1)


def auto_message_loop():
    global ENABLE_AUTO_MESSAGES, AUTO_MESSAGES
    while True:
        if ENABLE_AUTO_MESSAGES and running and driver and AUTO_MESSAGES:
            msg = random.choice(AUTO_MESSAGES)
            send_message_to_tiktok(msg)
            delay = random.randint(
                int(config.get("AUTO_MESSAGE_DELAY_MIN", 30)),
                int(config.get("AUTO_MESSAGE_DELAY_MAX", 120)),
            )
            set_status(f"Prochain auto-message dans {delay}s")
            time.sleep(delay)
        else:
            time.sleep(1)


def launch_driver():
    """
    Lance Selenium avec undetected_chromedriver en alignant la version
    ChromeDriver sur la version majeure de Chrome detectee.
    """
    import subprocess

    try:
        import winreg
    except Exception:
        winreg = None

    import undetected_chromedriver as uc

    global driver, current_live

    if driver:
        try:
            driver.quit()
        except Exception:
            pass

    def _detect_chrome_major_and_path():
        def _parse_major(version):
            try:
                return int(version.split(".")[0])
            except Exception:
                return None

        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]

        if winreg is not None:
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for subkey in (
                    r"SOFTWARE\Google\Chrome\BLBeacon",
                    r"SOFTWARE\WOW6432Node\Google\Chrome\BLBeacon",
                ):
                    try:
                        with winreg.OpenKey(root, subkey) as k:
                            version, _ = winreg.QueryValueEx(k, "version")
                            major = _parse_major(version)
                            for cp in chrome_paths:
                                if os.path.exists(cp):
                                    return major, cp
                            return major, None
                    except Exception:
                        pass

        for cp in chrome_paths:
            if os.path.exists(cp):
                try:
                    out = subprocess.run(
                        [cp, "--version"], capture_output=True, text=True, timeout=5
                    )
                    ver_str = (out.stdout or out.stderr or "").strip()
                    version = ver_str.split()[-1] if ver_str else ""
                    return _parse_major(version), cp
                except Exception:
                    return None, cp

        return None, None

    major, chrome_path = _detect_chrome_major_and_path()
    options = uc.ChromeOptions()

    if chrome_path and os.path.exists(chrome_path):
        options.binary_location = chrome_path

    if USE_CHROME_PROFILE:
        profile_path = CHROME_PROFILE_DIR
        if not os.path.isabs(profile_path):
            profile_path = os.path.join(script_dir, profile_path)
        os.makedirs(profile_path, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_path}")

    kwargs = {}
    if major:
        kwargs["version_main"] = major

    driver = uc.Chrome(options=options, **kwargs)
    driver.set_window_size(WINDOW_SIZE[0], WINDOW_SIZE[1])
    driver.set_window_position(100, 100)

    wait = WebDriverWait(driver, 30)
    driver.get(current_live)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    driver.refresh()
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    set_status("Page rafraichie")

    if not (EMAIL_LOGIN_TIKTOK and EMAIL_PASSWORD_TIKTOK):
        set_status(
            "Identifiants TikTok manquants. Definis TIKTOK_EMAIL_LOGIN et "
            "TIKTOK_EMAIL_PASSWORD dans .env."
        )
        return

    try_action(
        "Bouton Se connecter",
        lambda: wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//div[text()='Se connecter']/ancestor::button")
            )
        ).click(),
    )

    try_action(
        "Option Utiliser telephone/email",
        lambda: wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//div[contains(text(),'Utiliser le') and contains(text(),'e-mail')]",
                )
            )
        ).click(),
    )

    try_action(
        "Lien Connexion email",
        lambda: wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href,'/login/phone-or-email/email')]")
            )
        ).click(),
    )

    def fill_email():
        email_input = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@placeholder=\"E-mail ou nom d'utilisateur\"]")
            )
        )
        email_input.clear()
        email_input.send_keys(EMAIL_LOGIN_TIKTOK)

    try_action("Remplissage Email", fill_email)

    def fill_password():
        password_input = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@placeholder='Mot de passe']")
            )
        )
        password_input.clear()
        password_input.send_keys(EMAIL_PASSWORD_TIKTOK)

    try_action("Remplissage Mot de passe", fill_password)

    try_action(
        "Bouton Se connecter final",
        lambda: wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[@data-e2e='login-button']"))
        ).click(),
    )


def refresh_live_loop():
    global driver
    while True:
        time.sleep(REFRESH_INTERVAL)
        try:
            if driver:
                live_url = driver.current_url
                set_status("Rafraichissement automatique du live...")
                driver.get(live_url)
                WebDriverWait(driver, 30).until(
                    lambda d: d.execute_script("return document.readyState")
                    == "complete"
                )
                set_status(f"Live recharge: {live_url}")
                send_email_alert(
                    "Bot TikTok - Rafraichissement",
                    f"Le live a ete recharge: {live_url}",
                )
            else:
                set_status("Aucun driver actif pour rafraichir le live.")
        except Exception as e:
            set_status(f"Erreur refresh_live_loop: {e}")


def send_message_to_tiktok(msg):
    global driver, auto_like_pause_event
    if not driver:
        set_status("Driver non lance, impossible d'envoyer le message.")
        return
    try:
        auto_like_pause_event.clear()
        set_status("Auto-like en pause pour envoi message...")
        chat_box = WebDriverWait(driver, 12).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//div[@contenteditable='plaintext-only' and "
                    "@placeholder='Saisis ton message...']",
                )
            )
        )
        chat_box.click()
        time.sleep(get_human_delay())
        chat_box.send_keys(msg)
        time.sleep(get_human_delay())
        chat_box.send_keys(Keys.ENTER)
        set_status(f"Message envoye: {msg}")
        time.sleep(get_human_delay())
    except Exception as e:
        set_status(f"Erreur envoi message: {e}")
    finally:
        auto_like_pause_event.set()
        set_status("Auto-like reactive apres envoi message")


def get_live_comments(driver_instance):
    results = []
    try:
        nodes = driver_instance.find_elements(By.XPATH, "//*[contains(@data-e2e,'chat')]")
        for node in nodes:
            try:
                txt = node.text.strip()
                if txt and len(txt) < 300:
                    results.append({"user": "", "content": txt})
            except Exception:
                pass

        items = driver_instance.find_elements(
            By.CSS_SELECTOR, ".comment-item, .css-*, [class*='comment']"
        )
        for item in items:
            try:
                content = item.text.strip()
                if content and len(content) < 300:
                    results.append({"user": "", "content": content})
            except Exception:
                pass
    except Exception:
        pass

    unique = []
    seen = set()
    for row in results:
        key = row["content"]
        if key not in seen:
            unique.append(row)
            seen.add(key)
    return unique
