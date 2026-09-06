"""Acknowledge before doing work; an expired click must never mutate raid state."""
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("guildloot.interactions")


async def acknowledge_interaction(interaction, **options):
    started = time.monotonic()
    age_ms = max(0, (datetime.now(timezone.utc) - interaction.created_at).total_seconds() * 1000)
    if interaction.response.is_done():
        return False
    try:
        await interaction.response.defer(**options)
    except Exception as error:
        # Do not retry a dead token, send a followup, or carry out the action.
        # The persistent post remains usable by a fresh click.
        code = getattr(error, "code", None)
        if code not in (10062, 40060):
            raise
        logger.warning(
            "Interaction rejected code=%s interaction=%s message=%s action=%s "
            "age_before_ack_ms=%.0f ack_duration_ms=%.0f",
            code, interaction.id, getattr(interaction.message, "id", None),
            (interaction.data or {}).get("custom_id", "command"), age_ms,
            (time.monotonic() - started) * 1000,
        )
        return False
    elapsed_ms = (time.monotonic() - started) * 1000
    if age_ms + elapsed_ms >= 1500:
        logger.warning("Slow interaction acknowledgement interaction=%s age_before_ack_ms=%.0f ack_duration_ms=%.0f",
                       interaction.id, age_ms, elapsed_ms)
    return True
