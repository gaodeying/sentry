import responses

from sentry.models import Activity
from sentry.notifications.notifications.activity import ResolvedInReleaseActivityNotification
from sentry.types.activity import ActivityType
from sentry.utils.compat import mock

from . import SlackActivityNotificationTest, get_attachment, send_notification


class SlackUnassignedNotificationTest(SlackActivityNotificationTest):
    @responses.activate
    @mock.patch("sentry.notifications.notify.notify", side_effect=send_notification)
    def test_resolved_in_release(self, mock_func):
        """
        Test that a Slack message is sent with the expected payload when an issue is resolved in a release
        """
        notification = ResolvedInReleaseActivityNotification(
            Activity(
                project=self.project,
                group=self.group,
                user=self.user,
                type=ActivityType.SET_RESOLVED_IN_RELEASE,
                data={"version": "meow"},
            )
        )
        with self.tasks():
            notification.send()

        attachment, text = get_attachment()
        release_name = notification.activity.data["version"]
        assert text == f"Issue marked as resolved in {release_name} by {self.name}"
        assert (
            attachment["footer"]
            == f"{self.project.slug} | <http://testserver/settings/account/notifications/workflow/?referrer=ResolvedInReleaseActivitySlackUser|Notification Settings>"
        )
