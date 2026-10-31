from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.billing'

    def ready(self):
        # 1. Attach for_user to Invoice.objects and QuerySets
        from django.db import models

        def for_user(self, user):
            if not user or not user.is_authenticated:
                return self.none()
            if user.is_superuser or getattr(user, 'role', None) in ('admin', 'staff'):
                return self.all()
            if getattr(user, 'role', None) == 'customer':
                return self.filter(customer__user=user)
            return self.none()

        models.QuerySet.for_user = for_user
        models.Manager.for_user = for_user

        # 2. Wire billing urls into config.urls if not already included
        try:
            import config.urls
            from django.urls import path, include

            if not any(getattr(p, 'urlconf_name', None) == 'apps.billing.urls' for p in config.urls.urlpatterns):
                config.urls.urlpatterns.append(path('', include('apps.billing.urls')))
        except Exception:
            pass
