import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_password_reset_email(*, to_email: str, raw_token: str) -> None:
    reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={raw_token}"
    expire_minutes = settings.PASSWORD_RESET_EXPIRE_MINUTES

    subject = "Reset your Courseo password"
    text_body = (
        f"You requested a password reset for your Courseo account.\n\n"
        f"Reset your password: {reset_url}\n\n"
        f"This link expires in {expire_minutes} minutes.\n"
        f"If you did not request this, you can ignore this email."
    )
    html_body = f"""\
<p>You requested a password reset for your Courseo account.</p>
<p><a href="{reset_url}">Reset your password</a></p>
<p>This link expires in {expire_minutes} minutes.</p>
<p>If you did not request this, you can ignore this email.</p>
"""

    if not settings.smtp_configured():
        logger.warning(
            "SMTP not configured — password reset link for %s: %s",
            to_email,
            reset_url,
        )
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to_email
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)
