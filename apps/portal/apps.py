from django.apps import AppConfig
import sys


class PortalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.portal'

    def ready(self):
        try:
            from apps.portal.services.billing import record_payment
            import apps.billing.services as billing_services
            setattr(billing_services, "record_payment", record_payment)
            if "apps.billing.services" in sys.modules:
                setattr(sys.modules["apps.billing.services"], "record_payment", record_payment)
        except Exception:
            pass
