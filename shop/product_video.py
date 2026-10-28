"""Validate bounded MP4/MOV uploads without an external video process."""
import struct
from django.core.exceptions import ValidationError


def validate_product_video(file):
    if not file:
        return
    if file.size > 20_000_000:
        raise ValidationError('Video može imati najviše 20 MB.')
    try:
        file.seek(0)
        data = file.read(20_000_001)
        if len(data) > 20_000_000 or not file.name.lower().endswith(('.mp4', '.mov')):
            raise ValueError
        def atoms(start, end):
            while start + 8 <= end:
                size, kind = struct.unpack_from('>I4s', data, start)
                header = 8
                if size == 1:
                    size = struct.unpack_from('>Q', data, start + 8)[0]
                    header = 16
                elif size == 0:
                    size = end - start
                if size < header or start + size > end:
                    raise ValueError
                yield kind, start + header, start + size
                start += size
        duration = None
        for kind, begin, end in atoms(0, len(data)):
            if kind != b'moov':
                continue
            for child, pos, stop in atoms(begin, end):
                if child == b'mvhd':
                    version = data[pos]
                    if version == 0 and stop - pos >= 20:
                        scale, ticks = struct.unpack_from('>II', data, pos + 12)
                    elif version == 1 and stop - pos >= 32:
                        scale, ticks = struct.unpack_from('>IQ', data, pos + 20)
                    else:
                        raise ValueError
                    duration = ticks / scale
        if duration is None or not 0 < duration <= 5.05:
            raise ValueError
    except (ValueError, ZeroDivisionError, struct.error, IndexError):
        raise ValidationError('Odaberite ispravan MP4 ili MOV video trajanja do 5 sekundi.') from None
    finally:
        file.seek(0)
