"""Validate bytes and parse in a killable, memory-limited isolated process."""
import io
import json
import os
from pathlib import Path, PurePosixPath
import signal
import subprocess
import sys
import tempfile
import zipfile

from app.security import resource_policy as p

TYPES = {'.txt': {'text/plain'}, '.md': {'text/plain', 'text/markdown'},
         '.pdf': {'application/pdf'},
         '.docx': {'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}}

def validate_document(content, filename, content_type=None):
    suffix = Path(filename).suffix.lower()
    if suffix not in TYPES:
        p.reject('UNSUPPORTED_MEDIA_TYPE', 415)
    mime = (content_type or '').split(';', 1)[0].strip().lower()
    if mime and mime not in TYPES[suffix] | {'application/octet-stream'}:
        p.reject('UNSUPPORTED_MEDIA_TYPE', 415)
    if len(content) > p.MAX_FILE_BYTES:
        p.reject('PAYLOAD_TOO_LARGE')
    if not content:
        p.reject('INVALID_DOCUMENT', 422)
    if suffix in {'.txt', '.md'}:
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            p.reject('INVALID_DOCUMENT', 422)
        if '\x00' in text or content.startswith((b'%PDF-', b'PK\x03\x04')):
            p.reject('INVALID_DOCUMENT', 422)
        p.guard_text(text, extracted=True)
    elif suffix == '.pdf':
        if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
            p.reject('INVALID_DOCUMENT', 422)
    else:
        validate_docx(content)
    return suffix

def validate_docx(content):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > p.MAX_DOCX_ENTRIES:
                p.reject('DOCUMENT_RESOURCE_LIMIT', 422)
            names = set()
            total = 0
            for info in entries:
                name = info.filename
                path = PurePosixPath(name)
                if (name in names or path.is_absolute() or '..' in path.parts or '\\' in name
                        or ':' in name or info.flag_bits & 1
                        or (info.external_attr >> 16) & 0o170000 == 0o120000
                        or path.suffix.lower() in {'.zip', '.docx', '.xlsx', '.pptx', '.rar', '.7z', '.gz', '.jar'}):
                    p.reject('INVALID_DOCUMENT', 422)
                names.add(name)
                total += info.file_size
                if (info.file_size > p.MAX_DOCX_SINGLE_ENTRY_BYTES
                        or total > p.MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES
                        or info.file_size / max(info.compress_size, 1) > p.MAX_DOCX_COMPRESSION_RATIO):
                    p.reject('DOCUMENT_RESOURCE_LIMIT', 422)
            if not {'[Content_Types].xml', 'word/document.xml'}.issubset(names):
                p.reject('INVALID_DOCUMENT', 422)
            # Bounded reads validate CRC and reject XML entities before a converter.
            for info in entries:
                if not info.is_dir():
                    data = archive.read(info)
                    if info.filename.endswith('.xml') and (b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper()):
                        p.reject('INVALID_DOCUMENT', 422)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, ValueError):
        p.reject('INVALID_DOCUMENT', 422)

async def bounded_upload(upload):
    content = bytearray()
    try:
        while True:
            chunk = await upload.read(64 * 1024)
            if not chunk:
                break
            if len(content) + len(chunk) > p.MAX_FILE_BYTES:
                p.reject('PAYLOAD_TOO_LARGE')
            content.extend(chunk)
        validate_document(content, upload.filename or 'uploaded.txt', upload.content_type)
        return bytes(content)
    finally:
        await upload.close()

def parse_bytes(content, filename, content_type=None):
    suffix = validate_document(content, filename, content_type)
    from app.understanding.models import ExtractedText
    with tempfile.TemporaryDirectory(prefix='hermes-document-') as folder, p.capacity('document'):
        source = Path(folder) / ('input' + suffix)
        output = Path(folder) / 'result.json'
        source.write_bytes(content)
        child = subprocess.Popen([sys.executable, '-m', 'app.security.document_worker', str(source), str(output)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=os.name == 'posix')
        try:
            child.wait(timeout=p.DOCUMENT_PARSE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                if os.name == 'posix':
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
            except ProcessLookupError:
                pass  # The parser may finish between the deadline and kill.
            finally:
                child.wait()
            p.reject('DOCUMENT_PARSE_TIMEOUT', 408)
        if child.returncode != 0 or not output.is_file():
            p.reject('INVALID_DOCUMENT', 422)
        if output.stat().st_size > p.MAX_EXTRACTED_TEXT_CHARS * 6 + 16384:
            p.reject('DOCUMENT_RESOURCE_LIMIT', 422)
        try:
            result = json.loads(output.read_text())
            if 'error' in result:
                p.reject(result['error'], 422)
            extracted = ExtractedText(**result)
        except (ValueError, TypeError):
            p.reject('INVALID_DOCUMENT', 422)
        p.guard_text(extracted.text, extracted=True)
        return extracted
