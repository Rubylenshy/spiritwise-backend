"""
Cloudflare R2 utility functions.
All audio file operations go through here.
"""
import io
import uuid
import os
import boto3
from botocore.config import Config
from django.conf import settings


def get_r2_client():
    """Return a configured boto3 S3 client pointing at Cloudflare R2."""
    return boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        region_name='auto',
        config=Config(signature_version='s3v4'),
    )


def upload_audio(file_obj, original_filename: str, sermon_title: str = '') -> dict:
    """
    Upload an audio file to R2.
    Returns { key, public_url, size }
    """
    ext = os.path.splitext(original_filename)[1].lower() or '.mp3'
    unique_name = f'{uuid.uuid4().hex}{ext}'
    key = f'sermons/{unique_name}'

    content_type_map = {
        '.mp3':  'audio/mpeg',
        '.m4a':  'audio/mp4',
        '.aac':  'audio/aac',
        '.ogg':  'audio/ogg',
        '.opus': 'audio/ogg',
        '.wav':  'audio/wav',
        '.flac': 'audio/flac',
    }
    content_type = content_type_map.get(ext, 'audio/mpeg')

    client = get_r2_client()

    # Reset file position to start before reading
    file_obj.seek(0)

    client.upload_fileobj(
        file_obj,
        settings.AWS_STORAGE_BUCKET_NAME,
        key,
        ExtraArgs={
            'ContentType': content_type,
            'Metadata': {'sermon_title': sermon_title[:255] if sermon_title else ''},
        },
    )

    public_url = build_public_url(key)

    return {
        'key': key,
        'public_url': public_url,
        'size': file_obj.tell(),
    }


def build_public_url(key: str) -> str:
    """Build the public CDN URL for a given R2 object key."""
    domain = settings.AWS_S3_CUSTOM_DOMAIN.rstrip('/')
    if not domain.startswith('http'):
        domain = f'https://{domain}'
    return f'{domain}/{key}'


def delete_audio(key: str) -> bool:
    """Delete an audio file from R2 by its key."""
    try:
        client = get_r2_client()
        client.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
        return True
    except Exception:
        return False


def get_object_range(key: str, start: int, end: int) -> tuple:
    """
    Fetch a byte range from R2.
    Returns (content_bytes, content_type, total_size)
    """
    client = get_r2_client()
    range_header = f'bytes={start}-{end}'

    response = client.get_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
        Key=key,
        Range=range_header,
    )

    content = response['Body'].read()
    content_type = response.get('ContentType', 'audio/mpeg')

    # ContentRange format: "bytes start-end/total"
    content_range = response.get('ContentRange', f'bytes {start}-{end}/*')
    total_size = content_range.split('/')[-1]
    try:
        total_size = int(total_size)
    except ValueError:
        total_size = end + 1

    return content, content_type, total_size


class _R2ObjectReader(io.RawIOBase):
    """Seekable, read-only view of an R2 object — every read is a ranged GET."""

    def __init__(self, key: str):
        self.name = key  # lets mutagen use the extension when sniffing the format
        self._key = key
        self._client = get_r2_client()
        head = self._client.head_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
        self._size = head['ContentLength']
        self._pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self._size}[whence]
        self._pos = max(0, base + offset)
        return self._pos

    def readinto(self, buffer):
        if self._pos >= self._size or not len(buffer):
            return 0
        end = min(self._pos + len(buffer), self._size) - 1
        data = self._client.get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=self._key,
            Range=f'bytes={self._pos}-{end}',
        )['Body'].read()
        buffer[:len(data)] = data
        self._pos += len(data)
        return len(data)


def open_object(key: str, buffer_size: int = 256 * 1024):
    """
    Open an R2 object as a seekable file without downloading it.
    Reads are fetched in `buffer_size` chunks on demand, so tag/duration parsing
    touches a few hundred KB instead of the whole file. Raises
    botocore ClientError (404) if the key doesn't exist.
    """
    return io.BufferedReader(_R2ObjectReader(key), buffer_size=buffer_size)


def get_object_metadata(key: str) -> dict:
    """Get file size and content type without downloading the file."""
    client = get_r2_client()
    response = client.head_object(
        Bucket=settings.AWS_STORAGE_BUCKET_NAME,
        Key=key,
    )
    return {
        'size': response['ContentLength'],
        'content_type': response.get('ContentType', 'audio/mpeg'),
    }
