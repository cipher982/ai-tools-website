"""Cron schedule utilities."""

import logging
from datetime import datetime
from datetime import timezone
from typing import Dict
from typing import Optional

from croniter import croniter

logger = logging.getLogger(__name__)


def calculate_next_run(cron_expression: str) -> Optional[Dict[str, str]]:
    """Calculate next run time from cron expression."""
    try:
        now = datetime.now(timezone.utc)
        cron = croniter(cron_expression, now)
        next_run = cron.get_next(datetime)

        # Calculate time until next run
        time_until = next_run - now
        days = time_until.days
        hours, remainder = divmod(time_until.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            time_until_str = f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            time_until_str = f"{hours}h {minutes}m"
        else:
            time_until_str = f"{minutes}m"

        return {"next_run": next_run.isoformat(), "next_run_in": time_until_str}
    except Exception as e:
        logger.warning(f"Failed to calculate next run for cron '{cron_expression}': {e}")
        return None


def get_cron_schedules() -> Dict[str, str]:
    """Get cron schedules for each pipeline."""
    # These should match the actual crontab entries
    return {
        "discovery": "0 2 * * *",  # Daily at 2 AM UTC
        "enhancement": "0 3 * * 1",  # Weekly on Monday at 3 AM UTC
    }
