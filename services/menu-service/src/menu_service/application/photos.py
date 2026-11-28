from io import BytesIO
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError

PhotoKind = Literal["menu", "detail"]
MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTO_PIXELS = 24_000_000
MAX_PHOTO_EDGE: dict[PhotoKind, int] = {"menu": 960, "detail": 1920}


class InvalidPhoto(ValueError):
    pass


def prepare_photo(data: bytes, kind: PhotoKind) -> bytes:
    """Decode and re-encode one static raster image without uploaded metadata."""
    try:
        with Image.open(BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as image:
            if image.width * image.height > MAX_PHOTO_PIXELS:
                raise InvalidPhoto("Размер изображения должен быть не больше 24 мегапикселей.")
            if getattr(image, "is_animated", False):
                raise InvalidPhoto("Выберите обычное фото без анимации.")
            photo = ImageOps.exif_transpose(image)
            mode = "RGBA" if "A" in photo.getbands() or "transparency" in photo.info else "RGB"
            photo = photo.convert(mode)
            photo.info.clear()
            edge = MAX_PHOTO_EDGE[kind]
            photo.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            result = BytesIO()
            photo.save(result, format="WEBP", quality=85)
            return result.getvalue()
    except InvalidPhoto:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
        raise InvalidPhoto("Выберите исправный файл JPEG, PNG или WebP.") from error
