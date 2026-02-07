"""Alert system: polls Hansard for new contributions and sends notifications."""

from __future__ import annotations

import json
import os
import smtplib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.hansard_client import get_latest_contributions, Contribution


logger = logging.getLogger(__name__)

ALERTS_FILE = Path("./data/alerts.json")


def _load_alerts() -> list[dict]:
    if ALERTS_FILE.exists():
        return json.loads(ALERTS_FILE.read_text())
    return []


def _save_alerts(alerts: list[dict]):
    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERTS_FILE.write_text(json.dumps(alerts, indent=2, default=str))


def create_alert(member_id: int, member_name: str, email: str) -> dict:
    """Create a new alert for a member."""
    alerts = _load_alerts()

    # Check for duplicate
    for alert in alerts:
        if alert["member_id"] == member_id and alert["email"] == email:
            return alert

    alert = {
        "id": len(alerts) + 1,
        "member_id": member_id,
        "member_name": member_name,
        "email": email,
        "created_at": datetime.now().isoformat(),
        "last_checked": datetime.now().isoformat(),
        "active": True,
    }
    alerts.append(alert)
    _save_alerts(alerts)
    return alert


def get_alerts() -> list[dict]:
    return _load_alerts()


def get_alert(alert_id: int) -> Optional[dict]:
    alerts = _load_alerts()
    for alert in alerts:
        if alert["id"] == alert_id:
            return alert
    return None


def delete_alert(alert_id: int) -> bool:
    alerts = _load_alerts()
    new_alerts = [a for a in alerts if a["id"] != alert_id]
    if len(new_alerts) == len(alerts):
        return False
    _save_alerts(new_alerts)
    return True


def toggle_alert(alert_id: int) -> Optional[dict]:
    alerts = _load_alerts()
    for alert in alerts:
        if alert["id"] == alert_id:
            alert["active"] = not alert["active"]
            _save_alerts(alerts)
            return alert
    return None


def _send_email_sync(
    to_email: str,
    member_name: str,
    contributions: list[Contribution],
):
    """Send an email notification about new contributions (sync wrapper)."""
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("ALERT_FROM_EMAIL", smtp_user)

    if not all([smtp_host, smtp_user, smtp_password]):
        logger.warning("SMTP not configured — printing notification to console instead")
        print(f"\n{'='*60}")
        print(f"ALERT: {member_name} has new Hansard contributions!")
        print(f"{'='*60}")
        for c in contributions:
            print(f"\n  Date: {c.sitting_date.split('T')[0]}")
            print(f"  Debate: {c.debate_title}")
            print(f"  Section: {c.section}")
            print(f"  Link: {c.hansard_url}")
            print(f"  Preview: {c.text[:200]}...")
        print(f"{'='*60}\n")
        return

    # Build email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Hansard Alert: {member_name} spoke in Parliament"
    msg["From"] = from_email
    msg["To"] = to_email

    # Plain text version
    text_lines = [f"{member_name} has {len(contributions)} new contribution(s) in Hansard:\n"]
    for c in contributions:
        text_lines.append(f"- {c.sitting_date.split('T')[0]} | {c.debate_title}")
        text_lines.append(f"  {c.hansard_url}")
        text_lines.append(f"  Preview: {c.text[:200]}...\n")
    text_body = "\n".join(text_lines)

    # HTML version
    html_items = ""
    for c in contributions:
        html_items += f"""
        <div style="margin-bottom: 16px; padding: 12px; border-left: 3px solid #1d70b8; background: #f3f2f1;">
            <p style="margin: 0 0 4px 0; font-weight: bold;">{c.debate_title}</p>
            <p style="margin: 0 0 4px 0; color: #505a5f; font-size: 14px;">
                {c.sitting_date.split('T')[0]} &middot; {c.section} &middot; {c.house}
            </p>
            <p style="margin: 0 0 8px 0; font-size: 14px;">{c.text[:300]}...</p>
            <a href="{c.hansard_url}" style="color: #1d70b8;">Read full debate on Hansard &rarr;</a>
        </div>
        """

    html_body = f"""
    <html>
    <body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #0b0c0c;">{member_name} spoke in Parliament</h2>
        <p>{len(contributions)} new contribution(s) found:</p>
        {html_items}
        <hr style="border: none; border-top: 1px solid #b1b4b6; margin-top: 24px;">
        <p style="font-size: 12px; color: #505a5f;">
            Sent by Hansard Tracker.
        </p>
    </body>
    </html>
    """

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
    logger.info(f"Email notification sent to {to_email} about {member_name}")


def check_alerts():
    """Check all active alerts for new contributions."""
    alerts = _load_alerts()
    updated = False

    for alert in alerts:
        if not alert.get("active", True):
            continue

        member_id = alert["member_id"]
        member_name = alert["member_name"]
        last_checked = alert["last_checked"]
        since_date = last_checked.split("T")[0]

        try:
            contributions = get_latest_contributions(
                member_id=member_id,
                since_date=since_date,
            )

            if contributions:
                _send_email_sync(
                    to_email=alert["email"],
                    member_name=member_name,
                    contributions=contributions,
                )
                logger.info(
                    f"Alert {alert['id']}: Found {len(contributions)} new contributions "
                    f"for {member_name} since {since_date}"
                )

            alert["last_checked"] = datetime.now().isoformat()
            updated = True

        except Exception as e:
            logger.error(f"Alert {alert['id']}: Error checking {member_name}: {e}")

    if updated:
        _save_alerts(alerts)
