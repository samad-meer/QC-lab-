from django.contrib.auth.backends import ModelBackend

from .passwords import is_locked


class LockoutBackend(ModelBackend):
    """
    Sits under the sign-in page and the admin site alike, so neither is a way round
    a lockout or a blocked account. Django asks it on every request as well, so
    blocking someone ends a session they already have.
    """

    def user_can_authenticate(self, user):
        return user.may_sign_in() and not is_locked(user)
