"""Local-only document worker; no DB, taxonomy, models, or cloud extraction."""
import json
import os
from pathlib import Path
import sys

def main():
    from app.security import resource_policy as p
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['OMP_NUM_THREADS'] = '1'
    if os.name == 'posix':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (p.DOCUMENT_MEMORY_BYTES, p.DOCUMENT_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (p.DOCUMENT_PARSE_TIMEOUT_SECONDS, p.DOCUMENT_PARSE_TIMEOUT_SECONDS))
        resource.setrlimit(resource.RLIMIT_FSIZE, (p.MAX_EXTRACTED_TEXT_CHARS * 6 + 16384,) * 2)
    # MarkItDown is local-only here, including any accidentally enabled plugin.
    import socket
    def no_network(*args, **kwargs):
        raise OSError('Document worker networking disabled')
    socket.socket.connect = no_network
    from fastapi import HTTPException
    source, output = map(Path, sys.argv[1:])
    try:
        if source.suffix == '.pdf':
            import pdfplumber
            with pdfplumber.open(source) as pdf:
                if (pdf.doc.is_extractable is False or getattr(pdf.doc, 'encryption', None)
                        or any(xref.get_trailer().get('Encrypt') for xref in pdf.doc.xrefs)):
                    p.reject('INVALID_DOCUMENT', 422)
                if len(pdf.pages) > p.MAX_PDF_PAGES:
                    p.reject('DOCUMENT_RESOURCE_LIMIT', 422)
        from app.understanding.extractors.local_file import _extract_local_file_unbounded
        result = _extract_local_file_unbounded(source)
        p.guard_text(result.text, extracted=True)
        output.write_text(json.dumps(result.model_dump()))
    except HTTPException as exc:
        output.write_text(json.dumps({'error': exc.detail['code']}))
    except Exception:
        output.write_text(json.dumps({'error': 'INVALID_DOCUMENT'}))

if __name__ == '__main__':
    main()
