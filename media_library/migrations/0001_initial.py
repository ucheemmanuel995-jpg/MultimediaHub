import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import media_library.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("slug", models.SlugField(blank=True, max_length=120, unique=True)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name_plural": "categories",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="ContactMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("email", models.EmailField(max_length=254)),
                ("subject", models.CharField(max_length=150)),
                ("message", models.TextField(max_length=3000)),
                ("is_reviewed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="MediaItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("slug", models.SlugField(blank=True, max_length=220, unique=True)),
                ("description", models.TextField(blank=True)),
                ("artist", models.CharField(blank=True, help_text="Optional. Mostly useful for audio tracks.", max_length=150, verbose_name="creator / artist")),
                ("media_type", models.CharField(choices=[("image", "Image"), ("video", "Video"), ("audio", "Audio")], max_length=10)),
                ("file", models.FileField(max_length=255, upload_to=media_library.models.media_upload_path)),
                ("thumbnail", models.ImageField(blank=True, help_text="Optional preview image. Generated automatically for images.", max_length=255, upload_to=media_library.models.thumbnail_upload_path)),
                ("visibility", models.CharField(choices=[("public", "Public"), ("private", "Private")], default="public", max_length=10)),
                ("is_featured", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("view_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="media_items", to="media_library.category")),
                ("uploader", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="media_items", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Favorite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("media", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="favorited_by", to="media_library.mediaitem")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="favorites", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Comment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField(max_length=1000)),
                ("is_hidden", models.BooleanField(default=False, help_text="Hide this comment (moderation).")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("media", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="comments", to="media_library.mediaitem")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="comments", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="mediaitem",
            index=models.Index(fields=["media_type", "visibility", "is_active", "-created_at"], name="media_listing_idx"),
        ),
        migrations.AddIndex(
            model_name="mediaitem",
            index=models.Index(fields=["uploader", "-created_at"], name="media_uploader_idx"),
        ),
        migrations.AddIndex(
            model_name="mediaitem",
            index=models.Index(fields=["-view_count"], name="media_popular_idx"),
        ),
        migrations.AddConstraint(
            model_name="favorite",
            constraint=models.UniqueConstraint(fields=("user", "media"), name="unique_favorite"),
        ),
    ]
