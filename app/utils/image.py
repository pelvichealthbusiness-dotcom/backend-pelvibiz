import io
from PIL import Image


def force_resolution(image_bytes: bytes, width: int = 1080, height: int = 1350) -> bytes:
    """Center-crop to target aspect ratio, then resize to exact dimensions."""
    img = Image.open(io.BytesIO(image_bytes))

    # Target aspect ratio
    target_ratio = width / height  # 0.8 for 4:5
    current_ratio = img.width / img.height

    if current_ratio > target_ratio:
        # Image is wider — crop sides
        new_width = int(img.height * target_ratio)
        offset = (img.width - new_width) // 2
        img = img.crop((offset, 0, offset + new_width, img.height))
    elif current_ratio < target_ratio:
        # Image is taller — crop top/bottom
        new_height = int(img.width / target_ratio)
        offset = (img.height - new_height) // 2
        img = img.crop((0, offset, img.width, offset + new_height))

    # Resize to exact dimensions
    img = img.resize((width, height), Image.LANCZOS)

    # Return as PNG bytes
    output = io.BytesIO()
    img.save(output, format="PNG", quality=95)
    return output.getvalue()
