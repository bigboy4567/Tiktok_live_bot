import os
import subprocess
import sys
import threading
import time

import matplotlib
import requests
import tik_backend
from flask import render_template_string, request
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

matplotlib.use("QtAgg")

save_config_to_json = tik_backend.save_config_to_json
set_status = tik_backend.set_status
get_bandwidth = tik_backend.get_bandwidth
requires_auth = tik_backend.requires_auth
toggle_running = tik_backend.toggle_running
send_message_to_tiktok = tik_backend.send_message_to_tiktok
app = tik_backend.app


class CharLimitDialog(QDialog):
    def __init__(self, parent=None, max_chars=100, initial_text=""):
        super().__init__(parent)
        self.setWindowTitle("Nouveau Message")
        self.max_chars = max_chars

        layout = QVBoxLayout()
        label = QLabel("Entrez le message :")
        layout.addWidget(label)

        self.text_input = QLineEdit()
        self.text_input.setText(initial_text)
        layout.addWidget(self.text_input)

        current_len = len(initial_text)
        self.char_counter = QLabel(f"{current_len} / {max_chars} caracteres")
        self.char_counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.char_counter.setStyleSheet("color: green;")
        layout.addWidget(self.char_counter)

        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("OK")
        self.btn_cancel = QPushButton("Annuler")
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.setLayout(layout)
        self.text_input.textChanged.connect(self.update_counter)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.setMinimumWidth(400)

    def update_counter(self, text):
        current_len = len(text)
        self.char_counter.setText(f"{current_len} / {self.max_chars} caracteres")
        if current_len > self.max_chars:
            self.char_counter.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.char_counter.setStyleSheet("color: green;")

    def get_text(self):
        return self.text_input.text()


class BotWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Controle TikTok Bot (PyQt6)")
        self.resize(840, 900)

        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.setStyle("Fusion")
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(17, 17, 17))
            palette.setColor(QPalette.ColorRole.Base, QColor(27, 27, 31))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(24, 24, 28))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(234, 234, 234))
            palette.setColor(QPalette.ColorRole.Text, QColor(234, 234, 234))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(234, 234, 234))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(234, 234, 234))
            palette.setColor(QPalette.ColorRole.Button, QColor(32, 32, 36))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 242, 234))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
            app_instance.setPalette(palette)

        self.setStyleSheet(self._qss())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.setCentralWidget(self.tabs)

        self.tab_control = QWidget()
        self.tabs.addTab(self.tab_control, "Controle")
        self._build_control_tab()

        self.tab_messages = QWidget()
        self.tabs.addTab(self.tab_messages, "Messages")
        self._build_messages_tab()

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.update_stats_ui)
        self.ui_timer.start(1000)

    def _header(self, parent_layout, title_text, subtitle_text=""):
        wrap = QVBoxLayout()
        lbl_title = QLabel(title_text)
        lbl_title.setObjectName("pageTitle")
        wrap.addWidget(lbl_title, alignment=Qt.AlignmentFlag.AlignHCenter)
        if subtitle_text:
            lbl_sub = QLabel(subtitle_text)
            lbl_sub.setObjectName("pageSubtitle")
            wrap.addWidget(lbl_sub, alignment=Qt.AlignmentFlag.AlignHCenter)
        parent_layout.addLayout(wrap)

    def _card(self, parent_layout, title=None):
        frame = QFrame()
        frame.setObjectName("card")
        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(14, 12, 14, 12)
        vbox.setSpacing(10)
        if title:
            t = QLabel(title)
            t.setObjectName("cardTitle")
            vbox.addWidget(t)
        parent_layout.addWidget(frame)
        return vbox

    def _build_control_tab(self):
        base = QVBoxLayout(self.tab_control)
        base.setContentsMargins(16, 16, 16, 16)
        base.setSpacing(14)

        self._header(
            base,
            "Panel de controle TikTok Bot",
            "Actions rapides et telemetrie en temps reel",
        )

        card_send = self._card(base, "Envoi manuel")
        hl_msg = QHBoxLayout()
        self.msg_edit = QLineEdit()
        self.msg_edit.setPlaceholderText("Message a envoyer...")
        btn_send = QPushButton("Envoyer")
        btn_send.setObjectName("accentButton")
        btn_send.clicked.connect(self.on_send_message)
        hl_msg.addWidget(self.msg_edit)
        hl_msg.addWidget(btn_send)
        card_send.addLayout(hl_msg)

        card_like = self._card(base, "Auto-like")
        hl_btns = QHBoxLayout()
        btn_start = QPushButton("Demarrer")
        btn_start.setObjectName("accentButton")
        btn_stop = QPushButton("Arreter")
        btn_stop.setObjectName("dangerButton")
        btn_start.clicked.connect(lambda: self.set_running(True))
        btn_stop.clicked.connect(lambda: self.set_running(False))
        hl_btns.addWidget(btn_start)
        hl_btns.addWidget(btn_stop)
        card_like.addLayout(hl_btns)

        card_toggles = self._card(base, "Automations")
        self.chk_auto = QCheckBox("Activer l'envoi automatique de messages (liste)")
        self.chk_auto.setChecked(tik_backend.ENABLE_AUTO_MESSAGES)
        self.chk_auto.stateChanged.connect(self.on_toggle_auto_messages)
        card_toggles.addWidget(self.chk_auto)

        card_stats = self._card(base, "Statistiques")
        badges = QHBoxLayout()
        self.lbl_auto_status = QLabel("Auto-messages : OFF")
        self.lbl_auto_status.setObjectName("badge")
        self.lbl_msg_count = QLabel("Messages configures : 0")
        self.lbl_msg_count.setObjectName("badge")
        badges.addWidget(self.lbl_auto_status)
        badges.addWidget(self.lbl_msg_count)
        card_stats.addLayout(badges)

        grid = QVBoxLayout()
        self.lbl_likes = QLabel("Likes envoyes : 0")
        self.lbl_uptime = QLabel("Temps de fonctionnement : 0s")
        self.lbl_next_pause = QLabel("Prochaine pause : -")
        self.lbl_status = QLabel("Status: En attente...")
        for lab in [self.lbl_likes, self.lbl_uptime, self.lbl_next_pause, self.lbl_status]:
            lab.setObjectName("statLine")
            grid.addWidget(lab)
        card_stats.addLayout(grid)

        self.fig = Figure(figsize=(6.6, 1.8), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_ylim(0, 100)
        self.ax.set_title("Upload / Download (KB/s)", fontsize=9, color="#eaeaea")
        self.ax.set_facecolor("#1b1b1f")
        self.ax.get_xaxis().set_visible(False)
        for spine in self.ax.spines.values():
            spine.set_color("#2a2a2a")
        self.ax.tick_params(colors="#b7b7b7")
        self.canvas = FigureCanvasQTAgg(self.fig)
        card_stats.addWidget(self.canvas)

    def _build_messages_tab(self):
        base = QVBoxLayout(self.tab_messages)
        base.setContentsMargins(16, 16, 16, 16)
        base.setSpacing(14)

        self._header(
            base,
            "Gestion des Messages Automatiques",
            "Ajouter, modifier et prioriser les messages",
        )

        card_info = self._card(base)
        self.lbl_count = QLabel(f"Messages configures : {len(tik_backend.AUTO_MESSAGES)}")
        self.lbl_count.setObjectName("badge")
        card_info.addWidget(self.lbl_count)

        card_list = self._card(base, "Messages")
        self.list_messages = QListWidget()
        card_list.addWidget(self.list_messages)
        self.refresh_messages_list()

        row = QHBoxLayout()
        btn_add = QPushButton("Ajouter")
        btn_add.setObjectName("accentButton")
        btn_edit = QPushButton("Modifier")
        btn_edit.setObjectName("ghostButton")
        btn_del = QPushButton("Supprimer")
        btn_del.setObjectName("dangerButton")
        btn_clear = QPushButton("Tout effacer")
        btn_clear.setObjectName("ghostButton")
        btn_add.clicked.connect(self.add_message)
        btn_edit.clicked.connect(self.edit_message)
        btn_del.clicked.connect(self.delete_message)
        btn_clear.clicked.connect(self.clear_all_messages)
        for btn in (btn_add, btn_edit, btn_del, btn_clear):
            row.addWidget(btn)
        card_list.addLayout(row)

    def on_send_message(self):
        txt = self.msg_edit.text().strip()
        if txt:
            send_message_to_tiktok(txt)
            self.msg_edit.clear()

    def set_running(self, val):
        tik_backend.running = val
        if val and not tik_backend.bot_start_time:
            tik_backend.bot_start_time = time.time()
        set_status("Auto-like demarre" if val else "Auto-like arrete")

    def on_toggle_auto_messages(self, state):
        tik_backend.ENABLE_AUTO_MESSAGES = state == Qt.CheckState.Checked.value
        save_config_to_json()
        set_status(
            "Auto-messages actives et sauvegardes"
            if tik_backend.ENABLE_AUTO_MESSAGES
            else "Auto-messages desactives et sauvegardes"
        )

    def refresh_messages_list(self):
        self.list_messages.clear()
        for i, msg in enumerate(tik_backend.AUTO_MESSAGES, 1):
            display = msg[:60] + "..." if len(msg) > 60 else msg
            self.list_messages.addItem(f"{i}. {display}")
        if hasattr(self, "lbl_count") and self.lbl_count is not None:
            self.lbl_count.setText(f"Messages configures : {len(tik_backend.AUTO_MESSAGES)}")

    def add_message(self):
        dialog = CharLimitDialog(self, max_chars=100)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_msg = dialog.get_text().strip()
            if len(new_msg) > 100:
                QMessageBox.warning(
                    self, "Validation", "Le message ne peut pas depasser 100 caracteres."
                )
                return
            if new_msg:
                tik_backend.AUTO_MESSAGES.append(new_msg)
                self.refresh_messages_list()
                save_config_to_json()
                set_status(f"Message ajoute et sauvegarde : {new_msg[:30]}...")
            else:
                QMessageBox.warning(self, "Validation", "Le message ne peut pas etre vide.")

    def edit_message(self):
        current = self.list_messages.currentRow()
        if current < 0 or current >= len(tik_backend.AUTO_MESSAGES):
            QMessageBox.warning(
                self, "Selection", "Veuillez selectionner un message a modifier."
            )
            return

        dialog = CharLimitDialog(
            self, max_chars=100, initial_text=tik_backend.AUTO_MESSAGES[current]
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_msg = dialog.get_text().strip()
            if len(new_msg) > 100:
                QMessageBox.warning(
                    self, "Validation", "Le message ne peut pas depasser 100 caracteres."
                )
                return
            if new_msg:
                tik_backend.AUTO_MESSAGES[current] = new_msg
                self.refresh_messages_list()
                save_config_to_json()
                set_status("Message modifie et sauvegarde")
            else:
                QMessageBox.warning(self, "Validation", "Le message ne peut pas etre vide.")

    def delete_message(self):
        current = self.list_messages.currentRow()
        if current < 0 or current >= len(tik_backend.AUTO_MESSAGES):
            QMessageBox.warning(
                self, "Selection", "Veuillez selectionner un message a supprimer."
            )
            return
        confirm = QMessageBox.question(
            self, "Confirmation", "Etes-vous sur de vouloir supprimer ce message ?"
        )
        if confirm == QMessageBox.StandardButton.Yes:
            del tik_backend.AUTO_MESSAGES[current]
            self.refresh_messages_list()
            save_config_to_json()
            set_status("Message supprime et sauvegarde")

    def clear_all_messages(self):
        confirm = QMessageBox.question(
            self, "Confirmation", "Etes-vous sur de vouloir supprimer TOUS les messages ?"
        )
        if confirm == QMessageBox.StandardButton.Yes:
            tik_backend.AUTO_MESSAGES.clear()
            self.refresh_messages_list()
            save_config_to_json()
            set_status("Tous les messages supprimes et sauvegardes")

    def update_stats_ui(self):
        uptime = 0
        if tik_backend.bot_start_time:
            uptime = int(time.time() - tik_backend.bot_start_time)

        self.lbl_likes.setText(f"Likes envoyes : {tik_backend.likes_sent}")
        self.lbl_uptime.setText(f"Temps de fonctionnement : {uptime}s")

        if tik_backend.next_pause_time:
            remaining = int(max(0, tik_backend.next_pause_time - time.time()))
            self.lbl_next_pause.setText(f"Prochaine pause : {remaining}s")
        else:
            self.lbl_next_pause.setText("Prochaine pause : -")

        self.lbl_auto_status.setText(
            f"Auto-messages : {'ON' if tik_backend.ENABLE_AUTO_MESSAGES else 'OFF'}"
        )
        self.lbl_msg_count.setText(
            f"Messages configures : {len(tik_backend.AUTO_MESSAGES)}"
        )
        self.lbl_status.setText(f"Status: {tik_backend.status_message}")

        try:
            up, down = get_bandwidth()
            tik_backend.bandwidth_data["time"].append(time.time())
            tik_backend.bandwidth_data["upload"].append(up)
            tik_backend.bandwidth_data["download"].append(down)
            if len(tik_backend.bandwidth_data["upload"]) > 30:
                tik_backend.bandwidth_data["upload"].pop(0)
                tik_backend.bandwidth_data["download"].pop(0)
                tik_backend.bandwidth_data["time"].pop(0)

            self.ax.clear()
            self.ax.set_facecolor("#1b1b1f")
            self.ax.plot(
                tik_backend.bandwidth_data["upload"],
                label="up",
                color="#00f2ea",
                linewidth=1.5,
            )
            self.ax.plot(
                tik_backend.bandwidth_data["download"],
                label="down",
                color="#9f9f9f",
                linewidth=1.2,
                linestyle="--",
            )
            ymax = max(
                100,
                max(
                    tik_backend.bandwidth_data["upload"]
                    + tik_backend.bandwidth_data["download"]
                    + [0]
                ),
            )
            self.ax.set_ylim(0, ymax)
            self.ax.get_xaxis().set_visible(False)
            self.ax.legend(
                loc="upper right",
                fontsize=7,
                facecolor="#1b1b1f",
                edgecolor="#2a2a2a",
            )
            for spine in self.ax.spines.values():
                spine.set_color("#2a2a2a")
            self.ax.tick_params(colors="#b7b7b7")
            self.ax.set_title("Upload / Download (KB/s)", fontsize=9, color="#eaeaea")
            self.canvas.draw_idle()
        except Exception:
            pass

    def _qss(self):
        return """
        QWidget {
            background-color: #111111;
            color: #eaeaea;
            font-size: 13px;
        }
        #pageTitle {
            font-size: 20px;
            font-weight: 700;
            color: #00f2ea;
            padding: 4px 0 2px 0;
        }
        #pageSubtitle {
            font-size: 12px;
            color: #b7b7b7;
        }
        QTabWidget::pane {
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            margin-top: 8px;
            background: #1b1b1f;
        }
        QTabBar::tab {
            padding: 8px 14px;
            margin-right: 6px;
            color: #cfcfcf;
            background: transparent;
            border: 1px solid transparent;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        }
        QTabBar::tab:selected {
            color: #ffffff;
            background: #1b1b1f;
            border: 1px solid #2a2a2a;
            border-bottom: 2px solid #00f2ea;
        }
        #card {
            background: #1b1b1f;
            border: 1px solid #2a2a2a;
            border-radius: 12px;
        }
        #cardTitle {
            font-size: 14px;
            font-weight: 600;
            color: #eaeaea;
            margin-bottom: 2px;
        }
        QLabel#badge {
            background: rgba(0,242,234,0.12);
            color: #aef7f4;
            border: 1px solid rgba(0,242,234,0.35);
            border-radius: 10px;
            padding: 4px 8px;
        }
        QLabel#statLine {
            color: #a8a8a8;
        }
        QLineEdit {
            background: #17171a;
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            padding: 8px 10px;
            selection-background-color: #00f2ea;
            selection-color: #000000;
        }
        QListWidget {
            background: #17171a;
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            padding: 6px;
        }
        QPushButton {
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            padding: 8px 12px;
            background: #202024;
            color: #eaeaea;
        }
        QPushButton#accentButton {
            background: #00f2ea;
            color: #000000;
            border-color: #00c9c3;
        }
        QPushButton#dangerButton {
            background: #2a191b;
            color: #ffb3b8;
            border-color: #5a2a2f;
        }
        QPushButton#ghostButton {
            background: transparent;
            color: #cfcfcf;
            border-color: #2a2a2a;
        }
        """


def launch_pyqt_control():
    app_qt = QApplication.instance() or QApplication(sys.argv)
    win = BotWindow()
    win.show()
    app_qt.exec()


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
        h2 { color: #00f2ea; margin-top: 30px; }
        .btn { background: #00f2ea; border: none; padding: 12px 20px; margin: 5px; border-radius: 6px; cursor: pointer; font-size: 16px; transition: 0.3s; color: #121212; }
        .btn:hover { background: #00bfb3; }
        .btn-danger { background: #ff4757; color: white; }
        .btn-danger:hover { background: #ff3838; }
        .btn-small { padding: 8px 12px; font-size: 14px; margin: 2px; }
        input, textarea { padding: 10px; margin: 10px; border-radius: 6px; border: none; width: 80%; max-width: 400px; background: #1e1e2f; color: #f5f5f5; }
        .card { background: #1e1e2f; padding: 20px; border-radius: 10px; margin-top: 20px; }
        #status { margin-top: 20px; font-size: 18px; }
        label { display: block; margin: 10px; }
        .message-list { max-height: 300px; overflow-y: auto; background: #121212; border-radius: 6px; padding: 10px; margin: 10px 0; text-align: left; }
        .message-item { background: #1e1e2f; padding: 10px; margin: 5px 0; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }
        .message-text { flex-grow: 1; margin-right: 10px; word-break: break-word; }
        .message-actions { display: flex; gap: 5px; }
        .input-group { display: flex; align-items: center; justify-content: center; gap: 10px; margin: 10px 0; }
        .input-group input { margin: 0; }
    </style>
</head>
<body>
    <h1>Bot TikTok</h1>
    <div class="card">
        <form method="post" action="/control">
            <button class="btn" name="action" value="start">Demarrer</button>
            <button class="btn" name="action" value="stop">Arreter</button>
            <br>
            <input type="text" name="live_url" placeholder="Lien TikTok Live">
            <button class="btn" name="action" value="change_live">Changer Live</button>
            <br>
            <label>
                <input type="checkbox" name="auto_messages" onchange="this.form.submit()" {{'checked' if auto_messages else ''}}>
                Activer l'envoi auto de messages
            </label>
        </form>
    </div>
    <div class="card">
        <h2>Gestion des Auto-Messages</h2>
        <div class="input-group">
            <input type="text" id="newMessage" placeholder="Nouveau message..." maxlength="200">
            <button class="btn" onclick="addMessage()">Ajouter</button>
        </div>
        <div class="message-list" id="messagesList">
            {% for message in messages %}
            <div class="message-item" data-index="{{ loop.index0 }}">
                <span class="message-text">{{ loop.index }}. {{ message }}</span>
                <div class="message-actions">
                    <button class="btn btn-small" onclick='editMessage({{ loop.index0 }}, {{ message|tojson }})'>Modifier</button>
                    <button class="btn btn-small btn-danger" onclick="deleteMessage({{ loop.index0 }})">Supprimer</button>
                </div>
            </div>
            {% endfor %}
        </div>
        <div style="margin-top: 15px;">
            <button class="btn btn-danger" onclick="clearAllMessages()" {% if not messages %}disabled{% endif %}>Tout effacer</button>
            <span style="margin-left: 20px;">Messages configures : <strong id="messageCount">{{ messages|length }}</strong></span>
        </div>
    </div>
    <div class="card">
        <h2>Statistiques</h2>
        <p>Likes envoyes : <span id="likes">0</span></p>
        <p>Temps de fonctionnement : <span id="uptime">0s</span></p>
        <p>Prochaine pause prevue : <span id="next_pause">-</span></p>
        <p>Auto-messages : <span id="auto_status">{{ 'ON' if auto_messages else 'OFF' }}</span></p>
        <p>Messages configures : <span id="message_count">{{ messages|length }}</span></p>
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
                    document.getElementById("messageCount").innerText = data.message_count;
                });
        }, 2000);

        function addMessage() {
            const input = document.getElementById('newMessage');
            const message = input.value.trim();
            if (!message) { alert('Veuillez saisir un message'); return; }
            if (message.length > 200) { alert('Le message est trop long (max 200 caracteres)'); return; }
            fetch('/messages', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'action=add&message=' + encodeURIComponent(message)
            })
            .then(response => response.json())
            .then(data => { if (data.success) { location.reload(); } else { alert('Erreur: ' + data.error); } });
        }

        function editMessage(index, currentMessage) {
            const newMessage = prompt('Modifier le message:', currentMessage);
            if (newMessage === null) return;
            if (!newMessage.trim()) { alert('Le message ne peut pas etre vide'); return; }
            fetch('/messages', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'action=edit&index=' + index + '&message=' + encodeURIComponent(newMessage.trim())
            })
            .then(response => response.json())
            .then(data => { if (data.success) { location.reload(); } else { alert('Erreur: ' + data.error); } });
        }

        function deleteMessage(index) {
            if (!confirm('Etes-vous sur de vouloir supprimer ce message ?')) { return; }
            fetch('/messages', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'action=delete&index=' + index
            })
            .then(response => response.json())
            .then(data => { if (data.success) { location.reload(); } else { alert('Erreur: ' + data.error); } });
        }

        function clearAllMessages() {
            if (!confirm('Etes-vous sur de vouloir supprimer TOUS les messages ?')) { return; }
            fetch('/messages', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'action=clear'
            })
            .then(response => response.json())
            .then(data => { if (data.success) { location.reload(); } else { alert('Erreur: ' + data.error); } });
        }

        document.getElementById('newMessage').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') { addMessage(); }
        });
    </script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
@requires_auth
def index():
    return render_template_string(
        HTML_PAGE,
        auto_messages=tik_backend.ENABLE_AUTO_MESSAGES,
        messages=tik_backend.AUTO_MESSAGES,
    )


@app.route("/messages", methods=["POST"])
@requires_auth
def manage_messages():
    action = request.form.get("action")
    try:
        if action == "add":
            message = request.form.get("message", "").strip()
            if not message:
                return {"success": False, "error": "Message vide"}
            if len(message) > 200:
                return {"success": False, "error": "Message trop long"}
            tik_backend.AUTO_MESSAGES.append(message)
            save_config_to_json()
            set_status(f"Message ajoute via web : {message[:30]}...")
            return {"success": True}

        if action == "edit":
            index_i = int(request.form.get("index"))
            message = request.form.get("message", "").strip()
            if not message:
                return {"success": False, "error": "Message vide"}
            if index_i < 0 or index_i >= len(tik_backend.AUTO_MESSAGES):
                return {"success": False, "error": "Index invalide"}
            tik_backend.AUTO_MESSAGES[index_i] = message
            save_config_to_json()
            set_status("Message modifie via web")
            return {"success": True}

        if action == "delete":
            index_i = int(request.form.get("index"))
            if index_i < 0 or index_i >= len(tik_backend.AUTO_MESSAGES):
                return {"success": False, "error": "Index invalide"}
            deleted_msg = tik_backend.AUTO_MESSAGES.pop(index_i)
            save_config_to_json()
            set_status(f"Message supprime via web : {deleted_msg[:30]}...")
            return {"success": True}

        if action == "clear":
            tik_backend.AUTO_MESSAGES.clear()
            save_config_to_json()
            set_status("Tous les messages supprimes via web")
            return {"success": True}

        return {"success": False, "error": "Action invalide"}
    except Exception as e:
        set_status(f"Erreur gestion messages web : {e}")
        return {"success": False, "error": str(e)}


@app.route("/control", methods=["POST"])
@requires_auth
def control():
    action = request.form.get("action")
    live_url = request.form.get("live_url", "").strip()
    auto_messages_toggle = request.form.get("auto_messages")

    new_auto_state = auto_messages_toggle is not None
    if new_auto_state != tik_backend.ENABLE_AUTO_MESSAGES:
        tik_backend.ENABLE_AUTO_MESSAGES = new_auto_state
        save_config_to_json()
        set_status(
            "Auto-messages actives"
            if tik_backend.ENABLE_AUTO_MESSAGES
            else "Auto-messages desactives"
        )

    if action == "start":
        if not tik_backend.running:
            toggle_running()
    elif action == "stop":
        tik_backend.running = False
        set_status("Bot arrete via web")
    elif action == "change_live" and live_url:
        tik_backend.current_live = live_url
        if tik_backend.driver:
            tik_backend.driver.get(tik_backend.current_live)
        set_status(f"Live change : {tik_backend.current_live}")

    return render_template_string(
        HTML_PAGE,
        auto_messages=tik_backend.ENABLE_AUTO_MESSAGES,
        messages=tik_backend.AUTO_MESSAGES,
    )


@app.route("/status", methods=["GET"])
@requires_auth
def status():
    uptime = "0s"
    if tik_backend.bot_start_time:
        uptime = f"{int(time.time() - tik_backend.bot_start_time)}s"
    next_pause_str = "-"
    if tik_backend.next_pause_time:
        next_pause_str = f"{int(max(0, tik_backend.next_pause_time - time.time()))}s"
    return {
        "status": tik_backend.status_message,
        "likes": tik_backend.likes_sent,
        "uptime": uptime,
        "next_pause": next_pause_str,
        "auto_messages": tik_backend.ENABLE_AUTO_MESSAGES,
        "message_count": len(tik_backend.AUTO_MESSAGES),
    }


def clear_terminal():
    if not tik_backend.ENABLE_TERMINAL_CLEAR:
        set_status("Nettoyage terminal desactive (ENABLE_TERMINAL_CLEAR=false).")
        return
    while True:
        time.sleep(tik_backend.CLEAR_INTERVAL)
        os.system("cls" if os.name == "nt" else "clear")
        set_status("Terminal nettoye automatiquement.")


def close_driver():
    if tik_backend.driver:
        try:
            tik_backend.driver.quit()
            set_status("Fenetre Selenium fermee.")
        except Exception:
            pass


def launch_ngrok():
    try:
        subprocess.Popen(
            ["ngrok", "http", "5000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ngrok_url = None
        for _ in range(10):
            try:
                response = requests.get(
                    "http://127.0.0.1:4040/api/tunnels",
                    timeout=5,
                )
                response.raise_for_status()
                tunnels = response.json().get("tunnels", [])
                if tunnels:
                    ngrok_url = tunnels[0].get("public_url")
                    break
            except requests.RequestException:
                pass
            time.sleep(1)

        if not ngrok_url:
            raise RuntimeError("Tunnel ngrok introuvable apres attente.")

        tik_backend.ngrok_url = ngrok_url
        set_status(f"URL publique ngrok : {ngrok_url}")
        tik_backend.send_email_alert("Bot TikTok - Ngrok", f"Ton URL ngrok : {ngrok_url}")
    except Exception as e:
        set_status(f"Erreur ngrok : {e}")


if __name__ == "__main__":
    flask_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False),
        daemon=True,
    )
    flask_thread.start()

    threading.Thread(target=launch_ngrok, daemon=True).start()
    threading.Thread(target=clear_terminal, daemon=True).start()
    threading.Thread(target=tik_backend.refresh_live_loop, daemon=True).start()
    threading.Thread(target=tik_backend.auto_message_loop, daemon=True).start()

    threading.Thread(target=tik_backend.launch_driver, daemon=True).start()
    threading.Thread(target=tik_backend.auto_like, daemon=True).start()

    launch_pyqt_control()
