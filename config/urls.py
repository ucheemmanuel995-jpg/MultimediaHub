"""Root URL configuration for MultimediaHub."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("media_library.urls")),
]

handler404 = "media_library.views.page_not_found"
