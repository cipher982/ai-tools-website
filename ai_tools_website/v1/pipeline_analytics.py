"""Pipeline analytics and operational intelligence."""

import statistics
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Dict
from typing import List

from ai_tools_website.v1.pipeline_db import get_pipeline_history

# Define meaningful outcome metrics (not config inputs)
OUTCOME_METRICS = {
    "discovery": {
        "tools_found": "New Tools Found",
        "tools_updated": "Tools Updated",
        "search_queries": "Search Queries",
        "candidates_verified": "Candidates Verified",
        "action_add": "Added",
        "action_update": "Updated",
        "action_skip": "Skipped",
        "action_error": "Errors",
    },
    "maintenance": {
        "tools_recategorized": "Tools Recategorized",
        "categories_changed": "Categories Changed",
        "duplicates_removed": "Duplicates Removed",
        "changes_applied": "Changes Applied",
    },
    "enhancement": {
        "tools_enhanced": "Tools Enhanced",
        "updated": "Successfully Updated",
        "generation_failures": "API Failures",
        "attempted": "Attempted",
        "eligible_tools": "Eligible Tools",
    },
}


def render_sparkline(values: List[float], width: int = 12) -> str:
    """Render ASCII sparkline: ▁▂▃▄▅▆▇"""
    if not values or len(values) < 2:
        return "─" * width

    min_val, max_val = min(values), max(values)
    if min_val == max_val:
        return "▄" * width

    # Map to spark characters (from low to high)
    chars = "▁▂▃▄▅▆▇"
    normalized = [(v - min_val) / (max_val - min_val) for v in values]

    # Slice to requested width
    step = len(normalized) / width if len(normalized) > width else 1
    selected_vals = [normalized[int(i * step)] for i in range(min(width, len(normalized)))]

    return "".join(chars[int(n * (len(chars) - 1))] for n in selected_vals)


def render_progress_bar(percentage: float, width: int = 10) -> str:
    """Render visual progress: ████████░░ 82%"""
    percentage = max(0, min(100, percentage))  # Clamp to 0-100
    filled = int((percentage / 100) * width)
    return "█" * filled + "░" * (width - filled)


def calculate_health_score(pipeline: str, days: int = 7) -> Dict:
    """Calculate pipeline health score and trends."""

    # Get recent pipeline history
    history = get_pipeline_history(pipeline, limit=50)

    if not history:
        return {"score": 0, "status": "unknown", "message": "No execution history"}

    # Filter to recent runs
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent_runs = []

    for run in history:
        try:
            run_time = datetime.fromisoformat(run["started_at"])
            if run_time >= cutoff:
                recent_runs.append(run)
        except ValueError:
            continue

    if not recent_runs:
        return {"score": 50, "status": "stale", "message": f"No runs in last {days} days"}

    # Calculate success rate
    successful = sum(1 for run in recent_runs if run["status"] == "success")
    success_rate = successful / len(recent_runs)

    # Calculate duration trend (recent vs older)
    durations = [run["duration_seconds"] for run in recent_runs if run["duration_seconds"]]
    duration_trend = "stable"

    if len(durations) >= 4:
        recent_avg = statistics.mean(durations[: len(durations) // 2])
        older_avg = statistics.mean(durations[len(durations) // 2 :])

        if recent_avg > older_avg * 1.2:
            duration_trend = "slower"
        elif recent_avg < older_avg * 0.8:
            duration_trend = "faster"

    # Calculate overall health score (0-100)
    score = int(success_rate * 100)

    # Determine status and message
    if score >= 95:
        status = "excellent"
        message = f"{successful}/{len(recent_runs)} successful"
    elif score >= 80:
        status = "healthy"
        message = f"{successful}/{len(recent_runs)} successful"
    elif score >= 50:
        status = "degraded"
        message = f"Low success rate: {successful}/{len(recent_runs)}"
    else:
        status = "critical"
        message = f"High failure rate: {successful}/{len(recent_runs)}"

    return {
        "score": score,
        "status": status,
        "message": message,
        "success_rate": success_rate,
        "total_runs": len(recent_runs),
        "successful_runs": successful,
        "duration_trend": duration_trend,
        "durations": durations[-10:],  # Last 10 for sparkline
        "days_analyzed": days,
    }


def filter_outcome_metrics(pipeline: str, raw_metrics: Dict) -> Dict:
    """Filter metrics to show only meaningful outcomes, not config inputs."""

    allowed_metrics = OUTCOME_METRICS.get(pipeline, {})
    if not allowed_metrics:
        return raw_metrics

    # Filter and rename metrics
    filtered = {}
    for key, value in raw_metrics.items():
        if key in allowed_metrics:
            display_name = allowed_metrics[key]
            filtered[display_name] = value

    return filtered


def generate_insights(pipeline: str, health_data: Dict) -> List[str]:
    """Generate actionable operational insights."""
    insights = []

    success_rate = health_data.get("success_rate", 1.0)
    status = health_data.get("status", "unknown")
    duration_trend = health_data.get("duration_trend", "stable")

    # Success rate insights
    if success_rate < 0.1:
        insights.append("🚨 All runs failing - investigate immediately")
    elif success_rate < 0.5:
        insights.append("🔥 High failure rate - check configuration")
    elif success_rate < 0.8:
        insights.append("⚠️ Some failures - monitor closely")

    # Performance insights
    if duration_trend == "slower":
        insights.append("⏱️ Performance degrading - check resource usage")
    elif duration_trend == "faster":
        insights.append("⚡ Performance improving")

    # Pipeline-specific insights
    if pipeline == "enhancement" and success_rate < 0.5:
        insights.append("🤖 API errors detected - verify model configuration")

    if pipeline == "discovery" and success_rate < 0.8:
        insights.append("🔍 Search issues - check API quotas and network")

    # No news is good news
    if not insights and status in ["excellent", "healthy"]:
        insights.append("✅ Operating normally")

    return insights


def get_contextual_summary(pipeline: str, days: int = 1) -> str:
    """Get contextual time-based summary."""

    history = get_pipeline_history(pipeline, limit=100)
    if not history:
        return "No execution history"

    # Filter to timeframe
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []

    for run in history:
        try:
            run_time = datetime.fromisoformat(run["started_at"])
            if run_time >= cutoff:
                recent.append(run)
        except ValueError:
            continue

    if not recent:
        return f"No runs in last {days}{'d' if days > 1 else '24h'}"

    successful = sum(1 for run in recent if run["status"] == "success")

    timeframe = f"last {days}d" if days > 1 else "last 24h"

    if successful == len(recent):
        return f"{timeframe}: {len(recent)} runs, all successful"
    elif successful == 0:
        return f"{timeframe}: {len(recent)} runs, all failed"
    else:
        return f"{timeframe}: {successful}/{len(recent)} successful"


def calculate_trend_arrow(current: float, previous: float, threshold: float = 0.1) -> str:
    """Calculate trend arrow based on percentage change."""
    if previous == 0:
        return ""

    change = (current - previous) / previous

    if abs(change) < threshold:
        return ""  # No significant change
    elif change > 0:
        return "↗"  # Improving
    else:
        return "↘"  # Degrading
