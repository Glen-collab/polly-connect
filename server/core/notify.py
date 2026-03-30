"""Email notifications for Polly Connect."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


def send_notification(subject: str, body: str, to_email: str = None):
    """Send an email notification. Defaults to admin if no to_email specified."""
    from config import settings

    if not settings.GMAIL_APP_PASSWORD:
        logger.warning("GMAIL_APP_PASSWORD not set — skipping email notification")
        return False

    recipient = to_email or settings.NOTIFY_EMAIL
    msg = MIMEMultipart("alternative")
    msg["From"] = f"Polly Connect <{settings.GMAIL_USER}>"
    msg["To"] = recipient
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


def send_family_invitation(inviter_name: str, invitee_name: str, invitee_email: str,
                            family_code: str, invitation_id: int,
                            has_voice_message: bool = False,
                            base_url: str = "https://polly-connect.com"):
    """Send a family invitation email with the family code and link."""
    invite_url = f"{base_url}/web/family?invite={invitation_id}"

    voice_hook = ""
    if has_voice_message:
        voice_hook = f"""
        <div style="background: #f0fdf4; border: 2px solid #86efac; border-radius: 12px; padding: 20px; text-align: center; margin: 20px 0;">
            <p style="font-size: 18px; color: #166534; margin: 0 0 8px 0;">&#x1F3A4; {inviter_name} recorded a message for you</p>
            <p style="font-size: 13px; color: #15803d; margin: 0;">Click below to listen</p>
        </div>
        """
    else:
        voice_hook = f"""
        <div style="background: #f0fdf4; border: 2px solid #86efac; border-radius: 12px; padding: 20px; text-align: center; margin: 20px 0;">
            <p style="font-size: 18px; color: #166534; margin: 0;">{inviter_name} wants to share something with you</p>
        </div>
        """

    subject = f"{inviter_name} invited you to Polly Connect"
    body = f"""
    <div style="font-family: sans-serif; max-width: 500px; margin: 0 auto;">
        <div style="text-align: center; padding: 20px 0;">
            <span style="font-size: 48px;">&#x1F99C;</span>
            <h1 style="color: #059669; font-size: 24px; margin: 10px 0 5px 0;">Polly Connect</h1>
        </div>

        <h2 style="color: #1f2937; font-size: 20px; text-align: center;">
            Hi {invitee_name}!
        </h2>

        {voice_hook}

        <p style="color: #374151; font-size: 15px; line-height: 1.6; text-align: center;">
            Polly Connect is where families capture and share stories, messages, and memories
            across generations &mdash; through a friendly parrot-shaped device that listens,
            remembers, and connects.
        </p>

        <div style="text-align: center; margin: 25px 0;">
            <a href="{invite_url}"
               style="display: inline-block; background: #059669; color: white; font-size: 18px;
                      font-weight: bold; padding: 14px 32px; border-radius: 8px;
                      text-decoration: none;">
                Listen &amp; Get Started
            </a>
        </div>

        <div style="background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;
                    padding: 16px; text-align: center; margin: 20px 0;">
            <p style="color: #6b7280; font-size: 12px; margin: 0 0 4px 0;">Your access code</p>
            <p style="font-size: 28px; font-weight: bold; font-family: monospace;
                      letter-spacing: 6px; color: #059669; margin: 0;">
                {family_code}
            </p>
            <p style="color: #9ca3af; font-size: 11px; margin: 8px 0 0 0;">
                Enter this code at polly-connect.com/web/family
            </p>
        </div>

        <p style="color: #9ca3af; font-size: 11px; text-align: center; margin-top: 30px;">
            Polly Connect &mdash; Your Life, Your Voice, Your Growth
        </p>
    </div>
    """
    return send_notification(subject, body, to_email=invitee_email)
