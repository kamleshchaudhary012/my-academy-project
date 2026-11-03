import os
from PIL import Image
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}


def validate_image_file(value):
    """
    Validates uploaded image:
    1. Extension check (.jpg, .jpeg, .png, .webp).
    2. File size <= 5 MB.
    3. PIL image decoding verification (prevents disguised executables/scripts).
    """
    if not value:
        return

    # 1. Extension check
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError(
            _(f'Unsupported image format "{ext}". Allowed formats: JPG, JPEG, PNG, WebP.'),
            code='invalid_image_extension'
        )

    # 2. File size check
    file_size = getattr(value, 'size', None)
    if file_size and file_size > MAX_IMAGE_SIZE_BYTES:
        raise ValidationError(
            _(f'Image file size exceeds maximum limit of 5 MB (size: {file_size / (1024*1024):.2f} MB).'),
            code='image_too_large'
        )

    # 3. Decode verification via Pillow
    try:
        # Seek to start if file was previously read
        if hasattr(value, 'seek') and callable(value.seek):
            value.seek(0)
        img = Image.open(value)
        img.verify()
        if img.format not in ALLOWED_IMAGE_FORMATS:
            raise ValidationError(
                _(f'Invalid image content format "{img.format}". Allowed formats: JPG, JPEG, PNG, WebP.'),
                code='invalid_image_content'
            )
        # Reset file pointer for subsequent storage save
        if hasattr(value, 'seek') and callable(value.seek):
            value.seek(0)
    except Exception as e:
        if isinstance(e, ValidationError):
            raise e
        raise ValidationError(
            _('The uploaded file is not a valid or readable image.'),
            code='corrupt_image_file'
        )
