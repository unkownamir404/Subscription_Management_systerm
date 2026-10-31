from functools import wraps
from django.core.exceptions import PermissionDenied
from django.contrib.auth.mixins import AccessMixin

def is_admin(user):
    return user.is_authenticated and (user.role == "admin" or user.is_superuser)

def is_staff_or_admin(user):
    return user.is_authenticated and (user.role in ("staff", "admin") or user.is_staff or user.is_superuser)

class RoleRequiredMixin(AccessMixin):
    """
    Verify that the current user is authenticated and has one of the allowed roles.
    If not authenticated, redirects to login.
    If authenticated but role not allowed, raises PermissionDenied (403).
    """
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        user_role = getattr(request.user, "role", None)
        # Superusers or users matching allowed_roles
        if request.user.is_superuser or user_role in self.allowed_roles:
            return super().dispatch(request, *args, **kwargs)

        raise PermissionDenied("You do not have permission to access this resource.")


def role_required(allowed_roles):
    """
    Decorator for views that checks whether a user has a particular role,
    raising 403 if they do not.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())
            user_role = getattr(request.user, "role", None)
            if request.user.is_superuser or user_role in allowed_roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("You do not have permission to access this resource.")
        return _wrapped_view
    return decorator
