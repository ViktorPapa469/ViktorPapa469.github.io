"""Optional Telegram delivery (fill TELEGRAM_* in config.py to enable)."""
import requests

import config as C


def enabled():
    return bool(C.TELEGRAM_BOT_TOKEN and C.TELEGRAM_CHAT_ID)


def send_text(text, log):
    if not enabled():
        return
    try:
        requests.post(f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}/sendMessage",
                      data={"chat_id": C.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=15)
    except requests.RequestException as e:
        log(f"WARN: Telegram message failed ({e})")


def send_file(path, caption, log):
    if not enabled():
        return
    try:
        with open(path, "rb") as fh:
            requests.post(f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}/sendDocument",
                          data={"chat_id": C.TELEGRAM_CHAT_ID, "caption": caption},
                          files={"document": fh}, timeout=30)
    except (OSError, requests.RequestException) as e:
        log(f"WARN: Telegram file failed ({e})")
