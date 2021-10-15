import logging
import random
from time import sleep, time

import sentry_sdk
from django.conf import settings

from sentry import options
from sentry.eventstore.processing import event_processing_store
from sentry.killswitches import killswitch_matches_context
from sentry.processing import realtime_metrics
from sentry.tasks.base import instrumented_task
from sentry.tasks.store import do_process_event, process_event, process_event_from_reprocessing
from sentry.utils import metrics
from sentry.utils.canonical import CANONICAL_TYPES, CanonicalKeyDict
from sentry.utils.sdk import set_current_event_project

error_logger = logging.getLogger("sentry.errors.events")
info_logger = logging.getLogger("sentry.symbolication")

# Is reprocessing on or off by default?
REPROCESSING_DEFAULT = False

SYMBOLICATOR_MAX_RETRY_AFTER = settings.SYMBOLICATOR_MAX_RETRY_AFTER

# The maximum number of times an event will be moved between the normal
# and low priority queues
SYMBOLICATOR_MAX_QUEUE_SWITCHES = 3


class RetrySymbolication(Exception):
    def __init__(self, retry_after=None):
        self.retry_after = retry_after


def should_demote_symbolication(project_id: int) -> bool:
    """
    Determines whether a project's symbolication events should be pushed to the low priority queue.

    The decision is made based on three factors, in order:
        1. is the store.symbolicate-event-lpq-never killswitch set for the project? -> normal queue
        2. is the store.symbolicate-event-lpq-always killswitch set for the project? -> low priority queue
        3. has the project been selected for the lpq according to realtime_metrics? -> low priority queue

    Note that 3 is gated behind the config setting SENTRY_ENABLE_AUTO_LOW_PRIORITY_QUEUE.
    """
    always_lowpri = killswitch_matches_context(
        "store.symbolicate-event-lpq-always",
        {
            "project_id": project_id,
        },
    )
    never_lowpri = killswitch_matches_context(
        "store.symbolicate-event-lpq-never",
        {
            "project_id": project_id,
        },
    )

    if never_lowpri:
        return False
    elif always_lowpri:
        return True
    else:
        return settings.SENTRY_ENABLE_AUTO_LOW_PRIORITY_QUEUE and realtime_metrics.is_lpq_project(
            project_id
        )


def submit_symbolicate(
    is_low_priority, from_reprocessing, cache_key, event_id, start_time, data, queue_switches=0
):
    if is_low_priority:
        task = (
            symbolicate_event_from_reprocessing_low_priority
            if from_reprocessing
            else symbolicate_event_low_priority
        )
    else:
        task = symbolicate_event_from_reprocessing if from_reprocessing else symbolicate_event

    task.delay(
        cache_key=cache_key,
        start_time=start_time,
        event_id=event_id,
        data=data,
        queue_switches=queue_switches,
    )


def _do_symbolicate_event(
    cache_key, start_time, event_id, symbolicate_task, data=None, queue_switches=0
):
    from sentry.lang.native.processing import get_symbolication_function

    if data is None:
        data = event_processing_store.get(cache_key)

    if data is None:
        metrics.incr(
            "events.failed", tags={"reason": "cache", "stage": "symbolicate"}, skip_internal=False
        )
        error_logger.error("symbolicate.failed.empty", extra={"cache_key": cache_key})
        return

    data = CanonicalKeyDict(data)

    project_id = data["project"]
    set_current_event_project(project_id)

    event_id = data["event_id"]

    from_reprocessing = (
        symbolicate_task is symbolicate_event_from_reprocessing
        or symbolicate_task is symbolicate_event_from_reprocessing_low_priority
    )

    # check whether the event is in the wrong queue and if so, move it to the other one.
    # we do this at most SYMBOLICATOR_MAX_QUEUE_SWITCHES times.
    if queue_switches >= SYMBOLICATOR_MAX_QUEUE_SWITCHES:
        metrics.incr(
            "tasks.symbolication.symbolicate_event.low_priority.max_queue_switches", sample_rate=1
        )
    else:
        is_low_priority = symbolicate_task in [
            symbolicate_event_low_priority,
            symbolicate_event_from_reprocessing_low_priority,
        ]
        should_be_low_priority = should_demote_symbolication(project_id)

        if is_low_priority != should_be_low_priority:
            metrics.incr(
                "tasks.symbolication.symbolicate_event.low_priority.wrong_queue", sample_rate=1
            )
            submit_symbolicate(
                should_be_low_priority,
                from_reprocessing,
                cache_key,
                event_id,
                start_time,
                data,
                queue_switches + 1,
            )
            return

    def _continue_to_process_event():
        process_task = process_event_from_reprocessing if from_reprocessing else process_event
        do_process_event(
            cache_key=cache_key,
            start_time=start_time,
            event_id=event_id,
            process_task=process_task,
            data=data,
            data_has_changed=has_changed,
            from_symbolicate=True,
        )

    symbolication_function = get_symbolication_function(data)
    symbolication_function_name = getattr(symbolication_function, "__name__", "none")

    if killswitch_matches_context(
        "store.load-shed-symbolicate-event-projects",
        {
            "project_id": project_id,
            "event_id": event_id,
            "platform": data.get("platform") or "null",
            "symbolication_function": symbolication_function_name,
        },
    ):
        return _continue_to_process_event()

    has_changed = False

    symbolication_start_time = time()

    submission_ratio = options.get("symbolicate-event.low-priority.metrics.submission-rate")
    submit_realtime_metrics = not from_reprocessing and random.random() < submission_ratio
    timestamp = int(symbolication_start_time)

    if submit_realtime_metrics:
        with sentry_sdk.start_span(
            op="tasks.symbolication.symbolicate_event.low_priority.metrics.counter"
        ):
            try:
                realtime_metrics.increment_project_event_counter(project_id, timestamp)
            except Exception as e:
                sentry_sdk.capture_exception(e)

    with sentry_sdk.start_span(op="tasks.symbolication.symbolicate_event.symbolication") as span:
        span.set_data("symbolication_function", symbolication_function_name)
        with metrics.timer(
            "tasks.symbolication.symbolicate_event.symbolication",
            tags={"symbolication_function": symbolication_function_name},
        ):
            while True:
                try:
                    with sentry_sdk.start_span(
                        op="tasks.symbolication.symbolicate_event.%s" % symbolication_function_name
                    ) as span:
                        symbolicated_data = symbolication_function(data)
                        span.set_data("symbolicated_data", bool(symbolicated_data))

                    if symbolicated_data:
                        data = symbolicated_data
                        has_changed = True

                    break
                except RetrySymbolication as e:
                    if (
                        time() - symbolication_start_time
                    ) > settings.SYMBOLICATOR_PROCESS_EVENT_WARN_TIMEOUT:
                        error_logger.warning(
                            "symbolicate.slow",
                            extra={"project_id": project_id, "event_id": event_id},
                        )
                    if (
                        time() - symbolication_start_time
                    ) > settings.SYMBOLICATOR_PROCESS_EVENT_HARD_TIMEOUT:
                        # Do not drop event but actually continue with rest of pipeline
                        # (persisting unsymbolicated event)
                        metrics.incr(
                            "tasks.symbolication.symbolicate_event.fatal",
                            tags={
                                "reason": "timeout",
                                "symbolication_function": symbolication_function_name,
                            },
                        )
                        error_logger.exception(
                            "symbolicate.failed.infinite_retry",
                            extra={"project_id": project_id, "event_id": event_id},
                        )
                        data.setdefault("_metrics", {})["flag.processing.error"] = True
                        data.setdefault("_metrics", {})["flag.processing.fatal"] = True
                        has_changed = True
                        break
                    else:
                        # sleep for `retry_after` but max 5 seconds and try again
                        metrics.incr(
                            "tasks.symbolication.symbolicate_event.retry",
                            tags={"symbolication_function": symbolication_function_name},
                        )
                        sleep(min(e.retry_after, SYMBOLICATOR_MAX_RETRY_AFTER))
                        continue
                except Exception:
                    metrics.incr(
                        "tasks.symbolication.symbolicate_event.fatal",
                        tags={
                            "reason": "error",
                            "symbolication_function": symbolication_function_name,
                        },
                    )
                    error_logger.exception("tasks.symbolication.symbolicate_event.symbolication")
                    data.setdefault("_metrics", {})["flag.processing.error"] = True
                    data.setdefault("_metrics", {})["flag.processing.fatal"] = True
                    has_changed = True
                    break

    if submit_realtime_metrics:
        with sentry_sdk.start_span(
            op="tasks.symbolication.symbolicate_event.low_priority.metrics.histogram"
        ):
            symbolication_duration = int(time() - symbolication_start_time)
            try:
                realtime_metrics.increment_project_duration_counter(
                    project_id, timestamp, symbolication_duration
                )
            except Exception as e:
                sentry_sdk.capture_exception(e)

    # We cannot persist canonical types in the cache, so we need to
    # downgrade this.
    if isinstance(data, CANONICAL_TYPES):
        data = dict(data.items())

    if has_changed:
        cache_key = event_processing_store.store(data)

    return _continue_to_process_event()


@instrumented_task(
    name="sentry.tasks.symbolication.symbolicate_event",
    queue="events.symbolicate_event",
    time_limit=settings.SYMBOLICATOR_PROCESS_EVENT_HARD_TIMEOUT + 30,
    soft_time_limit=settings.SYMBOLICATOR_PROCESS_EVENT_HARD_TIMEOUT + 20,
    acks_late=True,
)
def symbolicate_event(
    cache_key, start_time=None, event_id=None, data=None, queue_switches=0, **kwargs
):
    """
    Handles event symbolication using the external service: symbolicator.

    :param string cache_key: the cache key for the event data
    :param int start_time: the timestamp when the event was ingested
    :param string event_id: the event identifier
    """
    return _do_symbolicate_event(
        cache_key=cache_key,
        start_time=start_time,
        event_id=event_id,
        symbolicate_task=symbolicate_event,
        data=data,
        queue_switches=queue_switches,
    )


@instrumented_task(
    name="sentry.tasks.symbolication.symbolicate_event_low_priority",
    queue="events.symbolicate_event_low_priority",
    time_limit=settings.SYMBOLICATOR_PROCESS_EVENT_HARD_TIMEOUT + 30,
    soft_time_limit=settings.SYMBOLICATOR_PROCESS_EVENT_HARD_TIMEOUT + 20,
    acks_late=True,
)
def symbolicate_event_low_priority(
    cache_key, start_time=None, event_id=None, data=None, queue_switches=0, **kwargs
):
    """
    Handles event symbolication using the external service: symbolicator.

    This puts the task on the low priority queue. Projects whose symbolication
    events misbehave get sent there to protect the main queue.

    :param string cache_key: the cache key for the event data
    :param int start_time: the timestamp when the event was ingested
    :param string event_id: the event identifier
    """
    return _do_symbolicate_event(
        cache_key=cache_key,
        start_time=start_time,
        event_id=event_id,
        symbolicate_task=symbolicate_event_low_priority,
        data=data,
        queue_switches=queue_switches,
    )


@instrumented_task(
    name="sentry.tasks.symbolication.symbolicate_event_from_reprocessing",
    queue="events.reprocessing.symbolicate_event",
    time_limit=settings.SYMBOLICATOR_PROCESS_EVENT_HARD_TIMEOUT + 30,
    soft_time_limit=settings.SYMBOLICATOR_PROCESS_EVENT_HARD_TIMEOUT + 20,
    acks_late=True,
)
def symbolicate_event_from_reprocessing(
    cache_key, start_time=None, event_id=None, data=None, queue_switches=0, **kwargs
):
    return _do_symbolicate_event(
        cache_key=cache_key,
        start_time=start_time,
        event_id=event_id,
        symbolicate_task=symbolicate_event_from_reprocessing,
        data=data,
        queue_switches=queue_switches,
    )


@instrumented_task(
    name="sentry.tasks.symbolication.symbolicate_event_from_reprocessing_low_priority",
    queue="events.reprocessing.symbolicate_event_low_priority",
    time_limit=settings.SYMBOLICATOR_PROCESS_EVENT_HARD_TIMEOUT + 30,
    soft_time_limit=settings.SYMBOLICATOR_PROCESS_EVENT_HARD_TIMEOUT + 20,
    acks_late=True,
)
def symbolicate_event_from_reprocessing_low_priority(
    cache_key, start_time=None, event_id=None, data=None, queue_switches=0, **kwargs
):
    return _do_symbolicate_event(
        cache_key=cache_key,
        start_time=start_time,
        event_id=event_id,
        symbolicate_task=symbolicate_event_from_reprocessing_low_priority,
        data=data,
        queue_switches=queue_switches,
    )