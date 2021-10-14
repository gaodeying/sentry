# Generated by Django 2.2.24 on 2021-09-24 19:23

import logging

from django.db import migrations

from sentry.snuba.models import QueryDatasets, SnubaQueryEventType
from sentry.snuba.tasks import _create_in_snuba, _delete_from_snuba
from sentry.utils.query import RangeQuerySetWrapperWithProgressBar


def migrate_subscriptions(apps, schema_editor):
    QuerySubscription = apps.get_model("sentry", "QuerySubscription")
    AppSnubaQueryEventType = apps.get_model("sentry", "SnubaQueryEventType")

    for subscription in RangeQuerySetWrapperWithProgressBar(
        QuerySubscription.objects.select_related("snuba_query").all()
    ):
        if subscription.subscription_id is not None:
            # The migration apps don't build this property, so manually set it.
            raw_event_types = AppSnubaQueryEventType.objects.filter(
                snuba_query=subscription.snuba_query
            ).all()
            event_types = [SnubaQueryEventType.EventType(ev.type) for ev in raw_event_types]
            setattr(subscription.snuba_query, "event_types", event_types)

            subscription_id = None
            try:
                subscription_id = _create_in_snuba(subscription)
            except Exception as e:
                logging.exception(f"failed to recreate {subscription.subscription_id}: {e}")
                continue

            try:
                _delete_from_snuba(
                    QueryDatasets(subscription.snuba_query.dataset),
                    subscription.subscription_id,
                )
            except Exception as e:
                try:
                    # Delete the subscription we just created to avoid orphans
                    _delete_from_snuba(
                        QueryDatasets(subscription.snuba_query.dataset),
                        subscription_id,
                    )
                except Exception as oe:
                    logging.exception(f"failed to delete orphan {subscription_id}: {oe}")

                logging.exception(f"failed to delete {subscription.subscription_id}: {e}")
                continue

            QuerySubscription.objects.filter(id=subscription.id).update(
                subscription_id=subscription_id
            )


class Migration(migrations.Migration):
    # This flag is used to mark that a migration shouldn't be automatically run in
    # production. We set this to True for operations that we think are risky and want
    # someone from ops to run manually and monitor.
    # General advice is that if in doubt, mark your migration as `is_dangerous`.
    # Some things you should always mark as dangerous:
    # - Large data migrations. Typically we want these to be run manually by ops so that
    #   they can be monitored. Since data migrations will now hold a transaction open
    #   this is even more important.
    # - Adding columns to highly active tables, even ones that are NULL.
    is_dangerous = True

    # This flag is used to decide whether to run this migration in a transaction or not.
    # By default we prefer to run in a transaction, but for migrations where you want
    # to `CREATE INDEX CONCURRENTLY` this needs to be set to False. Typically you'll
    # want to create an index concurrently when adding one to an existing table.
    # You'll also usually want to set this to `False` if you're writing a data
    # migration, since we don't want the entire migration to run in one long-running
    # transaction.
    atomic = False

    dependencies = [
        ("sentry", "0232_backfill_missed_semver_releases"),
    ]

    operations = [
        migrations.RunPython(
            migrate_subscriptions,
            migrations.RunPython.noop,
            hints={"tables": ["sentry_querysubscription", "sentry_snubaqueryeventtype"]},
        ),
    ]
