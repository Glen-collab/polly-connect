"""Email notifications for Polly Connect."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


def send_notification(subject: str, body: str):
    """Send an email notification to the admin."""
    from config import settings

    if not settings.GMAIL_APP_PASSWORD:
        logger.warning("GMAIL_APP_PASSWORD not set — skipping email notification")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Polly Connect <{settings.GMAIL_USER}>"
    msg["To"] = settings.NOTIFY_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.GMAIL_USER, settings.GMAIL_APP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Notification sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
        return False


def notify_new_registration(name: str, email: str, household: str):
    """Notify admin when a new user registers."""
    subject = f"New Polly Connect Registration: {name}"
    body = f"""
    <div style="font-family: sans-serif; max-width: 500px;">
        <h2 style="color: #059669;">New Registration</h2>
        <table style="border-collapse: collapse; width: 100%;">
            <tr><td style="padding: 8px; font-weight: bold;">Name</td><td style="padding: 8px;">{name}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Email</td><td style="padding: 8px;">{email}</td></tr>
            <tr><td style="padding: 8px; font-weight: bold;">Household</td><td style="padding: 8px;">{household}</td></tr>
        </table>
        <p style="color: #666; font-size: 12px; margin-top: 20px;">— Polly Connect</p>
    </div>
    """
    return send_notification(subject, body)
