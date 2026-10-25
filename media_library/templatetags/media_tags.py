from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """
    Build a query string from the current request's GET parameters, updating or
    removing the given keys. Used so pagination links preserve active filters.

        {% qs page=3 %}   ->  ?q=cats&type=image&page=3
    """
    request = context["request"]
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"
