"""
Compatibility shim for deprecated imghdr module on Python 3.13.

Thư viện python-telegram-bot chỉ gọi imghdr.what(), nên mình làm
một bản đơn giản đủ dùng.
"""

import mimetypes
from pathlib import Path
from typing import Optional, Union


def what(file: Union[str, Path, None], h: bytes | None = None) -> Optional[str]:
    """
    Trả về loại ảnh ('jpeg', 'png', 'gif', ...) dựa trên đuôi file.
    Nếu không đoán được thì trả về None.
    """
    if file is None:
        return None

    path = Path(file)
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("image/"):
        return mime.split("/", 1)[1]  # "image/jpeg" -> "jpeg"
    return None
