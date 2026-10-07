"""Admin registrations for the core application."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class UserAdmin(UserAdmin):
    """Admin for the custom user, exposing only the V1 account-type field."""

    list_display = ("username", "email", "account_type", "is_staff", "is_active")
    list_filter = ("account_type", "is_staff", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("V1 Account Type", {"fields": ("account_type",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("V1 Account Type", {"fields": ("account_type",)}),
    )