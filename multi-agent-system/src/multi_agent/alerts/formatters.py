"""
Alert message formatters.

format_alert(event) → Markdown string suitable for Telegram sendMessage.
- Emoji by severity: 🚨 CRITICAL / 🔄 WARN / ℹ️ INFO
- Timestamp in ART (Argentina Time, UTC-3)
- Key payload fields in **bold**
- Each event type has a dedicated section builder
"""
from __future__ import annotations

from datetime import timezone, timedelta
from zoneinfo import ZoneInfo

from .events import AlertEvent, AlertEventType, AlertSeverity

_ART = ZoneInfo("America/Argentina/Buenos_Aires")

_EMOJI = {
    AlertSeverity.CRITICAL: "🚨",
    AlertSeverity.WARN: "🔄",
    AlertSeverity.INFO: "ℹ️",
}


def _ts(event: AlertEvent) -> str:
    """Format event timestamp in ART for display."""
    local = event.created_at.astimezone(_ART)
    return local.strftime("%Y-%m-%d %H:%M:%S ART")


def _escape(text: str) -> str:
    """Minimal Markdown escaping for Telegram MarkdownV1."""
    # Only escape characters that break Telegram MarkdownV1 parsing
    return str(text).replace("_", r"\_").replace("*", r"\*").replace("`", r"\`")


def format_alert(event: AlertEvent, *, retry_delay_min: int | None = None) -> str:
    """Return a Telegram-ready Markdown string for the given AlertEvent."""
    emoji = _EMOJI.get(event.severity, "ℹ️")
    header = f"{emoji} *{event.severity.value}* — {_escape(event.title)}"
    delay_note = f" (+{retry_delay_min}min via retry)" if retry_delay_min else ""
    ts_line = f"_⏱ {_ts(event)}{delay_note}_"

    body = _format_body(event)

    parts = [header, ts_line]
    if body:
        parts.append(body)
    if event.correlation_id:
        parts.append(f"_corr: `{str(event.correlation_id)[:8]}…`_")

    return "\n".join(parts)


def _format_body(event: AlertEvent) -> str:
    p = event.payload
    t = event.event_type

    if t == AlertEventType.MARGIN_BREACH:
        return (
            f"*Symbol:* {_escape(p.get('symbol', 'N/A'))}\n"
            f"*Exposure:* {p.get('exposure_pct', 'N/A')}%  "
            f"*Limit:* {p.get('limit_pct', 'N/A')}%"
        )
    if t == AlertEventType.STOP_LOSS_HIT:
        return (
            f"*Ticker:* {_escape(p.get('ticker', 'N/A'))}\n"
            f"*PnL:* {p.get('pnl_pct', 'N/A')}%  "
            f"*Position:* {_escape(str(p.get('position_id', 'N/A')))}"
        )
    if t == AlertEventType.SYSTEM_FAILURE:
        return (
            f"*Component:* {_escape(p.get('component', 'N/A'))}\n"
            f"*Error:* {_escape(str(p.get('error_msg', 'N/A'))[:200])}"
        )
    if t == AlertEventType.ROLL_OPPORTUNITY:
        return (
            f"*Ticker:* {_escape(p.get('ticker', 'N/A'))}\n"
            f"*Expiry:* {p.get('expiry_date', 'N/A')}  "
            f"*DTE:* {p.get('dte', 'N/A')}  "
            f"*IV:* {p.get('current_iv', 'N/A')}%"
        )
    return ""
