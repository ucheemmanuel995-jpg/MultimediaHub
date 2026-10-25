from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Comment, ContactMessage, MediaItem, MediaType

User = get_user_model()


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text="Used for account recovery notices.")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class ProfileForm(forms.ModelForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        clash = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("Another account already uses this email.")
        return email


class MediaForm(forms.ModelForm):
    """
    Create/edit form for media.

    On edit the media type is locked: switching a stored image to "video"
    without replacing the file would leave the record inconsistent. To change
    type, upload a new item. A new file uploaded during edit is validated
    against the existing type, and the old file is removed after a successful
    save.
    """

    class Meta:
        model = MediaItem
        fields = [
            "title",
            "description",
            "media_type",
            "category",
            "artist",
            "file",
            "thumbnail",
            "visibility",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "file": forms.FileInput(attrs={"data-preview-target": "file-preview"}),
            "thumbnail": forms.FileInput(
                attrs={"data-preview-target": "thumb-preview", "accept": "image/*"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_edit = bool(self.instance and self.instance.pk)
        self._old_file_name = self.instance.file.name if self.is_edit else ""
        self._old_thumb_name = self.instance.thumbnail.name if self.is_edit else ""
        self.fields["category"].required = False
        self.fields["category"].empty_label = "No category"
        if self.is_edit:
            self.fields["media_type"].disabled = True
            self.fields["media_type"].help_text = (
                "The type cannot be changed after upload. Upload a new item instead."
            )
            self.fields["file"].help_text = (
                "Leave empty to keep the current file, or choose a replacement of the same type."
            )
        else:
            self.fields["file"].help_text = (
                "Images: JPG, PNG, GIF, WebP. Video: MP4 (H.264) recommended, WebM. "
                "Audio: MP3, WAV, OGG."
            )

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if len(title) < 2:
            raise forms.ValidationError("Please enter a descriptive title.")
        return title

    def save(self, commit=True):
        instance = self.instance
        file_replaced = (
            self.is_edit and instance.file.name and instance.file.name != self._old_file_name
        )
        if (
            file_replaced
            and instance.media_type == MediaType.IMAGE
            and "thumbnail" not in self.files
        ):
            # Force a fresh auto-generated thumbnail for the replacement image.
            instance.thumbnail = None
        item = super().save(commit=commit)
        if commit:
            self._cleanup_old_files(item)
        return item

    def _cleanup_old_files(self, item):
        if not self.is_edit:
            return
        for old_name, current in (
            (self._old_file_name, item.file.name),
            (self._old_thumb_name, item.thumbnail.name if item.thumbnail else ""),
        ):
            if old_name and old_name != current:
                try:
                    item.file.storage.delete(old_name)
                except Exception:  # pragma: no cover - best effort cleanup
                    pass


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["text"]
        widgets = {
            "text": forms.Textarea(
                attrs={"rows": 3, "maxlength": 1000, "placeholder": "Add a comment…"}
            )
        }
        labels = {"text": "Comment"}

    def clean_text(self):
        text = self.cleaned_data["text"].strip()
        if len(text) < 2:
            raise forms.ValidationError("Comments must be at least 2 characters long.")
        if len(text) > 1000:
            raise forms.ValidationError("Comments are limited to 1000 characters.")
        return text


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ["name", "email", "subject", "message"]
        widgets = {
            "message": forms.Textarea(attrs={"rows": 6, "maxlength": 3000}),
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if len(name) < 2:
            raise forms.ValidationError("Please enter your name.")
        return name

    def clean_message(self):
        message = self.cleaned_data["message"].strip()
        if len(message) < 10:
            raise forms.ValidationError("Your message must be at least 10 characters long.")
        if len(message) > 3000:
            raise forms.ValidationError("Your message is limited to 3000 characters.")
        return message
