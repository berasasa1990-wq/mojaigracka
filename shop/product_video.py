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


def browser_video(upload):
    """Normalize an uploaded clip to silent H.264 MP4 with fast-start metadata."""
    import subprocess
    import tempfile
    import uuid
    from pathlib import Path
    from django.core.files.base import ContentFile
    import imageio_ffmpeg

    validate_product_video(upload)
    try:
        with tempfile.TemporaryDirectory(prefix='product-video-') as directory:
            source = Path(directory) / 'input.mov'
            target = Path(directory) / 'output.mp4'
            with source.open('wb') as output:
                for chunk in upload.chunks():
                    output.write(chunk)
            subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error',
                '-i', str(source), '-map', '0:v:0', '-t', '5', '-an',
                '-vf', "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '24',
                '-pix_fmt', 'yuv420p', '-threads', '1', '-movflags', '+faststart',
                str(target),
            ], check=True, capture_output=True, timeout=60)
            data = target.read_bytes()
            if not data or len(data) > 20_000_000:
                raise ValueError
            return ContentFile(data, name=f'{uuid.uuid4().hex}.mp4')
    except (subprocess.SubprocessError, OSError, ValueError, RuntimeError):
        raise ValidationError('Video nije moguće pretvoriti. Pokušajte s drugim MOV ili MP4 fajlom.') from None
    finally:
        upload.seek(0)
