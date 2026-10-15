"""Synthetic P0-D fixtures. No production data, live models or external APIs."""
import asyncio
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import httpx
from fastapi import HTTPException

from app.security import resource_policy as p
from app.security.document_safety import validate_document, validate_docx, parse_bytes
from app.security.resource_middleware import ResourceSafetyMiddleware
from tests.test_application_auth import principal, send


def pdf_bytes(pages=1, text='Hello staffing document'):
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'']
    kids = []
    for _ in range(pages):
        page_id = len(objects) + 1
        kids.append(f'{page_id} 0 R')
        stream = f'BT /F1 12 Tf 30 100 Td ({text}) Tj ET'.encode()
        objects.extend([f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 {page_id+2} 0 R >> >> /Contents {page_id+1} 0 R >>'.encode(),
                        b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream',
                        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'])
    objects[1] = f'<< /Type /Pages /Count {pages} /Kids [{" ".join(kids)}] >>'.encode()
    data = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data));data.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref = len(data);data.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:data.extend(f'{offset:010} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(data)

def docx_bytes():
    from docx import Document
    doc = Document();doc.add_paragraph('Hello staffing document')
    result = io.BytesIO();doc.save(result);return result.getvalue()

class DocumentSafetyTests(unittest.TestCase):
    def rejected(self, code, call, *args):
        with self.assertRaises(HTTPException) as ctx:call(*args)
        self.assertEqual(ctx.exception.detail, {'code': code})

    def test_valid_txt(self):
        self.assertEqual(parse_bytes(b'Hello staffing document', 'resume.txt').text, 'Hello staffing document')

    def test_valid_markdown(self):
        self.assertIn('Staffing', parse_bytes(b'# Staffing\nHello', 'resume.md').text)

    def test_valid_pdf(self):
        self.assertIn('Hello staffing', parse_bytes(pdf_bytes(), 'resume.pdf').text)

    def test_valid_docx(self):
        self.assertIn('Hello staffing', parse_bytes(docx_bytes(), 'resume.docx').text)

    def test_file_byte_limit(self):
        with patch.object(p, 'MAX_FILE_BYTES', 5):
            self.rejected('PAYLOAD_TOO_LARGE', validate_document, b'123456', 'x.txt')

    def test_unsupported_extension(self):
        self.rejected('UNSUPPORTED_MEDIA_TYPE', validate_document, b'hello', 'x.exe')

    def test_mime_mismatch(self):
        self.rejected('UNSUPPORTED_MEDIA_TYPE', validate_document, b'hello', 'x.txt', 'application/pdf')

    def test_signature_mismatch(self):
        self.rejected('INVALID_DOCUMENT', validate_document, pdf_bytes(), 'x.txt')
        self.rejected('INVALID_DOCUMENT', validate_document, b'hello', 'x.pdf')

    def test_invalid_text_encoding(self):
        for data in [b'\xff\xfe\x00', b'abc\x00def']:
            self.rejected('INVALID_DOCUMENT', validate_document, data, 'x.txt')

    def test_invalid_pdf_structure(self):
        self.rejected('INVALID_DOCUMENT', parse_bytes, b'%PDF-1.4\nnot a document\n%%EOF', 'x.pdf')

    def test_pdf_page_ceiling(self):
        with patch.dict(os.environ, {'HERMES_MAX_PDF_PAGES': '1'}):
            self.rejected('DOCUMENT_RESOURCE_LIMIT', parse_bytes, pdf_bytes(pages=2), 'x.pdf')

    def test_pdf_text_ceiling(self):
        with patch.dict(os.environ, {'HERMES_MAX_EXTRACTED_TEXT_CHARS': '10'}):
            self.rejected('DOCUMENT_RESOURCE_LIMIT', parse_bytes, pdf_bytes(), 'x.pdf')

    def test_pdf_encryption_metadata_rejected(self):
        # Exercise worker preflight with harmless metadata; no encrypted payload/cracking.
        from app.security import document_worker
        fake = Mock()
        fake.__enter__ = Mock(return_value=fake);fake.__exit__ = Mock(return_value=False)
        fake.doc.is_extractable = False
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'input.pdf';source.write_bytes(pdf_bytes());output=Path(folder)/'out.json'
            with patch('pdfplumber.open',return_value=fake), patch.object(sys,'argv',['worker',str(source),str(output)]), patch('resource.setrlimit'), patch('socket.socket.connect'):
                document_worker.main()
            self.assertEqual(json.loads(output.read_text())['error'],'INVALID_DOCUMENT')

    def test_invalid_docx(self):
        self.rejected('INVALID_DOCUMENT', validate_document, b'not zip', 'x.docx')

    def archive(self, entries):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for name,data in entries:z.writestr(name,data)
        return stream.getvalue()

    def test_docx_traversal_and_absolute_paths(self):
        for name in ['../evil','/evil','C:/evil','word\\evil']:
            self.rejected('INVALID_DOCUMENT',validate_docx,self.archive([(name,'safe')]))

    def test_docx_nested_archive(self):
        self.rejected('INVALID_DOCUMENT',validate_docx,self.archive([('word/embedded.zip','safe')]))

    def test_docx_entry_count(self):
        with patch.object(p,'MAX_DOCX_ENTRIES',1):
            self.rejected('DOCUMENT_RESOURCE_LIMIT',validate_docx,self.archive([('a','x'),('b','x')]))

    def test_docx_total_size(self):
        with patch.object(p,'MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES',3):
            self.rejected('DOCUMENT_RESOURCE_LIMIT',validate_docx,self.archive([('a','abcd')]))

    def test_docx_single_entry_size(self):
        with patch.object(p,'MAX_DOCX_SINGLE_ENTRY_BYTES',3):
            self.rejected('DOCUMENT_RESOURCE_LIMIT',validate_docx,self.archive([('a','abcd')]))

    def test_docx_compression_ratio(self):
        # Tiny, harmless fixture under 1 KB, with a deliberately low test ceiling.
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('a','a'*200)
        with patch.object(p,'MAX_DOCX_COMPRESSION_RATIO',2):
            self.rejected('DOCUMENT_RESOURCE_LIMIT',validate_docx,stream.getvalue())

    def test_docx_entities(self):
        self.rejected('INVALID_DOCUMENT',validate_docx,self.archive([('[Content_Types].xml','<x/>'),('word/document.xml','<!DOCTYPE x><x/>')]))

    def test_timeout_kills_only_parser_and_cleans_files(self):
        original=subprocess.Popen
        children=[]
        def slow(*args,**kwargs):
            child=original([sys.executable,'-c','import time;time.sleep(5)'],**kwargs);children.append(child);return child
        with tempfile.TemporaryDirectory() as folder:
            real_temp=tempfile.TemporaryDirectory
            def located(*args,**kwargs):return real_temp(*args,dir=folder,**kwargs)
            with patch('app.security.document_safety.subprocess.Popen',side_effect=slow),patch('app.security.document_safety.tempfile.TemporaryDirectory',side_effect=located),patch.object(p,'DOCUMENT_PARSE_TIMEOUT_SECONDS',0.1):
                self.rejected('DOCUMENT_PARSE_TIMEOUT',parse_bytes,b'hello','x.txt')
            self.assertEqual(list(Path(folder).iterdir()),[])
            self.assertTrue(all(child.poll() is not None for child in children))

    def test_excess_extracted_text_never_reaches_taxonomy_or_model(self):
        from app.understanding.models import ExtractedText
        from app.understanding.service import build_understanding_result
        with patch.object(p,'MAX_EXTRACTED_TEXT_CHARS',4),patch('app.understanding.service.extract_taxonomy_signals') as taxonomy,patch('app.understanding.service.apply_llm_fallback') as model:
            self.rejected('DOCUMENT_RESOURCE_LIMIT',build_understanding_result,ExtractedText(text='12345'))
        taxonomy.assert_not_called();model.assert_not_called()

    def test_document_concurrency(self):
        with p.capacity('document'),p.capacity('document'):
            self.rejected('RESOURCE_BUSY',lambda: p.capacity('document').__enter__())

    def test_streaming_upload_stops_and_closes(self):
        from app.security.document_safety import bounded_upload
        from starlette.datastructures import UploadFile
        upload=UploadFile(io.BytesIO(b'123456'),filename='safe.txt')
        with patch.object(p,'MAX_FILE_BYTES',5):
            with self.assertRaises(HTTPException) as exc:asyncio.run(bounded_upload(upload))
        self.assertEqual(exc.exception.status_code,413)
        self.assertTrue(upload.file.closed)

    def test_invalid_file_intake_precedes_all_durable_writes(self):
        from app.intake.service import process_file_intake
        targets=['app.intake.service.store_attachment','app.intake.service.record_intake','app.intake.service.emit_event','app.intake.service.create_draft_object','app.intake.service.build_understanding_result']
        with ExitStack() as stack:
            mocks=[stack.enter_context(patch(t,side_effect=AssertionError('Side effect forbidden'))) for t in targets]
            self.rejected('INVALID_DOCUMENT',process_file_intake,'bad.docx',b'invalid',None)
            for mock in mocks:mock.assert_not_called()

    def test_authorized_small_file_http_path(self):
        from app.understanding.models import UnderstandingResult,ExtractedText,ParseQuality
        result=UnderstandingResult(document_kind='resume',extracted_text=ExtractedText(text='safe'),quality=ParseQuality(confidence=1.0),validation={},fallback={},llm_context={},structured_data={})
        with patch('app.security.rbac.load_access_users',return_value=[principal(permissions=['understanding:parse'])]),patch.object(p,'MAX_EXPENSIVE_REQUESTS_PER_MINUTE',100_000),patch('app.routers.understanding.build_understanding_result',return_value=result) as build,patch('urllib.request.urlopen',side_effect=AssertionError('Egress forbidden')):
            response=send('POST','/understanding/parse-file',files={'file':('resume.txt',b'safe','text/plain')},data={'document_kind':'resume'},headers={'Authorization':'Bearer service-token'})
        self.assertEqual(response.status_code,200)
        build.assert_called_once()

    def test_telegram_download_actual_bytes_bounded(self):
        from app.providers.telegram.service import telegram_download_file
        response=io.BytesIO(b'123456');response.headers={}
        with patch('app.providers.telegram.service.telegram_get_file',return_value={'ok':True,'result':{'file_path':'safe.txt'}}),patch('app.providers.telegram.service.urlopen',return_value=response),patch('app.security.resource_policy.MAX_FILE_BYTES',5):
            self.rejected('PAYLOAD_TOO_LARGE',telegram_download_file,'synthetic')
        self.assertTrue(response.closed)

    def test_telegram_metadata_limit_prevents_download(self):
        from app.providers.telegram.service import telegram_download_file
        with patch('app.providers.telegram.service.telegram_get_file',return_value={'ok':True,'result':{'file_path':'safe.txt','file_size':6}}),patch('app.providers.telegram.service.urlopen') as network,patch('app.security.resource_policy.MAX_FILE_BYTES',5):
            self.rejected('PAYLOAD_TOO_LARGE',telegram_download_file,'synthetic')
        network.assert_not_called()


class RequestSafetyTests(unittest.TestCase):
    def setUp(self):
        self.entered=0
        self.bodies=[]
        async def endpoint(scope,receive,send):
            self.entered+=1
            data=await receive();self.bodies.append(data['body'])
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'ok'})
        self.app=ResourceSafetyMiddleware(endpoint)

    def request(self,data,path='/safe',headers=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test') as client:
                return await client.post(path,content=data,headers=headers or {'Content-Type':'application/json'})
        return asyncio.run(run())

    def test_json_under_limit(self):
        self.assertEqual(self.request(b'{"text":"ok"}').status_code,200)

    def test_json_above_limit_before_handler(self):
        with patch.object(p,'MAX_JSON_BODY_BYTES',8):
            self.assertEqual(self.request(b'{"text":"too long"}').status_code,413)
        self.assertEqual(self.entered,0)

    def test_chunked_actual_bytes_limit(self):
        async def chunks():
            yield b'1234';yield b'56789'
        with patch.object(p,'MAX_JSON_BODY_BYTES',8):
            self.assertEqual(self.request(chunks(),headers={}).status_code,413)
        self.assertEqual(self.entered,0)

    def test_collection_limits(self):
        for key,limit in p.LIST_LIMITS.items():
            with self.subTest(key=key):
                self.assertEqual(self.request(json.dumps({key:['x']*(limit+1)}).encode()).status_code,413)
        self.assertEqual(self.entered,0)

    def test_history_per_message_and_total(self):
        for history in [[{'content':'x'*(p.MAX_MESSAGE_CHARS+1)}],['x'*15000]*8]:
            self.assertEqual(self.request(json.dumps({'history':history}).encode()).status_code,413)

    def test_exact_webhook_bytes_preserved(self):
        body=b'{ "text" : "exact bytes" }'
        self.assertEqual(self.request(body,path='/internal/comm/intake').status_code,200)
        self.assertEqual(self.bodies,[body])

    def test_body_receive_timeout(self):
        async def chunks():
            await asyncio.sleep(1);yield b'{}'
        with patch.object(p,'BODY_TIMEOUT_SECONDS',0.01):
            self.assertEqual(self.request(chunks()).status_code,408)
        self.assertEqual(self.entered,0)

    def test_oversized_unauthenticated_upload_has_no_side_effects(self):
        targets=['app.intake.service.store_attachment','app.intake.service.record_intake','app.intake.service.create_draft_object','app.security.document_safety.parse_bytes','app.understanding.service.extract_taxonomy_signals','app.prompt_runtime.service.run_prompt','app.prompt_runtime.service.send_langfuse_trace','app.providers.gmail.service._gmail_api_get','urllib.request.urlopen']
        with ExitStack() as stack:
            mocks=[stack.enter_context(patch(t,side_effect=AssertionError('Forbidden side effect'))) for t in targets]
            response=send('POST','/channels/intake/file',content=b'invalid',headers={'Content-Length':str(p.MAX_MULTIPART_BODY_BYTES+1)})
            self.assertEqual(response.status_code,401)
            for mock in mocks:mock.assert_not_called()

    def test_authenticated_rate_limit(self):
        with patch('app.security.rbac.load_access_users',return_value=[principal(permissions=['understanding:parse'])]),patch.object(p,'MAX_EXPENSIVE_REQUESTS_PER_MINUTE',1):
            first=self.request(b'{}','/understanding/parse-file',{'Authorization':'Bearer service-token'})
            second=self.request(b'{}','/understanding/parse-file',{'Authorization':'Bearer service-token'})
        self.assertEqual(first.status_code,200);self.assertEqual(second.status_code,429)

    def test_expensive_concurrency_limit(self):
        self.app.active=p.MAX_EXPENSIVE_CONCURRENCY
        with patch('app.security.rbac.load_access_users',return_value=[principal(permissions=['understanding:parse'])]):
            r=self.request(b'{}','/understanding/parse-file',{'Authorization':'Bearer service-token'})
        self.assertEqual(r.status_code,429);self.assertEqual(self.entered,0)

    def test_disabled_gmail_push_keeps_410(self):
        self.assertEqual(send('POST','/providers/gmail/push',content=b'',headers={'Content-Length':'999999999'}).status_code,410)


class ModelSafetyTests(unittest.TestCase):
    def test_http_model_budget_reaches_sync_handler_and_resets(self):
        from fastapi import FastAPI
        mini=FastAPI()
        mini.add_middleware(ResourceSafetyMiddleware)
        @mini.post('/safe')
        def handler():
            p.consume_model_attempt();p.consume_model_attempt()
            return {'ok':True}
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mini),base_url='http://test') as client:
                return await client.post('/safe',json={})
        with patch.object(p,'MAX_MODEL_CALLS_PER_REQUEST',1):
            response=asyncio.run(run())
        self.assertEqual(response.status_code,429)
        self.assertIsNone(p.MODEL_REQUEST_BUDGET.get())

    def test_actual_hidden_model_routes_receive_http_limits(self):
        from app.security.resource_middleware import expensive
        for path in ['/taxonomy-candidates/1/approve','/taxonomy-enrichment-requests/1/generate','/taxonomy/skills/test/description','/v1/messages/actions/extract','/v1/messages/understand','/context/candidate-card/build','/resume-builder/summary/suggest']:
            self.assertTrue(expensive(path),path)

    def test_model_attempt_budget_precedes_network(self):
        from app.prompt_runtime.service import _call_litellm_with_model
        from app.prompt_runtime.models import PromptRenderedMessage
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=b'{"choices":[{"message":{"content":"safe"}}]}'
        token=p.MODEL_REQUEST_BUDGET.set({'calls':0})
        try:
            with patch.dict(os.environ,{'LITELLM_API_KEY':'synthetic'}),patch.object(p,'MAX_MODEL_CALLS_PER_REQUEST',1),patch('urllib.request.urlopen',return_value=response) as network:
                _call_litellm_with_model([PromptRenderedMessage(role='user',content='safe')],'unchanged-model')
                with self.assertRaises(HTTPException) as exc:_call_litellm_with_model([PromptRenderedMessage(role='user',content='safe')],'unchanged-model')
                self.assertEqual(exc.exception.status_code,429)
                self.assertEqual(network.call_count,1)
        finally:
            p.MODEL_REQUEST_BUDGET.reset(token)

    def test_prompt_guard_precedes_registry_langfuse_and_model(self):
        from app.prompt_runtime.models import PromptRunRequest
        from app.prompt_runtime.service import run_prompt
        with patch.object(p,'MAX_MODEL_INPUT_CHARS',5),patch('app.prompt_runtime.service.get_prompt') as registry,patch('app.prompt_runtime.service._call_litellm') as model:
            with self.assertRaises(HTTPException):run_prompt(PromptRunRequest(prompt_id='test',variables={'text':'too large'}))
        registry.assert_not_called();model.assert_not_called()

    def test_direct_model_guard_precedes_network(self):
        from app.prompt_runtime.service import _call_litellm_with_model
        from app.prompt_runtime.models import PromptRenderedMessage
        with patch.object(p,'MAX_MODEL_INPUT_CHARS',5),patch('urllib.request.urlopen') as network:
            with self.assertRaises(HTTPException):_call_litellm_with_model([PromptRenderedMessage(role='user',content='too large')],'unchanged-model')
        network.assert_not_called()

    def test_fallback_guard_precedes_prompt(self):
        from app.prompt_runtime.extraction_fallback import run_llm_fallback
        with patch.object(p,'MAX_MODEL_INPUT_CHARS',5),patch('app.prompt_runtime.extraction_fallback.run_prompt') as model:
            with self.assertRaises(HTTPException):run_llm_fallback(prompt_id='test',variables={'x':'too large'},source='test')
        model.assert_not_called()

    def test_model_concurrency(self):
        with p.capacity('model'),p.capacity('model'):
            with self.assertRaises(HTTPException) as exc:
                with p.capacity('model'):pass
        self.assertEqual(exc.exception.status_code,429)


if __name__=='__main__':unittest.main()
