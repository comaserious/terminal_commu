import re
import unicodedata


_GENERIC_ALT = frozenset({"image", "img", "photo", "picture", "이미지", "사진"})
_IMAGE_FILENAME = re.compile(
    r".+\.(?:jpe?g|png|gif|webp|avif|svg)(?:[?#].*)?",
    re.IGNORECASE,
)
_HEX_IDENTIFIER = re.compile(r"[0-9a-f]{16,}", re.IGNORECASE)
_ENCODED_IDENTIFIER = re.compile(r"[A-Za-z0-9+/_=-]{24,}")
_URL_ADDRESS = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _normalize_alt(value: str) -> str:
    without_controls = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in value
    )
    return " ".join(without_controls.split())


def meaningful_image_alt(value: object, *, limit: int = 40) -> str | None:
    if not isinstance(value, str):
        return None
    if limit < 1:
        raise ValueError("limit must be positive")

    normalized = _normalize_alt(value)
    folded = normalized.casefold()
    if not normalized or folded in _GENERIC_ALT:
        return None
    if _URL_ADDRESS.search(normalized):
        return None
    if _IMAGE_FILENAME.fullmatch(normalized):
        return None
    if (
        "alt-hash" in folded
        or _HEX_IDENTIFIER.fullmatch(normalized)
        or _ENCODED_IDENTIFIER.fullmatch(normalized)
    ):
        return None
    if len(normalized) > limit:
        return f"{normalized[:limit]}…"
    return normalized


def image_placeholder(value: object) -> str:
    description = meaningful_image_alt(value)
    if description is None:
        return "[Image]"
    return f"[Image: {description}]"
