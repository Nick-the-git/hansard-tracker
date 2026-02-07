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


def create_alert(
    member_id: int,
    member_name: str,
    email: str,
    topics: Optional[list[str]] = None,
) -> dict:
    """Create a new alert for a member, optionally filtered by topics."""
    alerts = _load_alerts()

    # Check for duplicate
    for alert in alerts:
        if alert["member_id"] == member_id and alert["email"] == email:
            # Update topics if they've changed
            if topics is not None:
                alert["topics"] = topics
                _save_alerts(alerts)
            return alert

    alert = {
        "id": len(alerts) + 1,
        "member_id": member_id,
        "member_name": member_name,
        "email": email,
        "topics": topics or [],
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
    matched_info: Optional[list[dict]] = None,
):
    """Send an email notification about new contributions (sync wrapper).

    If matched_info is provided (from LLM filtering), it contains topic/reason
    data that gets included in the notification.
    """
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("ALERT_FROM_EMAIL", smtp_user)

    # Build a lookup from contribution_id to match info
    match_lookup = {}
    if matched_info:
        for m in matched_info:
            match_lookup[m["contribution_id"]] = m

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
            info = match_lookup.get(c.contribution_id)
            if info:
                print(f"  Topics: {', '.join(info.get('matched_topics', []))}")
                print(f"  Reason: {info.get('reason', '')}")
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
        text_lines.append(f"  Preview: {c.text[:200]}...")
        info = match_lookup.get(c.contribution_id)
        if info:
            text_lines.append(f"  Topics: {', '.join(info.get('matched_topics', []))}")
            text_lines.append(f"  Why: {info.get('reason', '')}")
        text_lines.append("")
    text_body = "\n".join(text_lines)

    # HTML version
    html_items = ""
    for c in contributions:
        info = match_lookup.get(c.contribution_id)
        topic_badge = ""
        if info and info.get("matched_topics"):
            badges = " ".join(
                f'<span style="background:#1d70b8;color:white;padding:2px 8px;'
                f'border-radius:12px;font-size:12px;margin-right:4px;">{t}</span>'
                for t in info["matched_topics"]
            )
            reason = info.get("reason", "")
            topic_badge = f"""
                <p style="margin: 4px 0;">{badges}</p>
                <p style="margin: 0 0 4px 0; color: #505a5f; font-size: 13px; font-style: italic;">
                    🤖 {reason}
                </p>
            """

        html_items += f"""
        <div style="margin-bottom: 16px; padding: 12px; border-left: 3px solid #1d70b8; background: #f3f2f1;">
            <p style="margin: 0 0 4px 0; font-weight: bold;">{c.debate_title}</p>
            <p style="margin: 0 0 4px 0; color: #505a5f; font-size: 14px;">
                {c.sitting_date.split('T')[0]} &middot; {c.section} &middot; {c.house}
            </p>
            {topic_badge}
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
    """Check all active alerts for new contributions.

    If an alert has topics set and a Gemini API key is available,
    uses the LLM to filter contributions by topic relevance.
    Only sends notifications for genuinely relevant speeches.
    """
    alerts = _load_alerts()
    updated = False

    for alert in alerts:
        if not alert.get("active", True):
            continue

        member_id = alert["member_id"]
        member_name = alert["member_name"]
        last_checked = alert["last_checked"]
        since_date = last_checked.split("T")[0]
        topics = alert.get("topics", [])

        try:
            contributions = get_latest_contributions(
                member_id=member_id,
                since_date=since_date,
            )

            if contributions:
                matched_info = None

                # If topics are set and Gemini is available, filter by relevance
                if topics and os.getenv("GEMINI_API_KEY"):
                    try:
                        from app.llm import filter_contributions_by_topics

                        matched = filter_contributions_by_topics(
                            contributions=contributions,
                            topics=topics,
                            member_name=member_name,
                        )

                        if matched:
                            # Only send the contributions that matched
                            matched_ids = {m["contribution_id"] for m in matched}
                            contributions = [
                                c for c in contributions
                                if c.contribution_id in matched_ids
                            ]
                            matched_info = matched
                        else:
                            # None matched the topics — skip notification
                            logger.info(
                                f"Alert {alert['id']}: {len(contributions)} new speeches "
                                f"by {member_name} but none matched topics {topics}"
                            )
                            contributions = []

                    except Exception as e:
                        logger.warning(
                            f"Alert {alert['id']}: LLM filtering failed ({e}), "
                            f"sending all contributions unfiltered"
                        )
                        # Fall back to sending everything

                if contributions:
                    _send_email_sync(
                        to_email=alert["email"],
                        member_name=member_name,
                        contributions=contributions,
                        matched_info=matched_info,
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
