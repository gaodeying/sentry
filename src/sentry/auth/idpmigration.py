from uuid import uuid4

from sentry import options
from sentry.models import Organization, OrganizationMember, User
from sentry.utils import redis
from sentry.utils.email import MessageBuilder

# from django.urls.base import reverse


# from sentry.utils.http import absolute_uri


def send_confirm_email(user, email, verification_key):
    context = {
        "user": user,
        # left incase we want to have a clickable verification link
        # "url": absolute_uri(
        #     reverse("sentry-account-confirm-email", args=[user.id, verification_key])
        # ),
        "confirm_email": email,
        "verification_key": verification_key,
    }
    msg = MessageBuilder(
        subject="{}Confirm Email".format(options.get("mail.subject-prefix")),
        template="sentry/emails/idp_verification_email.txt",
        html_template="sentry/emails/idp_verification_email.html",
        type="user.confirm_email",
        context=context,
    )
    msg.send_async([email])


def create_verification_key(user: User, org: Organization, email: str) -> None:
    """Store and email a verification key for IdP migration.

    Create a one-time verification key for a user whose SSO identity
    has been deleted, presumably because the parent organization has
    switched identity providers. Store the key in Redis and send it
    in an email to the associated address.

    :param user: the user profile to link
    :param org: the organization whose SSO provider is being used
    :param email: the email address associated with the SSO identity
    """
    redis_key = "verificationKeyStorage"
    TTL = 60 * 10
    cluster = redis.clusters.get("default").get_local_client_for_key(redis_key)
    member_id = OrganizationMember.objects.get(organization=org, user=user).id

    verification_key = f"auth:one-time-key:{uuid4().hex}"
    verification_value = {"user_id": user.id, "email": email, "member_id": member_id}

    cluster.hmset(verification_key, verification_value)
    cluster.expire(verification_key, TTL)

    send_confirm_email(user, email, verification_key)


def verify_new_identity(user: User, org: Organization, key: str) -> bool:
    """Verify a key to migrate a user to a new IdP.

    If the provided one-time key is valid, create a new auth identity
    linking the user to the organization's SSO provider.

    :param user: the user profile to link
    :param org: the organization whose SSO provider is being used
    :param key: the one-time verification key
    :return: whether the key is valid
    """
    # user cluster.hgetall(key) to get from redis
    raise NotImplementedError  # TODO