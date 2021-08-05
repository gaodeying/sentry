from django.db import models
from django.utils import timezone

from sentry.db.models import FlexibleForeignKey, Model, sane_repr


class GroupRegression(Model):
    """
    Describes when a group was marked as a regression.
    """

    __include_in_export__ = False

    group = FlexibleForeignKey("sentry.Group", unique=True)
    # the release in which this regressed in
    release = FlexibleForeignKey("sentry.Release")
    datetime = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "sentry_groupregression"
        app_label = "sentry"

    __repr__ = sane_repr("group_id", "release_id")