import mimetypes
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Case, Count, F, IntegerField, Q, When
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .forms import CommentForm, ContactForm, MediaForm, ProfileForm, RegisterForm
from .models import Category, Comment, Favorite, MediaItem, MediaType, Visibility
from .utils import iter_file_range, parse_range_header, safe_next_url

User = get_user_model()

SORT_OPTIONS = {
    "newest": ("-created_at", "Newest first"),
    "oldest": ("created_at", "Oldest first"),
    "title": ("title", "Title A–Z"),
    "popular": ("-view_count", "Most viewed"),
}
SORT_CHOICES = [(key, label) for key, (_, label) in SORT_OPTIONS.items()]

TYPE_LIBRARY_URLS = {
    MediaType.IMAGE: "media_library:gallery",
    MediaType.VIDEO: "media_library:video_library",
    MediaType.AUDIO: "media_library:audio_library",
}


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def apply_filters(request, queryset, *, fixed_type=None, allow_visibility=False):
    """
    Apply validated search / filter / sort parameters from ``request.GET``.

    Returns ``(queryset, filters)`` where ``filters`` holds only the cleaned,
    accepted values. Unknown values are ignored rather than trusted.
    """
    filters = {}

    query = request.GET.get("q", "").strip()[:100]
    if query:
        filters["q"] = query
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(artist__icontains=query)
            | Q(category__name__icontains=query)
        )

    if fixed_type:
        queryset = queryset.filter(media_type=fixed_type)
    else:
        media_type = request.GET.get("type", "")
        if media_type in MediaType.values:
            filters["type"] = media_type
            queryset = queryset.filter(media_type=media_type)

    category_slug = request.GET.get("category", "").strip()[:120]
    if category_slug:
        filters["category"] = category_slug
        queryset = queryset.filter(category__slug=category_slug)

    if allow_visibility:
        visibility = request.GET.get("visibility", "")
        if visibility in Visibility.values:
            filters["visibility"] = visibility
            queryset = queryset.filter(visibility=visibility)

    sort = request.GET.get("sort", "")
    if sort not in SORT_OPTIONS:
        sort = "newest"
    else:
        filters["sort"] = sort
    tie_breaker = "pk" if sort == "oldest" else "-pk"
    queryset = queryset.order_by(SORT_OPTIONS[sort][0], tie_breaker)
    filters.setdefault("sort", "newest")
    return queryset, filters


def paginate(request, queryset, per_page=None):
    paginator = Paginator(queryset, per_page or settings.ITEMS_PER_PAGE)
    return paginator.get_page(request.GET.get("page"))


def favorite_ids_for(user, items):
    """IDs of the given items that ``user`` has favorited (single query)."""
    if not user.is_authenticated:
        return set()
    return set(
        Favorite.objects.filter(user=user, media__in=list(items)).values_list(
            "media_id", flat=True
        )
    )


def _library(request, template, *, base_queryset, title, subtitle="", fixed_type=None, extra=None):
    queryset, filters = apply_filters(request, base_queryset, fixed_type=fixed_type)
    page_obj = paginate(request, queryset)
    context = {
        "title": title,
        "subtitle": subtitle,
        "page_obj": page_obj,
        "filters": filters,
        "fixed_type": fixed_type,
        "categories": Category.objects.all(),
        "sort_choices": SORT_CHOICES,
        "favorite_ids": favorite_ids_for(request.user, page_obj.object_list),
        "has_filters": any(k in filters for k in ("q", "type", "category")),
    }
    if extra:
        context.update(extra)
    return render(request, template, context)


def page_not_found(request, exception=None):
    return render(request, "media_library/404.html", status=404)


# --------------------------------------------------------------------------
# Public discovery
# --------------------------------------------------------------------------
def home(request):
    public = MediaItem.objects.public().with_related()
    featured = list(public.filter(is_featured=True)[:6])
    recent = list(public[:8])
    popular = list(public.filter(view_count__gt=0).order_by("-view_count", "-created_at")[:8])
    categories = (
        Category.objects.annotate(
            media_count=Count(
                "media_items",
                filter=Q(
                    media_items__is_active=True,
                    media_items__visibility=Visibility.PUBLIC,
                ),
            )
        )
        .filter(media_count__gt=0)
        .order_by("-media_count", "name")[:8]
    )
    shown = featured + recent + popular
    return render(
        request,
        "media_library/home.html",
        {
            "featured": featured,
            "recent": recent,
            "popular": popular,
            "categories": categories,
            "favorite_ids": favorite_ids_for(request.user, shown),
            "has_any_media": bool(recent),
        },
    )


def explore(request):
    return _library(
        request,
        "media_library/explore.html",
        base_queryset=MediaItem.objects.public().with_related(),
        title="Explore",
        subtitle="Everything shared publicly on MultimediaHub.",
    )


def gallery(request):
    return _library(
        request,
        "media_library/gallery.html",
        base_queryset=MediaItem.objects.public().with_related(),
        title="Image gallery",
        subtitle="Photos, artwork and graphics.",
        fixed_type=MediaType.IMAGE,
    )


def video_library(request):
    return _library(
        request,
        "media_library/video_library.html",
        base_queryset=MediaItem.objects.public().with_related(),
        title="Video library",
        subtitle="Watch videos right in your browser.",
        fixed_type=MediaType.VIDEO,
    )


def audio_library(request):
    return _library(
        request,
        "media_library/audio_library.html",
        base_queryset=MediaItem.objects.public().with_related(),
        title="Audio library",
        subtitle="Music, podcasts and sound clips.",
        fixed_type=MediaType.AUDIO,
    )


def search(request):
    query = request.GET.get("q", "").strip()
    return _library(
        request,
        "media_library/search_results.html",
        base_queryset=MediaItem.objects.public().with_related(),
        title="Search",
        subtitle=f"Results for “{query[:100]}”" if query else "Search titles, descriptions and categories.",
        extra={"searched": bool(query)},
    )


def categories(request):
    items = Category.objects.annotate(
        media_count=Count(
            "media_items",
            filter=Q(
                media_items__is_active=True,
                media_items__visibility=Visibility.PUBLIC,
            ),
        )
    ).order_by("name")
    return render(request, "media_library/categories.html", {"categories": items})


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    return _library(
        request,
        "media_library/category_detail.html",
        base_queryset=MediaItem.objects.public().with_related().filter(category=category),
        title=category.name,
        subtitle=category.description,
        extra={"category": category},
    )


# --------------------------------------------------------------------------
# Media detail and delivery
# --------------------------------------------------------------------------
def _related_items(item, limit=4):
    queryset = (
        MediaItem.objects.public()
        .with_related()
        .filter(media_type=item.media_type)
        .exclude(pk=item.pk)
    )
    if item.category_id:
        queryset = queryset.annotate(
            same_category=Case(
                When(category_id=item.category_id, then=0),
                default=1,
                output_field=IntegerField(),
            )
        ).order_by("same_category", "-created_at")
    return list(queryset[:limit])


def media_detail(request, slug):
    item = get_object_or_404(MediaItem.objects.with_related(), slug=slug)
    if not item.is_visible_to(request.user):
        raise Http404("Media not found")

    # Count one view per session, ignoring the uploader's own visits.
    viewed = request.session.get("viewed_media", [])
    if item.pk not in viewed and item.uploader_id != request.user.id:
        MediaItem.objects.filter(pk=item.pk).update(view_count=F("view_count") + 1)
        item.view_count += 1
        request.session["viewed_media"] = viewed[-199:] + [item.pk]

    related = _related_items(item)
    comments = item.comments.filter(is_hidden=False).select_related("user")
    is_favorite = (
        request.user.is_authenticated
        and Favorite.objects.filter(user=request.user, media=item).exists()
    )
    favorite_ids = {item.pk} if is_favorite else set()
    favorite_ids |= favorite_ids_for(request.user, related)

    return render(
        request,
        "media_library/media_detail.html",
        {
            "item": item,
            "related": related,
            "comments": comments,
            "comment_form": CommentForm(),
            "favorite_ids": favorite_ids,
            "can_manage": item.can_be_managed_by(request.user),
            "back_url": reverse(TYPE_LIBRARY_URLS[item.media_type]),
        },
    )


def media_file(request, slug, kind):
    """
    Authorised delivery of media files and thumbnails.

    Uploaded files are not reachable through a public MEDIA_URL; every request
    passes through the same visibility check as the detail page. Supports HTTP
    Range requests so audio/video seeking works.
    """
    if kind not in ("file", "thumb"):
        raise Http404
    item = get_object_or_404(MediaItem, slug=slug)
    if not item.is_visible_to(request.user):
        raise Http404("Media not found")

    field = item.file if kind == "file" else item.thumbnail
    if not field or not field.name:
        raise Http404

    try:
        path = field.path
    except NotImplementedError:  # non-filesystem storage backends
        path = None

    if path is not None and not os.path.isfile(path):
        raise Http404

    content_type = mimetypes.guess_type(field.name)[0] or "application/octet-stream"
    if path is None:
        response = FileResponse(field.open("rb"), content_type=content_type)
    else:
        size = os.path.getsize(path)
        byte_range = parse_range_header(request.headers.get("Range"), size)
        if byte_range is False:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        if byte_range:
            start, end = byte_range
            response = StreamingHttpResponse(
                iter_file_range(path, start, end), status=206, content_type=content_type
            )
            response["Content-Length"] = str(end - start + 1)
            response["Content-Range"] = f"bytes {start}-{end}/{size}"
        else:
            response = FileResponse(open(path, "rb"), content_type=content_type)
            response["Content-Length"] = str(size)

    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = "inline"
    if item.is_public and item.is_active:
        response["Cache-Control"] = "public, max-age=300"
    else:
        response["Cache-Control"] = "private, no-store"
    return response


# --------------------------------------------------------------------------
# Favorites
# --------------------------------------------------------------------------
@login_required
@require_POST
def favorite_toggle(request, slug):
    item = get_object_or_404(MediaItem, slug=slug)
    if not item.is_visible_to(request.user):
        raise Http404
    favorite, created = Favorite.objects.get_or_create(user=request.user, media=item)
    if not created:
        favorite.delete()
    favorited = created

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"favorited": favorited})

    messages.success(
        request,
        "Added to your favorites." if favorited else "Removed from your favorites.",
    )
    return redirect(safe_next_url(request, item.get_absolute_url()))


@login_required
def favorites(request):
    queryset = (
        Favorite.objects.filter(user=request.user)
        .filter(media__in=MediaItem.objects.visible_to(request.user))
        .select_related("media", "media__category", "media__uploader")
    )
    page_obj = paginate(request, queryset)
    items = [fav.media for fav in page_obj.object_list]
    return render(
        request,
        "media_library/favorites.html",
        {
            "page_obj": page_obj,
            "items": items,
            "favorite_ids": {item.pk for item in items},
        },
    )


# --------------------------------------------------------------------------
# Comments
# --------------------------------------------------------------------------
@login_required
@require_POST
def comment_add(request, slug):
    item = get_object_or_404(MediaItem, slug=slug)
    if not item.is_visible_to(request.user):
        raise Http404
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.user = request.user
        comment.media = item
        comment.save()
        messages.success(request, "Your comment was posted.")
    else:
        for error in form.errors.get("text", ["Your comment could not be posted."]):
            messages.error(request, error)
    return redirect(f"{item.get_absolute_url()}#comments")


@login_required
@require_http_methods(["GET", "POST"])
def comment_edit(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("media"), pk=pk)
    if comment.user_id != request.user.id:
        raise PermissionDenied
    if not comment.media.is_visible_to(request.user):
        raise Http404
    form = CommentForm(request.POST or None, instance=comment)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Comment updated.")
        return redirect(f"{comment.media.get_absolute_url()}#comments")
    return render(
        request,
        "media_library/comment_edit.html",
        {"form": form, "comment": comment},
    )


@login_required
@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("media"), pk=pk)
    if comment.user_id != request.user.id and not request.user.is_staff:
        raise PermissionDenied
    media_url = comment.media.get_absolute_url()
    comment.delete()
    messages.success(request, "Comment deleted.")
    return redirect(f"{media_url}#comments")


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------
def register(request):
    if request.user.is_authenticated:
        return redirect("media_library:dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"Welcome to MultimediaHub, {user.username}!")
        return redirect("media_library:dashboard")
    return render(request, "media_library/register.html", {"form": form})


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile was updated.")
        return redirect("media_library:profile")
    my_items = request.user.media_items.select_related("category")
    return render(
        request,
        "media_library/profile.html",
        {
            "form": form,
            "recent_media": list(my_items[:6]),
            "media_total": my_items.count(),
            "favorite_total": Favorite.objects.filter(user=request.user).count(),
        },
    )


class PasswordChangeViewWithMessage(SuccessMessageMixin, PasswordChangeView):
    success_message = "Your password was changed."


# --------------------------------------------------------------------------
# Member area
# --------------------------------------------------------------------------
@login_required
def dashboard(request):
    mine = request.user.media_items.all()
    stats = mine.aggregate(
        total=Count("id"),
        images=Count("id", filter=Q(media_type=MediaType.IMAGE)),
        videos=Count("id", filter=Q(media_type=MediaType.VIDEO)),
        audio=Count("id", filter=Q(media_type=MediaType.AUDIO)),
        public=Count("id", filter=Q(visibility=Visibility.PUBLIC)),
        private=Count("id", filter=Q(visibility=Visibility.PRIVATE)),
    )
    recent = list(mine.select_related("category")[:6])
    favorites_qs = (
        Favorite.objects.filter(user=request.user)
        .filter(media__in=MediaItem.objects.visible_to(request.user))
        .select_related("media", "media__category")
    )
    favorite_items = [fav.media for fav in favorites_qs[:4]]
    return render(
        request,
        "media_library/dashboard.html",
        {
            "stats": stats,
            "recent": recent,
            "favorite_items": favorite_items,
            "favorite_total": favorites_qs.count(),
            "favorite_ids": {item.pk for item in favorite_items},
        },
    )


@login_required
def my_media(request):
    base = request.user.media_items.select_related("category")
    queryset, filters = apply_filters(request, base, allow_visibility=True)
    page_obj = paginate(request, queryset)
    return render(
        request,
        "media_library/my_media.html",
        {
            "page_obj": page_obj,
            "filters": filters,
            "categories": Category.objects.all(),
            "sort_choices": SORT_CHOICES,
            "has_filters": any(k in filters for k in ("q", "type", "category", "visibility")),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def upload(request):
    form = MediaForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        form.instance.uploader = request.user
        item = form.save()
        messages.success(request, "Your media was uploaded successfully.")
        return redirect(item.get_absolute_url())
    if request.method == "POST":
        messages.error(request, "Please correct the errors below.")
    return render(request, "media_library/upload.html", {"form": form})


def _get_managed_item(request, slug):
    """Return the item if the user may manage it, else 404 (hidden) or 403."""
    item = get_object_or_404(MediaItem.objects.select_related("uploader"), slug=slug)
    if item.can_be_managed_by(request.user):
        return item
    if not item.is_visible_to(request.user):
        raise Http404
    raise PermissionDenied


@login_required
@require_http_methods(["GET", "POST"])
def edit_media(request, slug):
    item = _get_managed_item(request, slug)
    form = MediaForm(request.POST or None, request.FILES or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your changes were saved.")
        return redirect("media_library:my_media")
    if request.method == "POST":
        messages.error(request, "Please correct the errors below.")
    return render(request, "media_library/edit_media.html", {"form": form, "item": item})


@login_required
@require_http_methods(["GET", "POST"])
def delete_media(request, slug):
    item = _get_managed_item(request, slug)
    if request.method == "POST":
        title = item.title
        item.delete()
        messages.success(request, f"“{title}” was deleted.")
        return redirect("media_library:my_media")
    return render(request, "media_library/confirm_delete.html", {"item": item})


# --------------------------------------------------------------------------
# Information pages
# --------------------------------------------------------------------------
def about(request):
    return render(request, "media_library/about.html")


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Thanks! Your message was saved and will be reviewed by our team.",
            )
            return redirect("media_library:contact")
        messages.error(request, "Please correct the errors below.")
    return render(request, "media_library/contact.html", {"form": form})


def privacy(request):
    return render(request, "media_library/privacy.html")


def terms(request):
    return render(request, "media_library/terms.html")
