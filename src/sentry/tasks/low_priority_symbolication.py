"""
Tasks that automate the job of moving projects in and out of symbolicator's low priority queue based
on symbolication metrics stored in Redis.

This has three major tasks, executed in the following general order:
1. Scan for new suspect projects in Redis that need to be checked for LPQ eligibility. Triggers 2 and 3.
2. Determine a project's eligibility for the LPQ based on their recorded metrics.
3. Remove some specified project from the LPQ.
"""

import logging
import time

from sentry.processing import realtime_metrics
from sentry.processing.realtime_metrics.base import DurationsHistogram
from sentry.tasks.base import instrumented_task
from sentry.utils import sdk as sentry_sdk

logger = logging.getLogger(__name__)


@instrumented_task(  # type: ignore
    name="sentry.tasks.low_priority_symbolication.scan_for_suspect_projects",
    queue="symbolications.compute_low_priority_projects",
    ignore_result=True,
    soft_time_limit=10,
)
def scan_for_suspect_projects() -> None:
    """Scans and updates the list of projects assigned to the low priority queue."""
    _scan_for_suspect_projects()


def _scan_for_suspect_projects() -> None:
    suspect_projects = set()
    now = int(time.time())

    for project_id in realtime_metrics.projects():
        suspect_projects.add(project_id)
        update_lpq_eligibility.delay(project_id=project_id, cutoff=now)

    # Prune projects we definitely know shouldn't be in the queue any more.
    # `update_lpq_eligibility` should handle removing suspect projects from the list if it turns
    # out they need to be evicted.
    current_lpq_projects = realtime_metrics.get_lpq_projects() or set()
    expired_projects = current_lpq_projects.difference(suspect_projects)
    if not expired_projects:
        return

    realtime_metrics.remove_projects_from_lpq(expired_projects)

    for project_id in expired_projects:
        # TODO: add metrics!
        logger.warning("Moved project out of symbolicator's low priority queue: %s", project_id)


@instrumented_task(  # type: ignore
    name="sentry.tasks.low_priority_symbolication.update_lpq_eligibility",
    queue="symbolications.compute_low_priority_projects",
    ignore_result=True,
    soft_time_limit=10,
)
def update_lpq_eligibility(project_id: int, cutoff: int) -> None:
    """
    Given a project ID, determines whether the project belongs in the low priority queue and
    removes or assigns it accordingly to the low priority queue.

    `cutoff` is a posix timestamp that specifies an end time for the historical data this method
    should consider when calculating a project's eligibility. In other words, only data recorded
    before `cutoff` should be considered.
    """
    _update_lpq_eligibility(project_id, cutoff)


def _update_lpq_eligibility(project_id: int, cutoff: int) -> None:
    # TODO: It may be a good idea to figure out how to debounce especially if this is
    # executing more than 10s after cutoff.
    excessive_rate = excessive_event_rate(project_id, cutoff)
    excessive_duration = excessive_event_duration(project_id, cutoff)

    if excessive_rate or excessive_duration:
        was_added = realtime_metrics.add_project_to_lpq(project_id)
        if was_added:
            if excessive_rate:
                reason = "excessive event rate"
            else:
                reason = "excessive event duration"
            sentry_sdk.capture_message(
                f"Moved project {project_id} to symbolicator's LPQ: {reason}"
            )
    else:
        was_removed = realtime_metrics.remove_projects_from_lpq({project_id})
        if was_removed:
            logger.warning("Moved project %s out of symbolicator's LPQ", project_id)


def excessive_event_rate(project_id: int, cutoff: int) -> bool:
    """Whether the project is sending too many symbolication requests."""
    recent_time_window = 60

    buckets = realtime_metrics.get_counts_for_project(project_id, cutoff)

    total_rate = buckets.total_count() / buckets.total_time()

    recent_bucket_count = int(recent_time_window / buckets.width)
    recent_rate = sum(buckets.counts[-recent_bucket_count:]) / recent_time_window

    if recent_rate > 50 and recent_rate > 5 * total_rate:
        return True
    else:
        return False


def excessive_event_duration(project_id: int, cutoff: int) -> bool:
    """Whether the project's symbolication requests are taking too long to process."""

    buckets = realtime_metrics.get_durations_for_project(project_id, cutoff)

    total_histogram = DurationsHistogram(bucket_size=buckets.histograms[0].bucket_size)
    for histogram in buckets.histograms:
        total_histogram.incr_from(histogram)

    try:
        p75_duration = total_histogram.percentile(0.75)
    except ValueError:
        return False
    events_per_minute = total_histogram.total_count() / (buckets.width / 60)

    if events_per_minute > 15 and p75_duration > 6 * 60:
        return True
    else:
        return False
