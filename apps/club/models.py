from django.contrib.auth.models import AbstractUser
from django.db import models


class Member(AbstractUser):
    discord_id = models.CharField(max_length=32, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=100, blank=True)

    def __str__(self) -> str:
        return self.display_name or self.username


class Week(models.Model):
    class MatchStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        MATCHED = "matched", "Matched"
        UNMATCHED = "unmatched", "Unmatched"
        ERROR = "error", "Error"

    title = models.CharField(max_length=255)
    selected_by = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="weeks")
    movie = models.ForeignKey(
        "movies.Movie",
        on_delete=models.PROTECT,
        related_name="weeks",
        null=True,
        blank=True,
    )
    match_status = models.CharField(
        max_length=16,
        choices=MatchStatus.choices,
        default=MatchStatus.PENDING,
    )
    match_error = models.TextField(blank=True, default="")
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        if not self.created_at:
            return self.title
        return f"{self.title} ({self.created_at:%Y-%m-%d})"
