from django.contrib import admin
from django.urls import path

from apps.club import views
from apps.club.api import create_week, health

urlpatterns = [
    path("", views.home, name="home"),
    path("archive/", views.archive, name="archive"),
    path("movies/<int:tmdb_id>/", views.movie_detail, name="movie-detail"),
    path("picks/<int:week_id>/", views.week_detail, name="week-detail"),
    path("tmdb/update/", views.update_tmdb, name="update-tmdb"),
    path("stats/", views.stats, name="stats"),
    path("about/", views.about, name="about"),
    path("admin/", admin.site.urls),
    path("api/weeks/", create_week, name="create-week"),
    path("health/", health, name="health"),
]
