import mimetypes
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify

from .utils import make_image_thumbnail
from .validators import get_extension, validate_media_file, validate_thumbnail


class MediaType(models.TextChoices):
    IMAGE = "image", "Image"
    VIDEO = "video", "Video"
    AUDIO = "audio", "Audio"


class Visibility(models.TextChoices):
    PUBLIC = "public", "Public"
    PRIVATE = "private", "Private"


_TYPE_FOLDERS = {"image": "images", "video": "videos", "audio": "audio"}


def media_upload_path(instance, filename):
    """Random, collision-free storage path. The user's filename is discarded."""
    folder = _TYPE_FOLDERS.get(instance.media_type, "other")
    return f"{folder}/{uuid.uuid4().hex}{get_extension(filename)}"


def thumbnail_upload_path(instance, filename):
    return f"thumbnails/{uuid.uuid4().hex}{get_extension(filename)}"


def _unique_slug(model, value, max_length, instance_pk=None, fallback="item"):
    base = slugify(value)[: max_length - 9].strip("-") or fallback
    slug = base
    queryset = model.objects.all()
    if instance_pk:
        queryset = queryset.exclude(pk=instance_pk)
    while queryset.filter(slug=slug).exists():
        slug = f"{base}-{uuid.uuid4().hex[:6]}"
    return slug


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(Category, self.name, 120, self.pk, "category")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("media_library:category_detail", kwargs={"slug": self.slug})


class MediaQuerySet(models.QuerySet):
    def public(self):
        """Active, public media: the only media anonymous visitors may see."""
        return self.filter(visibility=Visibility.PUBLIC, is_active=True)

    def visible_to(self, user):
        """Media the given user is allowed to view."""
        if user.is_authenticated and user.is_staff:
            return self
        condition = Q(visibility=Visibility.PUBLIC, is_active=True)
        if user.is_authenticated:
            condition |= Q(uploader=user, is_active=True)
        return self.filter(condition)

    def with_related(self):
        return self.select_related("category", "uploader")


class MediaItem(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    artist = models.CharField(
        "creator / artist",
        max_length=150,
        blank=True,
        help_text="Optional. Mostly useful for audio tracks.",
    )
    media_type = models.CharField(max_length=10, choices=MediaType.choices)
    file = models.FileField(upload_to=media_upload_path, max_length=255)
    thumbnail = models.ImageField(
        upload_to=thumbnail_upload_path,
        max_length=255,
        blank=True,
        help_text="Optional preview image. Generated automatically for images.",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_items",
    )
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="media_items",
    )
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC
    )
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MediaQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["media_type", "visibility", "is_active", "-created_at"],
                name="media_listing_idx",
            ),
            models.Index(fields=["uploader", "-created_at"], name="media_uploader_idx"),
            models.Index(fields=["-view_count"], name="media_popular_idx"),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_media_type_display()})"

    # -- validation ---------------------------------------------------------
    def clean(self):
        super().clean()
        errors = {}
        file = self.file
        if (
            file
            and not getattr(file, "_committed", True)
            and self.media_type in MediaType.values
        ):
            try:
                validate_media_file(file.file, self.media_type)
            except ValidationError as exc:
                errors["file"] = exc.messages
        thumb = self.thumbnail
        if thumb and not getattr(thumb, "_committed", True):
            try:
                validate_thumbnail(thumb.file)
            except ValidationError as exc:
                errors["thumbnail"] = exc.messages
        if errors:
            raise ValidationError(errors)

    # -- persistence --------------------------------------------------------
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(MediaItem, self.title, 220, self.pk, "media")
        if self.media_type == MediaType.IMAGE and self.file and not self.thumbnail:
            data = make_image_thumbnail(self.file)
            if data:
                self.thumbnail.save("thumb.jpg", ContentFile(data), save=False)
        super().save(*args, **kwargs)

    # -- helpers ------------------------------------------------------------
    def get_absolute_url(self):
        return reverse("media_library:media_detail", kwargs={"slug": self.slug})

    @property
    def file_url(self):
        return reverse(
            "media_library:media_file", kwargs={"slug": self.slug, "kind": "file"}
        )

    @property
    def thumbnail_url(self):
        if not self.thumbnail:
            return ""
        return reverse(
            "media_library:media_file", kwargs={"slug": self.slug, "kind": "thumb"}
        )

    @property
    def card_image_url(self):
        """Lightweight image for listing cards (never a video/audio file)."""
        if self.thumbnail:
            return self.thumbnail_url
        if self.media_type == MediaType.IMAGE and self.file:
            return self.file_url
        return ""

    @property
    def mime_type(self):
        return mimetypes.guess_type(self.file.name)[0] or "application/octet-stream"

    @property
    def is_public(self):
        return self.visibility == Visibility.PUBLIC

    def is_visible_to(self, user):
        if user.is_authenticated and user.is_staff:
            return True
        if not self.is_active:
            return False
        if self.visibility == Visibility.PUBLIC:
            return True
        return user.is_authenticated and self.uploader_id == user.id

    def can_be_managed_by(self, user):
        return user.is_authenticated and (user.is_staff or self.uploader_id == user.id)


@receiver(post_delete, sender=MediaItem)
def delete_media_files(sender, instance, **kwargs):
    """Remove stored files once the database row is gone (after commit)."""
    targets = []
    for field in (instance.file, instance.thumbnail):
        if field and field.name:
            targets.append((field.storage, field.name))

    def _remove():
        for storage, name in targets:
            try:
                storage.delete(name)
            except Exception:  # pragma: no cover - best effort cleanup
                pass

    transaction.on_commit(_remove)


class Favorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites"
    )
    media = models.ForeignKey(
        MediaItem, on_delete=models.CASCADE, related_name="favorited_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "media"], name="unique_favorite")
        ]

    def __str__(self):
        return f"{self.user} ♥ {self.media.title}"


class Comment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments"
    )
    media = models.ForeignKey(
        MediaItem, on_delete=models.CASCADE, related_name="comments"
    )
    text = models.TextField(max_length=1000)
    is_hidden = models.BooleanField(
        default=False, help_text="Hide this comment (moderation)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.user} on {self.media.title}"


class ContactMessage(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=150)
    message = models.TextField(max_length=3000)
    is_reviewed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} — {self.name}"
