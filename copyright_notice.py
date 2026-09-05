"""Consistent attribution for Discord messages and embed footers."""
COPYRIGHT = "© Ariee-Everlook"


def without_copyright(value):
    return str(value or "").removesuffix("\n" + COPYRIGHT).removesuffix(COPYRIGHT).rstrip()


def copyright_text(value=None, limit=2000):
    text = without_copyright(value)
    suffix = "\n" + COPYRIGHT if text else COPYRIGHT
    available = limit - len(suffix)
    if len(text) > available:
        text = text[:available - 1].rstrip() + "…"
    return text + suffix
