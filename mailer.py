# письмо с HTML телом и вложением Excel, по умолчанию кладется файлом .eml, отправка только по явному флагу

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def build_message(html, xlsx_path, subject, cfg):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["mail"]["from"]
    msg["To"] = ", ".join(cfg["mail"]["to"])
    msg.set_content("Отчет в HTML, откройте письмо в почтовом клиенте с поддержкой HTML. Подробности во вложении.")
    msg.add_alternative(html, subtype="html")
    data = Path(xlsx_path).read_bytes()
    msg.add_attachment(data, maintype="application", subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       filename=Path(xlsx_path).name)
    return msg


def save_eml(msg, path):
    Path(path).write_bytes(bytes(msg))


def send_smtp(msg):
    # параметры только из переменных окружения, в код пароль не кладем
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
