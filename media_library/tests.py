import io
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Category, Comment, ContactMessage, Favorite, MediaItem
from .utils import parse_range_header

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def png_bytes(size=(40, 30), color=(120, 80, 220)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def png_upload(name="photo.png"):
    return SimpleUploadedFile(name, png_bytes(), content_type="image/png")


def mp4_upload(name="clip.mp4"):
    data = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
    return SimpleUploadedFile(name, data, content_type="video/mp4")


def mp3_upload(name="track.mp3"):
    data = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 64
    return SimpleUploadedFile(name, data, content_type="audio/mpeg")


def wav_upload(name="sound.wav"):
    data = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
    return SimpleUploadedFile(name, data, content_type="audio/wav")


class MediaTestCase(TestCase):
    """Base class: temporary MEDIA_ROOT and no HTTPS redirects."""

    @classmethod
    def setUpClass(cls):
        cls._tmp_media = tempfile.mkdtemp(prefix="mmhub-test-")
        cls._override = override_settings(
            MEDIA_ROOT=cls._tmp_media, SECURE_SSL_REDIRECT=False
        )
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._tmp_media, ignore_errors=True)

    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", "S3cure-pass!")
        self.bob = User.objects.create_user("bob", "bob@example.com", "S3cure-pass!")
        self.staff = User.objects.create_user(
            "staffer", "staff@example.com", "S3cure-pass!", is_staff=True, is_superuser=True
        )
        self.category = Category.objects.create(name="Nature", description="Outdoors")

    def make_item(self, **overrides):
        defaults = {
            "title": "Sunset",
            "media_type": "image",
            "file": png_upload(),
            "uploader": self.alice,
            "category": self.category,
        }
        defaults.update(overrides)
        return MediaItem.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ModelTests(MediaTestCase):
    def test_slug_generated_and_unique(self):
        first = self.make_item(title="Same Title")
        second = self.make_item(title="Same Title", file=png_upload("b.png"))
        self.assertTrue(first.slug)
        self.assertNotEqual(first.slug, second.slug)

    def test_image_thumbnail_generated(self):
        item = self.make_item()
        self.assertTrue(item.thumbnail)
        self.assertTrue(os.path.exists(item.thumbnail.path))

    def test_upload_path_is_randomised(self):
        item = self.make_item(file=png_upload("../../evil name.png"))
        self.assertTrue(item.file.name.startswith("images/"))
        self.assertNotIn("evil", item.file.name)
        self.assertNotIn("..", item.file.name)

    def test_str_representations(self):
        item = self.make_item()
        self.assertIn("Sunset", str(item))
        self.assertEqual(str(self.category), "Nature")

    def test_favorite_unique_constraint(self):
        item = self.make_item()
        Favorite.objects.create(user=self.bob, media=item)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Favorite.objects.create(user=self.bob, media=item)

    def test_public_queryset_hides_private_and_inactive(self):
        public = self.make_item(title="Public one")
        self.make_item(title="Private one", visibility="private", file=png_upload("p.png"))
        self.make_item(title="Inactive one", is_active=False, file=png_upload("i.png"))
        self.assertEqual(list(MediaItem.objects.public()), [public])

    def test_visible_to_rules(self):
        private = self.make_item(visibility="private")
        self.assertIn(private, MediaItem.objects.visible_to(self.alice))
        self.assertNotIn(private, MediaItem.objects.visible_to(self.bob))
        self.assertIn(private, MediaItem.objects.visible_to(self.staff))


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------
class PublicPageTests(MediaTestCase):
    def test_homepage_empty_state(self):
        response = self.client.get(reverse("media_library:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No media has been shared yet")

    def test_homepage_shows_real_media_only_when_public(self):
        self.make_item(title="Visible Photo", is_featured=True)
        self.make_item(title="Secret Photo", visibility="private", file=png_upload("s.png"))
        response = self.client.get(reverse("media_library:home"))
        self.assertContains(response, "Visible Photo")
        self.assertNotContains(response, "Secret Photo")

    def test_library_pages_filter_by_type(self):
        self.make_item(title="An Image")
        self.make_item(title="A Video", media_type="video", file=mp4_upload())
        self.make_item(title="An Audio", media_type="audio", file=mp3_upload())

        gallery = self.client.get(reverse("media_library:gallery"))
        self.assertContains(gallery, "An Image")
        self.assertNotContains(gallery, "A Video")

        videos = self.client.get(reverse("media_library:video_library"))
        self.assertContains(videos, "A Video")
        self.assertNotContains(videos, "An Audio")

        audio = self.client.get(reverse("media_library:audio_library"))
        self.assertContains(audio, "An Audio")
        self.assertNotContains(audio, "An Image")

    def test_explore_lists_everything_public(self):
        self.make_item(title="An Image")
        self.make_item(title="A Video", media_type="video", file=mp4_upload())
        response = self.client.get(reverse("media_library:explore"))
        self.assertContains(response, "An Image")
        self.assertContains(response, "A Video")

    def test_search_matches_title_description_and_category(self):
        self.make_item(title="Mountain lake", description="calm water")
        self.make_item(title="City", description="busy streets", file=png_upload("c.png"))
        url = reverse("media_library:search")

        self.assertContains(self.client.get(url, {"q": "mountain"}), "Mountain lake")
        by_description = self.client.get(url, {"q": "busy"})
        self.assertContains(by_description, "City")
        self.assertNotContains(by_description, "Mountain lake")
        # category name search (both items share the "Nature" category)
        self.assertContains(self.client.get(url, {"q": "nature"}), "Mountain lake")
        self.assertContains(self.client.get(url, {"q": "zzzz-nothing"}), "No media matches")

    def test_search_without_query_shows_prompt(self):
        response = self.client.get(reverse("media_library:search"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "What are you looking for?")

    def test_invalid_filter_and_sort_values_are_ignored(self):
        self.make_item(title="Okay")
        response = self.client.get(
            reverse("media_library:explore"),
            {"type": "'; DROP TABLE x;--", "sort": "bogus", "page": "abc"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Okay")

    def test_sorting(self):
        self.make_item(title="Banana", file=png_upload("1.png"))
        self.make_item(title="Apple", file=png_upload("2.png"))
        response = self.client.get(reverse("media_library:explore"), {"sort": "title"})
        titles = [item.title for item in response.context["page_obj"].object_list]
        self.assertEqual(titles, ["Apple", "Banana"])
        response = self.client.get(reverse("media_library:explore"), {"sort": "oldest"})
        titles = [item.title for item in response.context["page_obj"].object_list]
        self.assertEqual(titles, ["Banana", "Apple"])

    def test_pagination_and_filter_preservation(self):
        for index in range(13):
            self.make_item(title=f"Photo {index}", file=png_upload(f"{index}.png"))
        url = reverse("media_library:gallery")
        page1 = self.client.get(url, {"sort": "title"})
        self.assertEqual(len(page1.context["page_obj"].object_list), 12)
        self.assertContains(page1, "sort=title&amp;page=2")
        page2 = self.client.get(url, {"sort": "title", "page": 2})
        self.assertEqual(len(page2.context["page_obj"].object_list), 1)

    def test_categories_and_category_detail(self):
        self.make_item(title="Forest")
        listing = self.client.get(reverse("media_library:categories"))
        self.assertContains(listing, "Nature")
        detail = self.client.get(self.category.get_absolute_url())
        self.assertContains(detail, "Forest")
        missing = self.client.get(reverse("media_library:category_detail", args=["nope"]))
        self.assertEqual(missing.status_code, 404)

    def test_static_pages(self):
        for name in ("about", "contact", "privacy", "terms"):
            response = self.client.get(reverse(f"media_library:{name}"))
            self.assertEqual(response.status_code, 200, name)

    def test_unknown_url_returns_404(self):
        self.assertEqual(self.client.get("/this/does/not/exist/").status_code, 404)


# ---------------------------------------------------------------------------
# Detail pages and file delivery
# ---------------------------------------------------------------------------
class DetailAndDeliveryTests(MediaTestCase):
    def test_detail_page_for_each_type(self):
        image = self.make_item(title="Img")
        video = self.make_item(title="Vid", media_type="video", file=mp4_upload())
        audio = self.make_item(title="Aud", media_type="audio", file=mp3_upload())
        for item, tag in ((image, "<img"), (video, "<video"), (audio, "<audio")):
            response = self.client.get(item.get_absolute_url())
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, tag)
            self.assertContains(response, item.title)

    def test_missing_media_is_404(self):
        response = self.client.get(reverse("media_library:media_detail", args=["missing"]))
        self.assertEqual(response.status_code, 404)

    def test_view_count_increments_once_per_session(self):
        item = self.make_item()
        self.client.get(item.get_absolute_url())
        self.client.get(item.get_absolute_url())
        item.refresh_from_db()
        self.assertEqual(item.view_count, 1)

    def test_owner_visits_do_not_count(self):
        item = self.make_item()
        self.client.force_login(self.alice)
        self.client.get(item.get_absolute_url())
        item.refresh_from_db()
        self.assertEqual(item.view_count, 0)

    def test_private_detail_permissions(self):
        item = self.make_item(visibility="private")
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 200)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 200)

    def test_inactive_media_hidden_from_public(self):
        item = self.make_item(is_active=False)
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)

    def test_public_file_is_served(self):
        item = self.make_item()
        response = self.client.get(item.file_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(b"".join(response.streaming_content), png_bytes())

    def test_private_file_cannot_be_fetched_directly(self):
        item = self.make_item(visibility="private")
        for url in (item.file_url, item.thumbnail_url):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(item.file_url).status_code, 404)
        self.client.force_login(self.alice)
        response = self.client.get(item.file_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])

    def test_media_root_is_not_publicly_routed(self):
        item = self.make_item()
        self.assertEqual(self.client.get(f"/uploads/{item.file.name}").status_code, 404)

    def test_invalid_file_kind_is_404(self):
        item = self.make_item()
        url = reverse("media_library:media_file", kwargs={"slug": item.slug, "kind": "secret"})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_range_requests(self):
        item = self.make_item(media_type="audio", file=mp3_upload(), title="Song")
        total = item.file.size
        response = self.client.get(item.file_url, HTTP_RANGE="bytes=0-9")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], f"bytes 0-9/{total}")
        self.assertEqual(len(b"".join(response.streaming_content)), 10)
        bad = self.client.get(item.file_url, HTTP_RANGE=f"bytes={total + 100}-")
        self.assertEqual(bad.status_code, 416)

    def test_parse_range_header(self):
        self.assertEqual(parse_range_header("bytes=0-9", 100), (0, 9))
        self.assertEqual(parse_range_header("bytes=90-", 100), (90, 99))
        self.assertEqual(parse_range_header("bytes=-10", 100), (90, 99))
        self.assertIsNone(parse_range_header("junk", 100))
        self.assertIs(parse_range_header("bytes=500-", 100), False)

    def test_related_media_shown_and_excludes_private(self):
        main = self.make_item(title="Main")
        self.make_item(title="Sibling", file=png_upload("s.png"))
        self.make_item(title="Hidden Sibling", visibility="private", file=png_upload("h.png"))
        response = self.client.get(main.get_absolute_url())
        self.assertContains(response, "Sibling")
        self.assertNotContains(response, "Hidden Sibling")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class AuthTests(MediaTestCase):
    def test_registration_creates_user_and_logs_in(self):
        response = self.client.post(
            reverse("media_library:register"),
            {
                "username": "newbie",
                "email": "newbie@example.com",
                "password1": "Tr1cky-Passw0rd!",
                "password2": "Tr1cky-Passw0rd!",
            },
        )
        self.assertRedirects(response, reverse("media_library:dashboard"))
        self.assertTrue(User.objects.filter(username="newbie").exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), User.objects.get(username="newbie").pk)

    def test_registration_rejects_duplicate_username_and_email(self):
        base = {"password1": "Tr1cky-Passw0rd!", "password2": "Tr1cky-Passw0rd!"}
        dup_user = self.client.post(
            reverse("media_library:register"),
            {"username": "alice", "email": "other@example.com", **base},
        )
        self.assertEqual(dup_user.status_code, 200)
        self.assertTrue(dup_user.context["form"].errors.get("username"))
        dup_email = self.client.post(
            reverse("media_library:register"),
            {"username": "fresh", "email": "ALICE@example.com", **base},
        )
        self.assertTrue(dup_email.context["form"].errors.get("email"))

    def test_registration_password_validation(self):
        response = self.client.post(
            reverse("media_library:register"),
            {
                "username": "weak",
                "email": "weak@example.com",
                "password1": "12345678",
                "password2": "12345678",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("password2"))
        self.assertFalse(User.objects.filter(username="weak").exists())

    def test_registration_password_mismatch(self):
        response = self.client.post(
            reverse("media_library:register"),
            {
                "username": "mismatch",
                "email": "m@example.com",
                "password1": "Tr1cky-Passw0rd!",
                "password2": "Different-Passw0rd!",
            },
        )
        self.assertTrue(response.context["form"].errors.get("password2"))

    def test_login_and_logout(self):
        response = self.client.post(
            reverse("media_library:login"),
            {"username": "alice", "password": "S3cure-pass!"},
        )
        self.assertRedirects(response, reverse("media_library:dashboard"))
        self.assertIn("_auth_user_id", self.client.session)

        # GET must not log out (POST + CSRF only).
        self.assertEqual(self.client.get(reverse("media_library:logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("media_library:logout"))
        self.assertRedirects(response, reverse("media_library:home"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_with_bad_password(self):
        response = self.client.post(
            reverse("media_library:login"), {"username": "alice", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_csrf(self):
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.alice)
        self.assertEqual(strict.post(reverse("media_library:logout")).status_code, 403)

    def test_member_pages_require_login(self):
        for name in ("dashboard", "my_media", "upload", "favorites", "profile"):
            url = reverse(f"media_library:{name}")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("media_library:login"), response["Location"])

    def test_nav_changes_with_authentication(self):
        anonymous = self.client.get(reverse("media_library:home"))
        self.assertContains(anonymous, "Register")
        self.assertNotContains(anonymous, "Log out")
        self.client.force_login(self.alice)
        authed = self.client.get(reverse("media_library:home"))
        self.assertContains(authed, "Log out")
        self.assertContains(authed, "Dashboard")

    def test_profile_update_cannot_change_privileges(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("media_library:profile"),
            {
                "first_name": "Alice",
                "last_name": "Doe",
                "email": "alice.new@example.com",
                "is_staff": "on",
                "is_superuser": "on",
            },
        )
        self.assertRedirects(response, reverse("media_library:profile"))
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.first_name, "Alice")
        self.assertEqual(self.alice.email, "alice.new@example.com")
        self.assertFalse(self.alice.is_staff)
        self.assertFalse(self.alice.is_superuser)

    def test_profile_rejects_email_used_by_someone_else(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("media_library:profile"),
            {"first_name": "", "last_name": "", "email": "bob@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("email"))


# ---------------------------------------------------------------------------
# Upload, edit, delete
# ---------------------------------------------------------------------------
class UploadTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)
        self.url = reverse("media_library:upload")

    def payload(self, **extra):
        data = {
            "title": "My upload",
            "description": "Something nice",
            "media_type": "image",
            "category": self.category.pk,
            "artist": "",
            "visibility": "public",
        }
        data.update(extra)
        return data

    def test_upload_page_renders(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_upload_image_success(self):
        response = self.client.post(self.url, self.payload(file=png_upload()))
        item = MediaItem.objects.get(title="My upload")
        self.assertRedirects(response, item.get_absolute_url())
        self.assertEqual(item.uploader, self.alice)
        self.assertTrue(os.path.exists(item.file.path))
        self.assertTrue(item.thumbnail)

    def test_upload_video_and_audio_success(self):
        self.client.post(self.url, self.payload(title="Video", media_type="video", file=mp4_upload()))
        self.client.post(self.url, self.payload(title="MP3 audio", media_type="audio", file=mp3_upload()))
        self.client.post(self.url, self.payload(title="WAV audio", media_type="audio", file=wav_upload()))
        self.assertEqual(MediaItem.objects.filter(media_type="video").count(), 1)
        self.assertEqual(MediaItem.objects.filter(media_type="audio").count(), 2)

    def test_upload_requires_file(self):
        response = self.client.post(self.url, self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("file"))
        self.assertEqual(MediaItem.objects.count(), 0)

    def test_fake_image_with_png_extension_rejected(self):
        fake = SimpleUploadedFile("fake.png", b"<?php echo 'hi'; ?>", content_type="image/png")
        response = self.client.post(self.url, self.payload(file=fake))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("file"))
        self.assertEqual(MediaItem.objects.count(), 0)

    def test_wrong_extension_for_type_rejected(self):
        response = self.client.post(
            self.url, self.payload(media_type="image", file=mp4_upload("movie.mp4"))
        )
        self.assertTrue(response.context["form"].errors.get("file"))

    def test_video_with_wrong_signature_rejected(self):
        junk = SimpleUploadedFile("junk.mp4", b"this is just text, not video", content_type="video/mp4")
        response = self.client.post(self.url, self.payload(media_type="video", file=junk))
        self.assertTrue(response.context["form"].errors.get("file"))

    def test_audio_with_wrong_signature_rejected(self):
        junk = SimpleUploadedFile("junk.mp3", b"definitely not audio data", content_type="audio/mpeg")
        response = self.client.post(self.url, self.payload(media_type="audio", file=junk))
        self.assertTrue(response.context["form"].errors.get("file"))

    def test_executable_extension_rejected(self):
        exe = SimpleUploadedFile("run.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        response = self.client.post(self.url, self.payload(file=exe))
        self.assertTrue(response.context["form"].errors.get("file"))

    def test_svg_images_rejected(self):
        svg = SimpleUploadedFile("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", content_type="image/svg+xml")
        response = self.client.post(self.url, self.payload(file=svg))
        self.assertTrue(response.context["form"].errors.get("file"))

    @override_settings(MAX_IMAGE_SIZE_MB=0.00001)
    def test_file_size_limit_enforced(self):
        response = self.client.post(self.url, self.payload(file=png_upload()))
        self.assertEqual(response.status_code, 200)
        errors = response.context["form"].errors.get("file")
        self.assertTrue(errors)
        self.assertIn("too large", errors[0])
        self.assertEqual(MediaItem.objects.count(), 0)

    def test_invalid_thumbnail_rejected(self):
        bad_thumb = SimpleUploadedFile("t.png", b"not an image", content_type="image/png")
        response = self.client.post(
            self.url,
            self.payload(title="Video", media_type="video", file=mp4_upload(), thumbnail=bad_thumb),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("thumbnail"))

    def test_video_with_valid_thumbnail(self):
        response = self.client.post(
            self.url,
            self.payload(title="Video", media_type="video", file=mp4_upload(), thumbnail=png_upload("t.png")),
        )
        item = MediaItem.objects.get(title="Video")
        self.assertRedirects(response, item.get_absolute_url())
        self.assertTrue(item.thumbnail)

    def test_private_upload_not_public(self):
        self.client.post(self.url, self.payload(file=png_upload(), visibility="private"))
        item = MediaItem.objects.get(title="My upload")
        self.client.logout()
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)

    def test_upload_requires_csrf_protection(self):
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.alice)
        response = strict.post(self.url, self.payload(file=png_upload()))
        self.assertEqual(response.status_code, 403)

    def test_user_cannot_set_featured_or_active_or_uploader(self):
        self.client.post(
            self.url,
            self.payload(file=png_upload(), is_featured="on", uploader=self.bob.pk, view_count=999),
        )
        item = MediaItem.objects.get(title="My upload")
        self.assertFalse(item.is_featured)
        self.assertEqual(item.uploader, self.alice)
        self.assertEqual(item.view_count, 0)


class EditDeleteTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.item = self.make_item(title="Original")
        self.edit_url = reverse("media_library:edit_media", args=[self.item.slug])
        self.delete_url = reverse("media_library:delete_media", args=[self.item.slug])

    def edit_payload(self, **extra):
        data = {
            "title": "Renamed",
            "description": "new text",
            "category": "",
            "artist": "",
            "visibility": "public",
        }
        data.update(extra)
        return data

    def test_owner_can_edit(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.edit_url).status_code, 200)
        response = self.client.post(self.edit_url, self.edit_payload())
        self.assertRedirects(response, reverse("media_library:my_media"))
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "Renamed")
        self.assertIsNone(self.item.category)

    def test_other_user_cannot_edit(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.edit_url).status_code, 403)
        self.assertEqual(self.client.post(self.edit_url, self.edit_payload()).status_code, 403)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "Original")

    def test_other_user_gets_404_for_private_item(self):
        self.item.visibility = "private"
        self.item.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.edit_url).status_code, 404)

    def test_anonymous_cannot_edit(self):
        response = self.client.post(self.edit_url, self.edit_payload())
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_staff_can_edit(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.edit_url, self.edit_payload(title="Staff edit"))
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "Staff edit")

    def test_media_type_cannot_be_changed(self):
        self.client.force_login(self.alice)
        self.client.post(self.edit_url, self.edit_payload(media_type="video"))
        self.item.refresh_from_db()
        self.assertEqual(self.item.media_type, "image")

    def test_replacing_file_removes_old_file(self):
        self.client.force_login(self.alice)
        old_path = self.item.file.path
        old_thumb = self.item.thumbnail.path
        response = self.client.post(self.edit_url, self.edit_payload(file=png_upload("new.png")))
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertNotEqual(self.item.file.path, old_path)
        self.assertTrue(os.path.exists(self.item.file.path))
        self.assertFalse(os.path.exists(old_path))
        self.assertFalse(os.path.exists(old_thumb))
        self.assertTrue(os.path.exists(self.item.thumbnail.path))

    def test_replacement_must_match_type(self):
        self.client.force_login(self.alice)
        old_path = self.item.file.path
        response = self.client.post(self.edit_url, self.edit_payload(file=mp4_upload("v.mp4")))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("file"))
        self.item.refresh_from_db()
        self.assertEqual(self.item.file.path, old_path)
        self.assertTrue(os.path.exists(old_path))

    def test_delete_requires_post_confirmation_page(self):
        self.client.force_login(self.alice)
        response = self.client.get(self.delete_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(MediaItem.objects.filter(pk=self.item.pk).exists())

    def test_owner_can_delete_and_files_removed(self):
        self.client.force_login(self.alice)
        file_path = self.item.file.path
        thumb_path = self.item.thumbnail.path
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.delete_url)
        self.assertRedirects(response, reverse("media_library:my_media"))
        self.assertFalse(MediaItem.objects.filter(pk=self.item.pk).exists())
        self.assertFalse(os.path.exists(file_path))
        self.assertFalse(os.path.exists(thumb_path))

    def test_other_user_cannot_delete(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(self.delete_url).status_code, 403)
        self.assertTrue(MediaItem.objects.filter(pk=self.item.pk).exists())

    def test_deletion_requires_csrf(self):
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.alice)
        self.assertEqual(strict.post(self.delete_url).status_code, 403)
        self.assertTrue(MediaItem.objects.filter(pk=self.item.pk).exists())


# ---------------------------------------------------------------------------
# Dashboard and My Media
# ---------------------------------------------------------------------------
class DashboardTests(MediaTestCase):
    def test_dashboard_statistics_come_from_database(self):
        self.make_item(title="I1", file=png_upload("1.png"))
        self.make_item(title="I2", visibility="private", file=png_upload("2.png"))
        self.make_item(title="V1", media_type="video", file=mp4_upload())
        self.make_item(title="A1", media_type="audio", file=mp3_upload())
        self.make_item(title="Bobs", uploader=self.bob, file=png_upload("3.png"))
        self.client.force_login(self.alice)
        response = self.client.get(reverse("media_library:dashboard"))
        stats = response.context["stats"]
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["images"], 2)
        self.assertEqual(stats["videos"], 1)
        self.assertEqual(stats["audio"], 1)
        self.assertEqual(stats["public"], 3)
        self.assertEqual(stats["private"], 1)

    def test_dashboard_empty_state(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("media_library:dashboard"))
        self.assertContains(response, "No uploads yet")

    def test_my_media_only_lists_own_items_with_filters(self):
        self.make_item(title="Mine public", file=png_upload("1.png"))
        self.make_item(title="Mine private", visibility="private", file=png_upload("2.png"))
        self.make_item(title="Mine video", media_type="video", file=mp4_upload())
        self.make_item(title="Not mine", uploader=self.bob, file=png_upload("3.png"))
        self.client.force_login(self.alice)
        url = reverse("media_library:my_media")

        everything = self.client.get(url)
        self.assertContains(everything, "Mine public")
        self.assertNotContains(everything, "Not mine")

        private_only = self.client.get(url, {"visibility": "private"})
        self.assertContains(private_only, "Mine private")
        self.assertNotContains(private_only, "Mine public")

        videos = self.client.get(url, {"type": "video"})
        self.assertContains(videos, "Mine video")
        self.assertNotContains(videos, "Mine public")

        searched = self.client.get(url, {"q": "private"})
        self.assertContains(searched, "Mine private")
        self.assertNotContains(searched, "Mine video")


# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------
class FavoriteTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.item = self.make_item()
        self.url = reverse("media_library:favorite_toggle", args=[self.item.slug])

    def test_requires_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Favorite.objects.count(), 0)

    def test_get_not_allowed(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_add_and_remove(self):
        self.client.force_login(self.bob)
        self.client.post(self.url)
        self.assertEqual(Favorite.objects.filter(user=self.bob, media=self.item).count(), 1)
        page = self.client.get(reverse("media_library:favorites"))
        self.assertContains(page, "Sunset")
        self.client.post(self.url)
        self.assertEqual(Favorite.objects.count(), 0)

    def test_ajax_response(self):
        self.client.force_login(self.bob)
        response = self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.json(), {"favorited": True})
        response = self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.json(), {"favorited": False})

    def test_cannot_favorite_someone_elses_private_media(self):
        private = self.make_item(title="Hidden", visibility="private", file=png_upload("h.png"))
        self.client.force_login(self.bob)
        url = reverse("media_library:favorite_toggle", args=[private.slug])
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(Favorite.objects.count(), 0)

    def test_favorites_are_per_user(self):
        Favorite.objects.create(user=self.alice, media=self.item)
        self.client.force_login(self.bob)
        page = self.client.get(reverse("media_library:favorites"))
        self.assertContains(page, "No favorites yet")

    def test_open_redirect_is_blocked(self):
        self.client.force_login(self.bob)
        response = self.client.post(self.url, {"next": "https://evil.example.com/"})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example.com", response["Location"])

    def test_favorite_of_later_private_item_not_listed(self):
        Favorite.objects.create(user=self.bob, media=self.item)
        self.item.visibility = "private"
        self.item.save()
        self.client.force_login(self.bob)
        page = self.client.get(reverse("media_library:favorites"))
        self.assertNotContains(page, "Sunset")


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
class CommentTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.item = self.make_item()
        self.add_url = reverse("media_library:comment_add", args=[self.item.slug])

    def test_anonymous_cannot_comment(self):
        response = self.client.post(self.add_url, {"text": "Hello there"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Comment.objects.count(), 0)

    def test_post_and_render_comment_escaped(self):
        self.client.force_login(self.bob)
        self.client.post(self.add_url, {"text": "<script>alert(1)</script> nice"})
        self.assertEqual(Comment.objects.count(), 1)
        page = self.client.get(self.item.get_absolute_url())
        self.assertNotContains(page, "<script>alert(1)</script>")
        self.assertContains(page, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_comment_length_validation(self):
        self.client.force_login(self.bob)
        self.client.post(self.add_url, {"text": "x"})
        self.client.post(self.add_url, {"text": "y" * 1001})
        self.assertEqual(Comment.objects.count(), 0)

    def test_owner_can_edit_and_delete(self):
        comment = Comment.objects.create(user=self.bob, media=self.item, text="First")
        self.client.force_login(self.bob)
        edit_url = reverse("media_library:comment_edit", args=[comment.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 200)
        self.client.post(edit_url, {"text": "Edited text"})
        comment.refresh_from_db()
        self.assertEqual(comment.text, "Edited text")
        self.client.post(reverse("media_library:comment_delete", args=[comment.pk]))
        self.assertEqual(Comment.objects.count(), 0)

    def test_others_cannot_edit_or_delete(self):
        comment = Comment.objects.create(user=self.bob, media=self.item, text="Bob's")
        self.client.force_login(self.alice)
        edit_url = reverse("media_library:comment_edit", args=[comment.pk])
        self.assertEqual(self.client.post(edit_url, {"text": "Hacked!"}).status_code, 403)
        delete_url = reverse("media_library:comment_delete", args=[comment.pk])
        self.assertEqual(self.client.post(delete_url).status_code, 403)
        comment.refresh_from_db()
        self.assertEqual(comment.text, "Bob's")

    def test_staff_can_delete_but_not_edit_others(self):
        comment = Comment.objects.create(user=self.bob, media=self.item, text="Bob's")
        self.client.force_login(self.staff)
        edit_url = reverse("media_library:comment_edit", args=[comment.pk])
        self.assertEqual(self.client.post(edit_url, {"text": "Changed"}).status_code, 403)
        self.client.post(reverse("media_library:comment_delete", args=[comment.pk]))
        self.assertEqual(Comment.objects.count(), 0)

    def test_hidden_comments_not_displayed(self):
        Comment.objects.create(user=self.bob, media=self.item, text="Rude words", is_hidden=True)
        page = self.client.get(self.item.get_absolute_url())
        self.assertNotContains(page, "Rude words")

    def test_cannot_comment_on_private_media_of_others(self):
        private = self.make_item(title="Hidden", visibility="private", file=png_upload("h.png"))
        self.client.force_login(self.bob)
        url = reverse("media_library:comment_add", args=[private.slug])
        self.assertEqual(self.client.post(url, {"text": "Hello there"}).status_code, 404)


# ---------------------------------------------------------------------------
# Contact form
# ---------------------------------------------------------------------------
class ContactTests(MediaTestCase):
    def test_valid_message_saved(self):
        response = self.client.post(
            reverse("media_library:contact"),
            {
                "name": "Carol",
                "email": "carol@example.com",
                "subject": "Hello",
                "message": "This is a long enough message.",
            },
        )
        self.assertRedirects(response, reverse("media_library:contact"))
        saved = ContactMessage.objects.get()
        self.assertEqual(saved.name, "Carol")
        self.assertFalse(saved.is_reviewed)

    def test_success_message_does_not_claim_email_sent(self):
        response = self.client.post(
            reverse("media_library:contact"),
            {
                "name": "Carol",
                "email": "carol@example.com",
                "subject": "Hello",
                "message": "This is a long enough message.",
            },
            follow=True,
        )
        self.assertContains(response, "was saved")
        self.assertNotContains(response, "email was sent")

    def test_invalid_message_rejected(self):
        response = self.client.post(
            reverse("media_library:contact"),
            {"name": "C", "email": "not-an-email", "subject": "Hi", "message": "short"},
        )
        self.assertEqual(response.status_code, 200)
        errors = response.context["form"].errors
        self.assertTrue(errors.get("email"))
        self.assertTrue(errors.get("message"))
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_contact_requires_csrf(self):
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        response = strict.post(
            reverse("media_library:contact"),
            {"name": "Carol", "email": "c@example.com", "subject": "Hi", "message": "long enough message"},
        )
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
class AdminTests(MediaTestCase):
    def test_admin_requires_staff(self):
        url = reverse("admin:media_library_mediaitem_changelist")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_staff_can_open_admin_changelists(self):
        self.make_item()
        self.client.force_login(self.staff)
        for model in ("category", "mediaitem", "favorite", "comment", "contactmessage"):
            url = reverse(f"admin:media_library_{model}_changelist")
            self.assertEqual(self.client.get(url).status_code, 200, model)

    def test_staff_can_open_media_change_form(self):
        item = self.make_item()
        self.client.force_login(self.staff)
        url = reverse("admin:media_library_mediaitem_change", args=[item.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
