#!/usr/bin/env python3
"""
Point d'entree principal pour lancer le bot TikTok.
"""

import threading

import tik_backend
from tik_frontend import clear_terminal, launch_ngrok, launch_pyqt_control


def main():
    tik_backend.logger.info("Demarrage du bot TikTok")
    tik_backend.logger.info("=" * 50)

    flask_thread = threading.Thread(
        target=lambda: tik_backend.app.run(
            host="0.0.0.0",
            port=5000,
            debug=False,
            use_reloader=False,
        ),
        daemon=True,
    )
    flask_thread.start()
    tik_backend.logger.info("Serveur Flask demarre sur http://0.0.0.0:5000")

    threading.Thread(target=launch_ngrok, daemon=True).start()
    tik_backend.logger.info("Ngrok lance")

    threading.Thread(target=clear_terminal, daemon=True).start()
    tik_backend.logger.info("Nettoyage terminal active")

    threading.Thread(target=tik_backend.refresh_live_loop, daemon=True).start()
    tik_backend.logger.info("Rafraichissement live active")

    threading.Thread(target=tik_backend.auto_message_loop, daemon=True).start()
    tik_backend.logger.info("Boucle auto-message active")

    threading.Thread(target=tik_backend.launch_driver, daemon=True).start()
    tik_backend.logger.info("Driver Selenium lance")

    threading.Thread(target=tik_backend.auto_like, daemon=True).start()
    tik_backend.logger.info("Auto-like active")

    tik_backend.logger.info("=" * 50)
    tik_backend.logger.info("Lancement de l'interface PyQt6")
    launch_pyqt_control()


if __name__ == "__main__":
    main()

