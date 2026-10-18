"""Admin forms — mostly one fix, and it is worth the file.

`Article.tags` is a `JSONField`. Django renders those as a raw textarea that
demands valid JSON, so writing an article meant typing

    ["بازاریابی", "اینستاگرام"]

with the brackets, the quotes and the commas in the right places, in a
right-to-left box where a stray bracket is hard to even see. Get one wrong and
the admin refuses to save the whole article — not the tags, the article.

Nobody writing a blog post should be typing JSON. The tags are a list of words;
the form asks for a list of words.

The stored shape does not change, so the API, the tag pages and the existing
rows all keep working.
"""
import json

from django import forms

from .models import Article


class TagsField(forms.CharField):
    """A list of words, comma-separated, stored as a JSON list."""

    widget = forms.TextInput(attrs={"dir": "auto", "style": "width: 100%"})

    def prepare_value(self, value):
        # Comes back as a list from the model, and as a string when the form is
        # re-rendered after a validation error somewhere else on the page.
        if isinstance(value, (list, tuple)):
            return "، ".join(str(v) for v in value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    return "، ".join(str(v) for v in json.loads(stripped))
                except ValueError:
                    return value
        return value

    def clean(self, value):
        text = super().clean(value) or ""
        # Both commas, because a Persian keyboard gives «،» and an English one
        # gives «,» — and the person typing should not have to care which.
        parts = text.replace("،", ",").split(",")
        out: list[str] = []
        for part in parts:
            tag = part.strip()[:40]
            if tag and tag not in out:
                out.append(tag)
        return out[:12]


class ArticleForm(forms.ModelForm):
    tags = TagsField(
        required=False,
        label="برچسب‌ها",
        help_text="با ویرگول جدا کنید — مثلاً: بازاریابی، اینستاگرام، هوش مصنوعی",
    )

    class Meta:
        model = Article
        fields = "__all__"
