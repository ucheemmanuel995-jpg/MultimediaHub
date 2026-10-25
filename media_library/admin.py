from django.contrib import admin
from django.utils.html import format_html

from .models import Category, Comment, ContactMessage, Favorite, MediaItem


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at",)


@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    list_display = (
        "preview",
        "title",
        "media_type",
        "category",
        "uploader",
        "visibility",
        "is_featured",
        "is_active",
        "view_count",
        "created_at",
    )
    list_display_links = ("preview", "title")
    list_filter = ("media_type", "visibility", "is_featured", "is_active", "category")
    list_editable = ("is_featured", "is_active")
    search_fields = ("title", "description", "artist", "uploader__username", "category__name")
    list_select_related = ("category", "uploader")
    raw_id_fields = ("uploader",)
    readonly_fields = ("preview", "view_count", "created_at", "updated_at")
    date_hierarchy = "created_at"
    actions = ["feature", "unfeature", "activate", "deactivate"]
    fieldsets = (
        ("Content", {"fields": ("title", "slug", "description", "artist", "category")}),
        ("Files", {"fields": ("media_type", "file", "thumbnail", "preview")}),
        ("Publishing", {"fields": ("uploader", "visibility", "is_featured", "is_active")}),
        ("Statistics", {"fields": ("view_count", "created_at", "updated_at")}),
    )

    @admin.display(description="Preview")
    def preview(self, obj):
        if obj and obj.pk and obj.card_image_url:
            return format_html(
                '<img src="{}" alt="" style="height:48px;width:auto;border-radius:6px;">',
                obj.card_image_url,
            )
        return "—"

    @admin.action(description="Mark selected as featured")
    def feature(self, request, queryset):
        queryset.update(is_featured=True)

    @admin.action(description="Remove featured flag")
    def unfeature(self, request, queryset):
        queryset.update(is_featured=False)

    @admin.action(description="Activate selected")
    def activate(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Deactivate selected (hide from site)")
    def deactivate(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ("user", "media", "created_at")
    list_select_related = ("user", "media")
    search_fields = ("user__username", "media__title")
    raw_id_fields = ("user", "media")
    readonly_fields = ("created_at",)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("short_text", "user", "media", "is_hidden", "created_at")
    list_filter = ("is_hidden", "created_at")
    list_select_related = ("user", "media")
    search_fields = ("text", "user__username", "media__title")
    raw_id_fields = ("user", "media")
    readonly_fields = ("created_at", "updated_at")
    actions = ["hide_comments", "unhide_comments"]

    @admin.display(description="Comment")
    def short_text(self, obj):
        return obj.text[:60] + ("…" if len(obj.text) > 60 else "")

    @admin.action(description="Hide selected comments")
    def hide_comments(self, request, queryset):
        queryset.update(is_hidden=True)

    @admin.action(description="Unhide selected comments")
    def unhide_comments(self, request, queryset):
        queryset.update(is_hidden=False)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "name", "email", "is_reviewed", "created_at")
    list_filter = ("is_reviewed", "created_at")
    list_editable = ("is_reviewed",)
    search_fields = ("name", "email", "subject", "message")
    readonly_fields = ("name", "email", "subject", "message", "created_at")
    actions = ["mark_reviewed"]

    @admin.action(description="Mark selected as reviewed")
    def mark_reviewed(self, request, queryset):
        queryset.update(is_reviewed=True)

    def has_add_permission(self, request):
        return False
