from django.db import models


class Genre(models.Model):
    tmdb_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Movie(models.Model):
    tmdb_id = models.PositiveIntegerField(unique=True)
    title = models.CharField(max_length=255)
    release_date = models.DateField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(blank=True, default="")
    genres = models.ManyToManyField(Genre, related_name="movies", blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return f"{self.title} ({self.tmdb_id})"

    def save(self, *args, **kwargs):
        old_tmdb_id = None
        if self.pk:
            old_tmdb_id = (
                type(self).objects.filter(pk=self.pk)
                .values_list("tmdb_id", flat=True)
                .first()
            )

        super().save(*args, **kwargs)

        if kwargs.get("raw"):
            return

        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "tmdb_id" not in update_fields:
            return

        if self.tmdb_id and self.tmdb_id != old_tmdb_id:
            # Imported here to avoid a circular import at module load time.
            from .sync import sync_movie_metadata

            sync_movie_metadata(self)
