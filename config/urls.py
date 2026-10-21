from django.contrib import admin
from django.urls import path

from apps.club.api import create_week, health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/weeks/", create_week, name="create-week"),
    path("health/", health, name="health"),
]
