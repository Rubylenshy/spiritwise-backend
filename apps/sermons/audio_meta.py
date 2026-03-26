"""
Audio metadata extraction using mutagen.
Handles MP3 (ID3), MP4/M4A/AAC, OGG, OPUS, FLAC, WAV.
"""
import io
from mutagen import File as MutagenFile
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus


def extract_metadata(file_obj) -> dict:
    """
    Extract all useful metadata from an audio file.

    Returns:
    {
        'duration_seconds': int,
        'title': str,
        'artist': str,        # maps to speaker
        'album': str,         # maps to series title hint
        'date': str,          # YYYY or YYYY-MM-DD
        'comment': str,       # maps to description
        'cover_art': bytes | None,
        'cover_mime': str | None,
    }
    """
    file_obj.seek(0)
    result = {
        'duration_seconds': 0,
        'title': '',
        'artist': '',
        'album': '',
        'date': '',
        'comment': '',
        'cover_art': None,
        'cover_mime': None,
    }

    try:
        audio = MutagenFile(file_obj, easy=False)
        if audio is None:
            return result

        # ── Duration ─────────────────────────────────────────────────────────
        if hasattr(audio, 'info') and hasattr(audio.info, 'length'):
            result['duration_seconds'] = int(audio.info.length)

        # ── MP3 (ID3 tags) ────────────────────────────────────────────────────
        if hasattr(audio, 'tags') and audio.tags:
            tags = audio.tags

            # ID3 tags (MP3)
            if hasattr(tags, 'getall'):
                result['title']   = _id3_text(tags, 'TIT2')
                result['artist']  = _id3_text(tags, 'TPE1')
                result['album']   = _id3_text(tags, 'TALB')
                result['date']    = _id3_text(tags, 'TDRC') or _id3_text(tags, 'TYER')
                result['comment'] = _id3_text(tags, 'COMM')

                # Cover art (APIC frame)
                apic_frames = tags.getall('APIC')
                if apic_frames:
                    apic = apic_frames[0]
                    result['cover_art'] = apic.data
                    result['cover_mime'] = apic.mime or 'image/jpeg'

            # MP4/M4A tags
            elif isinstance(tags, dict):
                result['title']   = _mp4_text(tags, '\xa9nam')
                result['artist']  = _mp4_text(tags, '\xa9ART')
                result['album']   = _mp4_text(tags, '\xa9alb')
                result['date']    = _mp4_text(tags, '\xa9day')
                result['comment'] = _mp4_text(tags, '\xa9cmt')

                # Cover art (covr atom)
                if 'covr' in tags and tags['covr']:
                    cover = tags['covr'][0]
                    result['cover_art'] = bytes(cover)
                    result['cover_mime'] = 'image/jpeg'  # MP4 cover is usually JPEG

        # ── FLAC ─────────────────────────────────────────────────────────────
        if isinstance(audio, FLAC):
            vc = audio.tags or {}
            result['title']   = _vc_text(vc, 'title')
            result['artist']  = _vc_text(vc, 'artist')
            result['album']   = _vc_text(vc, 'album')
            result['date']    = _vc_text(vc, 'date')
            result['comment'] = _vc_text(vc, 'comment')
            if audio.pictures:
                pic = audio.pictures[0]
                result['cover_art'] = pic.data
                result['cover_mime'] = pic.mime or 'image/jpeg'

        # ── OGG Vorbis / Opus ─────────────────────────────────────────────────
        if isinstance(audio, (OggVorbis, OggOpus)):
            tags = audio.tags or {}
            result['title']   = _vc_text(tags, 'title')
            result['artist']  = _vc_text(tags, 'artist')
            result['album']   = _vc_text(tags, 'album')
            result['date']    = _vc_text(tags, 'date')
            result['comment'] = _vc_text(tags, 'comment')

    except Exception:
        pass  # Never crash on metadata — just return what we have

    return result


def _id3_text(tags, key: str) -> str:
    frames = tags.getall(key)
    if not frames:
        return ''
    frame = frames[0]
    if hasattr(frame, 'text') and frame.text:
        return str(frame.text[0]).strip()
    if hasattr(frame, 'desc'):
        # COMM frame
        texts = tags.getall(key)
        for t in texts:
            if hasattr(t, 'text') and t.text:
                return str(t.text[0]).strip()
    return ''


def _mp4_text(tags: dict, key: str) -> str:
    val = tags.get(key)
    if val and isinstance(val, list) and val[0]:
        return str(val[0]).strip()
    return ''


def _vc_text(tags, key: str) -> str:
    val = tags.get(key.lower()) or tags.get(key.upper())
    if val and isinstance(val, list):
        return str(val[0]).strip()
    return ''
