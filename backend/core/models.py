"""
Core application models.

Authentication V1 defines exactly two account types used for Phase 2:
    * common staff account
    * separate administrator account

Individual user accountability (per-doctor, per-nurse, RBAC, permission
matrices) is deferred to V2 and is intentionally NOT modelled here.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class AccountType(models.TextChoices):
    STAFF = "staff", "Staff"
    ADMINISTRATOR = "administrator", "Administrator"


class User(AbstractUser):
    """The application user, distinguishing the two V1 account types."""

    account_type = models.CharField(
        max_length=16,
        choices=AccountType.choices,
        default=AccountType.STAFF,
        help_text=(
            "Authentication V1: identifies a common staff account versus the "
            "separate administrator account."
        ),
    )

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"