from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "media_library"

urlpatterns = [
    # Public discovery
    path("", views.home, name="home"),
    path("explore/", views.explore, name="explore"),
    path("images/", views.gallery, name="gallery"),
    path("videos/", views.video_library, name="video_library"),
    path("audio/", views.audio_library, name="audio_library"),
    path("search/", views.search, name="search"),
    path("categories/", views.categories, name="categories"),
    path("categories/<slug:slug>/", views.category_detail, name="category_detail"),
    # Media
    path("media/<slug:slug>/", views.media_detail, name="media_detail"),
    path("media/<slug:slug>/<str:kind>/", views.media_file, name="media_file"),
    path("media/<slug:slug>/favorite/toggle/", views.favorite_toggle, name="favorite_toggle"),
    path("media/<slug:slug>/comments/add/", views.comment_add, name="comment_add"),
    path("comments/<int:pk>/edit/", views.comment_edit, name="comment_edit"),
    path("comments/<int:pk>/delete/", views.comment_delete, name="comment_delete"),
    # Account
    path("register/", views.register, name="register"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="media_library/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    path(
        "profile/password/",
        views.PasswordChangeViewWithMessage.as_view(
            template_name="media_library/password_change.html",
            success_url=reverse_lazy("media_library:profile"),
        ),
        name="password_change",
    ),
    # Member area
    path("dashboard/", views.dashboard, name="dashboard"),
    path("my-media/", views.my_media, name="my_media"),
    path("upload/", views.upload, name="upload"),
    path("my-media/<slug:slug>/edit/", views.edit_media, name="edit_media"),
    path("my-media/<slug:slug>/delete/", views.delete_media, name="delete_media"),
    path("favorites/", views.favorites, name="favorites"),
    # Information
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("privacy/", views.privacy, name="privacy"),
    path("terms/", views.terms, name="terms"),
]
