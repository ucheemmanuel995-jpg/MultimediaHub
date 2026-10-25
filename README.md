# MultimediaHub

A full-stack multimedia discovery, streaming and media-management website built with **Django**, **PostgreSQL**, Django Templates, HTML5, CSS3 and vanilla JavaScript.

## Features

- Browse **images, videos and audio** with search, category filter, sorting and pagination (state is preserved in pagination links).
- Image gallery with auto-generated thumbnails and an accessible full-size viewer (native `<dialog>`).
- Native HTML5 video and audio players (no autoplay), related media, view counts.
- Registration, login, logout (POST + CSRF), profile editing, password change.
- Upload, edit and delete your own media; public or private visibility.
- **Private media is protected**: files are never served from a public URL. Every file and thumbnail goes through an authorisation view; HTTP Range requests are supported so seeking works.
- Favorites (database backed, unique per user/media) and comments (edit/delete own, staff can delete, hide via admin).
- Personal dashboard with statistics computed from the database; "My media" with search, type and visibility filters.
- Contact form saved to the database (no email is claimed or sent), About, Privacy and Terms pages (starter text — needs legal review).
- Django Admin for categories, media, favorites, comments and contact messages.

## Technology

Python 3.12 · Django 5.2 · PostgreSQL (psycopg 3) · Pillow · python-dotenv · no frontend framework.

## Folder structure

```
MultimediaHub/
├── manage.py
├── requirements.txt
├── .env.example          # placeholders only; copy to .env
├── .env.production.example
├── Dockerfile
├── compose.yaml
├── config/               # settings, root urls, wsgi/asgi
├── media_library/        # the app
│   ├── models.py         # Category, MediaItem, Favorite, Comment, ContactMessage
│   ├── validators.py     # content-based upload validation
│   ├── forms.py  views.py  urls.py  admin.py  utils.py  tests.py
│   ├── migrations/0001_initial.py
│   ├── templatetags/media_tags.py
│   ├── templates/media_library/   # all pages + partials (_*.html)
│   └── static/media_library/{css,js,images}
└── uploads/              # user uploads (git-ignored, never publicly routed)
```

## Setup (Windows)

All commands are for **Command Prompt** in `C:\Users\OPERA\Desktop\MultimediaHub`.

1. **Activate your environment**
   ```
   C:\pythonDevEnvs\data_env\Scripts\activate.bat
   ```
2. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```
3. **Create the PostgreSQL database** (once). Using `psql`:
   ```
   psql -U postgres -c "CREATE DATABASE multimediahub_db;"
   ```
   (or create it in pgAdmin). The app never drops or recreates databases.
4. **Configure environment variables**
   ```
   copy .env.example .env
   ```
   Edit `.env` and set a real `SECRET_KEY` and your `DB_PASSWORD`. Generate a key with:
   ```
   python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
   ```
   `.env` is git-ignored. Never commit it.
5. **Verify the build**
   ```
   python manage.py check
   python manage.py makemigrations --check --dry-run
   python manage.py migrate
   python manage.py test
   ```
   - `makemigrations --check` should report *No changes detected*. If it reports changes (the migration was hand-written), run `python manage.py makemigrations` and keep the generated file.
   - The test run creates and destroys its own `test_multimediahub_db` database, so the PostgreSQL user needs the `CREATEDB` privilege. Use a separate test database/user in shared environments.
6. **Create an administrator**
   ```
   python manage.py createsuperuser
   ```
7. **Run the development server**
   ```
   python manage.py runserver
   ```
   - Site: http://127.0.0.1:8000/
   - Admin: http://127.0.0.1:8000/admin/

## Using the site

1. Log in to Django Admin and create a few **Categories** (optional but recommended).
2. Register a normal account (or use your superuser) and click **Upload**.
3. Choose type, file, category and visibility. Supported formats:
   - Images: JPG, PNG, GIF, WebP (max 10 MB)
   - Video: MP4 (H.264/AAC recommended for compatibility), WebM, OGV (max 200 MB)
   - Audio: MP3, WAV, OGG (max 50 MB)
   Limits are configurable with `MAX_IMAGE_SIZE_MB`, `MAX_VIDEO_SIZE_MB`, `MAX_AUDIO_SIZE_MB` in `.env`.
4. Mark an item **Featured** in Django Admin to show it on the homepage.

Notes:
- The media type is locked after upload (changing it would leave the stored file inconsistent). Upload a new item instead.
- Replacing a file on the edit page deletes the old file and (for images) regenerates the thumbnail.
- Videos are **not transcoded**. A file with a valid container that the browser can't decode shows the fallback message with a download link.
- Validation checks size, extension and file signature (and fully decodes images with Pillow). It cannot prove the streams inside a video/audio file are well-formed.

## Security measures

CSRF protection on all state-changing forms (no `csrf_exempt`), POST-only logout/favorite/delete, backend ownership checks (403/404), private media delivered only through an authorised view, random server-side filenames, content-based upload validation, SVG uploads rejected, size limits, Django password validation, auto-escaped templates (no `|safe`), open-redirect-safe `next` handling, secrets and DB credentials from environment variables, hardened cookie/HSTS/SSL settings when `DEBUG=False`.

## Production considerations

- Copy `.env.production.example` to `.env.production` and replace the domain, Django secret and database password placeholders. Keep this file outside source control.
- Point both the apex domain and its `www` hostname to the Docker host and allow inbound TCP ports 80 and 443 (plus UDP 443 for HTTP/3). Set `DOMAIN` in `.env.production`; match `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` to the domain(s) you will serve.
- Deploy with Docker Compose: `docker compose --env-file .env.production build web`, then start PostgreSQL with `docker compose --env-file .env.production up -d db`. Run `docker compose --env-file .env.production run --rm web python manage.py migrate --noinput` and `docker compose --env-file .env.production run --rm web python manage.py collectstatic --noinput`, then start the application and Caddy proxy with `docker compose --env-file .env.production up -d`.
- Caddy automatically provisions TLS certificates for `DOMAIN` and proxies HTTPS traffic to the app. Keep `USE_X_FORWARDED_PROTO=True` only with this trusted proxy (or another proxy that overwrites `X-Forwarded-Proto` with the actual scheme).
- WhiteNoise serves collected static assets. The named Compose volumes persist PostgreSQL data and user uploads. Back up both. Never expose `/uploads/` as a static web-server alias: media authorization must pass through Django.
- If using a managed PostgreSQL service instead of the Compose database, set `DB_HOST`, `DB_PORT`, `DB_SSLMODE=require` (if required by the provider), and supply the credentials through the hosting platform's secret manager.
- Raise the reverse proxy's request-body limit to accommodate your configured upload limits. For high traffic or large media libraries, consider object storage and signed URLs or an X-Accel-Redirect/X-Sendfile approach.
- Back up the database and `uploads/` together.
- Have the Privacy and Terms pages reviewed by a qualified professional.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ImproperlyConfigured: SECRET_KEY ...` | Create `.env` (local) or configure the required `SECRET_KEY` in the deployment environment. |
| `password authentication failed` / `could not connect` | Check `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` and `DB_SSLMODE`; confirm PostgreSQL is reachable from the app container. |
| `database "multimediahub_db" does not exist` | Create it (step 3). |
| `permission denied to create database` when testing | Grant `CREATEDB` to the DB user. |
| Video won't play | Re-encode to MP4 (H.264 + AAC). |
| Uploads rejected as "too large" | Raise the matching `MAX_*_SIZE_MB` value (and any proxy limit). |

## Known limitations

- No email sending (contact messages are stored for admin review).
- No video transcoding or video thumbnail extraction (upload an optional thumbnail instead).
- Admin-side file replacement does not remove the old file (use the site's edit page, which does).
- No public user profile pages; uploader names are shown as text.
