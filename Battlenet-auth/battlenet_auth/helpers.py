import re

_INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')
_FORM_RE = re.compile(r'<form\b[^>]*\baction\s*=\s*"([^"]*)"', re.I)
_CHALLENGE_RE = re.compile(r"/challenge/([0-9a-fA-F-]{16,})")
_ERROR_RES = (
    re.compile(r"error-message-heading[^>]*>([^<]+)<"),
    re.compile(r'"error_message"\s*:\s*"([^"]+)"'),
    re.compile(r'id="display-errors"[^>]*>\s*<[^>]+>([^<]+)<'),
)


def form_inputs(html):
    return [
        {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
        for tag in _INPUT_RE.findall(html)
    ]


def form_field(html, name, default=""):
    for tag in form_inputs(html):
        if tag.get("name") == name or tag.get("id") == name:
            return tag.get("value", default)
    return default


def srp_enabled(html):
    return form_field(html, "srpEnabled", "false").strip().lower() == "true"


def challenge_id(text):
    found = _CHALLENGE_RE.search(text)
    return found.group(1) if found else None


def form_action(html):
    return _FORM_RE.search(html)


def is_redirect(res):
    return res.status_code in (301, 302, 303, 307, 308)


def location(res):
    return res.headers.get("location")


def error_text(html):
    for pattern in _ERROR_RES:
        found = pattern.search(html)
        if found:
            return found.group(1).strip()
    return ""
