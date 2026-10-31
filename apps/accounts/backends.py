from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

class CaseInsensitiveModelBackend(ModelBackend):
    """
    Authenticates against settings.AUTH_USER_MODEL with case-insensitive email.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or not password:
            return None
        try:
            user = UserModel.objects.get(email__iexact=username)
        except (UserModel.DoesNotExist, UserModel.MultipleObjectsReturned):
            # Run default password hasher once to mitigate timing attacks
            UserModel().set_password(password)
            return None
        else:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        return None
