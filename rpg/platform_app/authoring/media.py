"""Cover bytes use a closed set of image signatures and private storage."""
import hashlib


def image_extension(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("封面仅支持 PNG、JPEG、WebP")


def store_cover(uid, data):
    from platform_app.storage import store_bytes
    extension = image_extension(data)
    _, url = store_bytes(data, kind=f"authoring/{uid}", filename=hashlib.sha256(data).hexdigest() + extension)
    return url
