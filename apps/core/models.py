from django.db import models

class TimeStamped(models.Model):
    """
    Abstract base model that provides self-updating
    created_at and updated_at timestamp fields.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
