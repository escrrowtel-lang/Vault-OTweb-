"""Optional email (password reset). SMTP details sirf environment se aate hain, DB ya code mein nahi.
SMTP_HOST, SMTP_PORT (587 STARTTLS / 465 SSL), SMTP_USER, SMTP_PASS, SMTP_FROM
"""
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage


def configured():
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def _send(to, subject, body):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    msg = EmailMessage()
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    ctx = ssl.create_default_context()
    try:
        if port == 465:
            s = smtplib.SMTP_SSL(host, port, timeout=20, context=ctx)
        else:
            s = smtplib.SMTP(host, port, timeout=20)
            s.starttls(context=ctx)
        with s:
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
            s.send_message(msg)
    except Exception as e:  # noqa - mail fail hone se app nahi rukna chahiye
        print("mail error:", type(e).__name__)


def send_async(to, subject, body):
    if configured():
        threading.Thread(target=_send, args=(to, subject, body), daemon=True).start()
        return True
    return False
