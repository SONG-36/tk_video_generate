from io import BytesIO

from PIL import Image


def create_png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color=(245, 50, 85)).save(buffer, format="PNG")
    return buffer.getvalue()

