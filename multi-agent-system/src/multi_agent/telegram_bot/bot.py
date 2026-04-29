"""
Telegram bot — command handlers for @LakeAgents_bot.

Commands:
  /start   — welcome message
  /help    — list all commands
  /status  — current risk mode + NAV (from snapshot)
  /portfolio — portfolio summary (NAV, cash, beta, vega, drawdown)
  /positions — list all open positions
  /pnl     — PnL breakdown (daily, weekly, monthly)

Auth: all commands require chat_id in TELEGRAM_ALLOWED_CHAT_IDS (fail-closed).
Service calls: direct import of service layer (not HTTP) for efficiency.

Pool injection: the FastAPI lifespan injects the shared PostgresPool via
  tg_app.bot_data["pool"] = pool
before calling initialize(). Handlers access it via context.bot_data["pool"].
This ensures a single pool is used across the API and bot (no singleton divergence).

Lifecycle (integrated with FastAPI lifespan):
  tg_app.bot_data["pool"] = pool
  await tg_app.initialize()
  await tg_app.start()
  await tg_app.updater.start_polling()
  ...
  await tg_app.updater.stop()
  await tg_app.stop()
  await tg_app.shutdown()
"""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from multi_agent.config import settings
from .auth import require_auth

logger = logging.getLogger(__name__)
_ART = ZoneInfo("America/Argentina/Buenos_Aires")


# ── Handlers ──────────────────────────────────────────────────────────────────

@require_auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *LakeAgents Bot* activo.\nUsá /help para ver los comandos disponibles.",
        parse_mode="Markdown",
    )


@require_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Comandos disponibles:*\n"
        "/status — modo de riesgo + NAV actual\n"
        "/portfolio — resumen del portfolio\n"
        "/positions — posiciones abiertas\n"
        "/pnl — PnL diario / semanal / mensual\n"
        "/help — este mensaje"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@require_auth
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        snapshot, risk_mode = _get_snapshot_and_mode(context)
        nav = float(snapshot.nav_usd)
        ts = snapshot.snapshot_at.astimezone(_ART).strftime("%H:%M:%S ART")
        text = (
            f"*Estado del sistema*\n"
            f"🚦 Modo: *{risk_mode.value}*\n"
            f"💰 NAV: *${nav:,.0f}*\n"
            f"⏱ _snapshot: {ts}_"
        )
    except Exception as exc:
        logger.exception("cmd_status failed")
        text = f"⚠️ Error al obtener estado: {exc}"
    await update.message.reply_text(text, parse_mode="Markdown")


@require_auth
async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        snapshot, _ = _get_snapshot_and_mode(context)
        text = (
            f"*Portfolio*\n"
            f"💰 NAV: *${float(snapshot.nav_usd):,.0f}*\n"
            f"🏦 Cash: *${float(snapshot.cash_usd):,.0f}*\n"
            f"📊 Beta: *{snapshot.portfolio_beta:.2f}*\n"
            f"🌊 Vega: *{snapshot.vega_total:,.0f}*\n"
            f"📉 Drawdown: *{snapshot.drawdown_from_peak_pct:.2f}%*\n"
            f"⚡ Buying power used: *{snapshot.buying_power_used_pct:.1f}%*"
        )
    except Exception as exc:
        logger.exception("cmd_portfolio failed")
        text = f"⚠️ Error: {exc}"
    await update.message.reply_text(text, parse_mode="Markdown")


@require_auth
async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        snapshot, _ = _get_snapshot_and_mode(context)
        positions = snapshot.positions
        if not positions:
            await update.message.reply_text("_Sin posiciones abiertas._", parse_mode="Markdown")
            return
        lines = [f"*Posiciones ({len(positions)})*"]
        for p in positions[:20]:  # cap at 20 to avoid message length limit
            lines.append(
                f"• *{p.ticker}* {p.asset_class} qty={p.quantity} "
                f"MV=${float(p.market_value_usd):,.0f}"
            )
        if len(positions) > 20:
            lines.append(f"_... y {len(positions) - 20} más_")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as exc:
        logger.exception("cmd_positions failed")
        await update.message.reply_text(f"⚠️ Error: {exc}")


@require_auth
async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        snapshot, _ = _get_snapshot_and_mode(context)
        text = (
            f"*PnL*\n"
            f"📅 Diario: *{snapshot.pnl_daily_pct:+.2f}%* "
            f"(${float(snapshot.pnl_daily_usd):+,.0f})\n"
            f"📆 Semanal: *{snapshot.pnl_weekly_pct:+.2f}%*\n"
            f"🗓 Mensual: *{snapshot.pnl_monthly_pct:+.2f}%*"
        )
    except Exception as exc:
        logger.exception("cmd_pnl failed")
        text = f"⚠️ Error: {exc}"
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Service helpers ───────────────────────────────────────────────────────────

def _get_snapshot_and_mode(context: ContextTypes.DEFAULT_TYPE):
    """
    Call the risk service layer directly (no HTTP round-trip).
    Uses the PostgresPool injected by the lifespan via bot_data["pool"],
    ensuring a single shared pool (no singleton divergence with get_pool()).
    """
    from multi_agent.risk import get_current_risk_mode
    from multi_agent.risk.config import load_limits
    from multi_agent.risk.portfolio_snapshot import CachedSnapshotBuilder, SnapshotBuilder

    pool = context.bot_data["pool"]
    builder = CachedSnapshotBuilder(SnapshotBuilder(pool))
    snapshot = builder.get()
    limits = load_limits()
    risk_mode = get_current_risk_mode(snapshot, limits)
    return snapshot, risk_mode


# ── Application factory ───────────────────────────────────────────────────────

def build_application() -> Application:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("pnl", cmd_pnl))
    return app
