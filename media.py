"""Bounded raster attachments. No arbitrary paths or active document formats served."""
import base64
import hashlib
import io
import re
import warnings
from pathlib import Path
from PIL import Image

MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
MAX_IMAGES = 4
MAX_AUDIO = 2
MAX_AUDIO_FILE = 10 * 1024 * 1024
AUDIO_SECONDS = 300
FORMATS = {'PNG': ('png', 'image/png'), 'JPEG': ('jpg', 'image/jpeg'),
           'GIF': ('gif', 'image/gif'), 'WEBP': ('webp', 'image/webp')}
MEDIA_PATH = re.compile(r'/media/([a-f0-9]{64}\.(?:png|jpg|gif|webp|mp3|wav|m4a|ogg))\Z')
IMAGE_TAG = re.compile(r'\[\[ROOM_IMAGE:([^\r\n]*?)\]\]')
AUDIO_TAG = re.compile(r'\[\[ROOM_AUDIO:([^\r\n]*?)\]\]')
AUDIO_SUFFIX = {'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'm4a': 'audio/mp4', 'ogg': 'audio/ogg'}
AUDIO_MIME_SUFFIX = {mime: suffix for suffix, mime in AUDIO_SUFFIX.items()}


def sniff_audio(raw):
    """Reject short header-only fakes: require container structure or MP3 frame sync."""
    if len(raw) < 26:
        return None
    if raw[:4] == b'RIFF' and raw[8:12] == b'WAVE':
        head = raw[:65536]
        if b'fmt ' in head and b'data' in head:
            return 'wav'
        return None
    if raw[:4] == b'OggS' and raw[4] == 0 and len(raw) >= 28:
        return 'ogg'
    if raw[4:8] == b'ftyp' and int.from_bytes(raw[0:4], 'big') >= 8:
        if b'moov' in raw or b'mdat' in raw:
            return 'm4a'
        return None
    start = 10
    if raw[:3] == b'ID3':
        start = 10 + (((raw[6] & 0x7F) << 21) | ((raw[7] & 0x7F) << 14)
                      | ((raw[8] & 0x7F) << 7) | (raw[9] & 0x7F))
    frames = 0
    position = start
    limit = min(len(raw) - 4, start + 1_000_000)
    while position <= limit:
        if raw[position] == 0xFF and (raw[position + 1] & 0xE0) == 0xE0:
            version = (raw[position + 1] >> 3) & 0x03
            layer = (raw[position + 1] >> 1) & 0x03
            bitrate = (raw[position + 2] >> 4) & 0x0F
            sample = (raw[position + 2] >> 2) & 0x03
            if version != 1 and layer != 0 and bitrate not in (0, 15) and sample != 3:
                frames += 1
                if frames >= 2:
                    return 'mp3'
                position += 4
                continue
        position += 1
    return None


class MediaStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()

    def prepare(self, raw, name='图片'):
        if not raw or len(raw) > MAX_FILE:
            raise ValueError('每张图片须为1字节至8 MB。')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    fmt = image.format
                    if fmt not in FORMATS: raise ValueError('支持 PNG、JPEG、GIF、WebP 图片。')
                    width, height = image.size
                    if width * height > 24_000_000: raise ValueError('图片分辨率不能超过2400万像素。')
                    frames = getattr(image, 'n_frames', 1)
                    if frames > 200 or width * height * frames > 80_000_000:
                        raise ValueError('动图过大，请使用更短或更小的表情。')
                    image.verify()
                # Verify decoded frames as well as the container/header.
                with Image.open(io.BytesIO(raw)) as image:
                    for frame in range(frames):
                        image.seek(frame); image.load()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ValueError('图片分辨率过大。') from exc
        except (OSError, SyntaxError, EOFError) as exc:
            raise ValueError('图片损坏或格式不支持。') from exc
        ext, mime = FORMATS[fmt]
        filename = hashlib.sha256(raw).hexdigest() + '.' + ext
        label = str(name).replace('\\', '/').rsplit('/', 1)[-1][:120] or '图片'
        meta = dict(kind='image', url='/media/' + filename, name=label, mime=mime,
                    width=width, height=height, bytes=len(raw))
        return meta, raw

    def prepare_audio(self, raw, name='音频'):
        if not raw or len(raw) > MAX_AUDIO_FILE:
            raise ValueError('每个音频须为1字节至10 MB。')
        ext = sniff_audio(raw)
        if not ext:
            raise ValueError('支持 MP3、WAV、M4A、OGG 音频。')
        filename = hashlib.sha256(raw).hexdigest() + '.' + ext
        label = str(name).replace('\\', '/').rsplit('/', 1)[-1][:120] or '音频'
        meta = dict(kind='audio', url='/media/' + filename, name=label,
                    mime=AUDIO_SUFFIX[ext], bytes=len(raw))
        return meta, raw

    def uploads_audio(self, values):
        if not isinstance(values, list) or len(values) > MAX_AUDIO:
            raise ValueError('每条消息最多2个音频。')
        prepared = []
        total = 0
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get('data'), str):
                raise ValueError('音频数据格式错误。')
            if len(item['data']) > (MAX_AUDIO_FILE + 2) // 3 * 4: raise ValueError('每个音频不能超过10 MB。')
            try: raw = base64.b64decode(item['data'], validate=True)
            except ValueError as exc: raise ValueError('音频编码错误。') from exc
            total += len(raw)
            if total > MAX_TOTAL: raise ValueError('每条消息的音频合计不能超过20 MB。')
            prepared.append(self.prepare_audio(raw, item.get('name', '音频')))
        return prepared

    def uploads(self, values):
        if not isinstance(values, list) or len(values) > MAX_IMAGES:
            raise ValueError('每条消息最多4张图片。')
        prepared = []
        total = 0
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get('data'), str):
                raise ValueError('图片数据格式错误。')
            if len(item['data']) > (MAX_FILE + 2) // 3 * 4: raise ValueError('每张图片不能超过8 MB。')
            try: raw = base64.b64decode(item['data'], validate=True)
            except ValueError as exc: raise ValueError('图片编码错误。') from exc
            total += len(raw)
            if total > MAX_TOTAL: raise ValueError('每条消息的图片合计不能超过20 MB。')
            prepared.append(self.prepare(raw, item.get('name', '图片')))
        return prepared

    def save(self, prepared):
        self.directory.mkdir(parents=True, exist_ok=True)
        result = []
        for meta, raw in prepared:
            path = self.directory / meta['url'].rsplit('/', 1)[-1]
            if not path.exists():
                # Content-addressed writes are idempotent; write complete bytes before publishing.
                import tempfile, os
                fd, temporary = tempfile.mkstemp(dir=self.directory, prefix='.pending-')
                try:
                    with os.fdopen(fd, 'wb') as output: output.write(raw)
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary): os.unlink(temporary)
            result.append(meta)
        return result

    def path(self, url):
        match = MEDIA_PATH.fullmatch(url)
        if not match: return None
        path = self.directory / match[1]
        if path.is_symlink() or path.resolve().parent != self.directory or not path.is_file(): return None
        return path

    def from_reply(self, text, roots):
        prepared = []; errors = []
        def take(kind):
            def inner(match):
                try:
                    path = Path(match[1].strip()).resolve(strict=True)
                    if not any(path.is_relative_to(Path(root).resolve()) for root in roots):
                        raise ValueError('文件须位于自己的目录或public目录。')
                    if not path.is_file(): raise ValueError('文件不存在。')
                    max_bytes=MAX_AUDIO_FILE if kind=='audio' else MAX_FILE
                    with path.open('rb') as source: raw=source.read(max_bytes+1)
                    if len(raw)>max_bytes: raise ValueError('文件超过大小限制。')
                    if kind == 'audio':
                        if len(prepared) >= MAX_AUDIO: raise ValueError('每条消息最多2个音频。')
                        if not path.is_file() or len(raw) > MAX_AUDIO_FILE: raise ValueError('音频不存在或超过10 MB。')
                        meta, payload = self.prepare_audio(raw, path.name)
                    else:
                        if sum(1 for p in prepared if p[0].get('kind') == 'image') >= MAX_IMAGES: raise ValueError('每条消息最多4张图片。')
                        if not path.is_file() or len(raw) > MAX_FILE: raise ValueError('图片不存在或超过8 MB。')
                        meta, payload = self.prepare(raw, path.name)
                    if sum(len(p[1]) for p in prepared) + len(raw) > MAX_TOTAL: raise ValueError('附件合计超过20 MB。')
                    prepared.append((meta, payload))
                except (OSError, ValueError) as exc:
                    errors.append(('音频' if kind == 'audio' else '图片') + '未发送：' + str(exc))
                return ''
            return inner
        clean = AUDIO_TAG.sub(take('audio'), text)
        clean = IMAGE_TAG.sub(take('image'), clean)
        # Never expose an unfinished control marker.
        for marker in ('[[ROOM_IMAGE:', '[[ROOM_AUDIO:'):
            clean = clean.split(marker, 1)[0]
        return (clean.strip() + ('\n' + '\n'.join(errors) if errors else '')).strip(), self.save(prepared)


def public_preview(text):
    for marker in ('[[ROOM_IMAGE:', '[[ROOM_AUDIO:'):
        text = text.split(marker, 1)[0]
    for marker in ('[[ROOM_IMAGE:', '[[ROOM_AUDIO:'):
        for length in range(len(marker) - 1, 0, -1):
            if text.endswith(marker[:length]): return text[:-length]
    return text
