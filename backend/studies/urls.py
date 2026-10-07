"""URL configuration for the studies application."""
from django.urls import path

from . import views

app_name = "studies"

urlpatterns = [
    path("api/studies/", views.study_list, name="study-list"),
]