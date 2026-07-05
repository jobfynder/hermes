# HERMES-200 Understanding — Progress Checkpoint

Status: In progress  
Branch: feature/hermes-200-understanding  
Server: jobfynder-intel-01

---

## Completed Foundation

### 1. Parser Foundation

Implemented:

- `app/understanding/`
- `app/understanding/models.py`
- `app/understanding/service.py`
- `/understanding/parse-text`

Commit:

- `8b8b906 feat(hermes-200): add parser foundation and parse-text endpoint`

---

### 2. Local Document Extractors

Implemented:

- Plain text extractor
- MarkItDown extractor
- pdfplumber PDF fallback
- python-docx DOCX fallback
- Local file extraction router

Commit:

- `12c11d6 feat(hermes-200): add local document extractors`

---

### 3. Extraction Quality Scoring

Implemented:

- Character count
- Word count
- Token count
- Language detection
- Confidence score
- Fallback decision
- Failure reasons

Commit:

- `0835fcd feat(hermes-200): add extraction quality scoring`

---

### 4. Token Budget Compression

Implemented:

- Local token counter
- Head/tail compression
- LLM-ready compressed context

Commits:

- `59d3409 feat(hermes-200): add token budget compression`
- `e3fd29f feat(hermes-200): add compressed llm context to understanding result`

---

### 5. File Upload Parsing

Implemented:

- `/understanding/parse-file`
- Text file upload support
- DOCX upload support
- Safe PDF weak-extraction fallback behavior

Commit:

- `db08581 feat(hermes-200): add parse-file upload endpoint`

---

### 6. MarkItDown-First Strategy

Implemented:

- MarkItDown is attempted first for supported document files
- Specialized local fallback is used when MarkItDown output is empty or weak

Commit:

- `ba71eee feat(hermes-200): prefer markitdown before local extractor fallbacks`

---

### 7. Basic Local Skills Parser

Implemented:

- spaCy blank English tokenizer
- RapidFuzz-assisted skill detection
- Exact phrase skill detection
- Years-of-experience extraction
- No LLM usage

Commit:

- `b6331e5 feat(hermes-200): add basic local skills parser`

---

### 8. Repeatable Smoke Test

Implemented:

- `scripts/hermes-200-smoke-test.sh`

Validated:

- Health endpoint
- Good text parsing
- Weak text fallback
- Text file upload
- Skills extraction
- Years-of-experience extraction
- LLM context generation

Commit:

- `c20498a test(hermes-200): add understanding smoke test script`

---

## Current API Endpoints

### Parse Text

`POST /understanding/parse-text`

Accepts raw text and returns:

- Extracted text
- Quality score
- Fallback decision
- LLM context
- Basic structured data

### Parse File

`POST /understanding/parse-file`

Accepts uploaded files and returns:

- Extracted text
- Extractor source
- Quality score
- Fallback decision
- LLM context
- Basic structured data

---

## Current Parser Behavior

The current HERMES-200 parser follows this order:

1. Extract text locally
2. Score extraction quality
3. Compress text into LLM-safe context
4. Parse basic structured fields locally
5. Mark low-confidence extraction as fallback-needed
6. Avoid LLM unless later fallback rules explicitly require it

---

## Current Structured Fields

Current local parser extracts:

- Skills
- Years of experience
- Parser metadata

---

## Current Phase 1 Tools Activated

Activated:

- MarkItDown
- pdfplumber
- python-docx
- spaCy
- RapidFuzz
- LangDetect
- Pydantic
- Tiktoken
- Local token-budget compression

Pending:

- Headroom integration
- Unstructured.io dynamic fallback
- Cloud extraction policy
- Resume-specific schema
- Job-description-specific schema
- Skill taxonomy persistence

---

## Next Recommended Steps

1. Add resume/job-description schema models.
2. Add document-kind-specific parsers.
3. Add better skill taxonomy source file.
4. Add fallback policy engine.
5. Add Unstructured.io only as optional dynamic fallback.
6. Add Headroom or keep current compression as baseline until Headroom integration is confirmed.
7. Add parser result validation.
8. Add parser output versioning.

---

## Additional Completed Milestones

### 9. Structured Parsing Schemas

Implemented:

- `ParsedSkill`
- `ParserMetadata`
- `ResumeStructuredData`
- `JobDescriptionStructuredData`
- `GenericStructuredData`

Commit:

- `f2c19d8 feat(hermes-200): add structured parsing schemas`

---

### 10. Schema-Aware Basic Parser

Implemented:

- Resume-specific structured output
- Job-description-specific structured output
- Generic message/unknown structured output
- Basic title extraction
- Schema version metadata

Commit:

- `a80165a feat(hermes-200): wire structured schemas into basic parser`

---

## Latest Validation

Validated with:

- `scripts/hermes-200-smoke-test.sh`

Result:

- Health endpoint passed
- Good resume parse passed
- Weak text fallback passed
- Text file upload parse passed
- Skills extraction passed
- Years-of-experience extraction passed

Latest confirmed commit:

- `a80165a feat(hermes-200): wire structured schemas into basic parser`

---

## Updated Next Recommended Steps

1. Move skill taxonomy into a separate editable source file.
2. Add synonyms and aliases for skills.
3. Add resume-specific field extraction.
4. Add job-description-specific field extraction.
5. Add parser fallback policy engine.
6. Add optional Unstructured.io fallback only after local quality checks.
7. Keep current local token compression as baseline before Headroom integration.

---

## Additional Completed Milestones

### 11. Editable Skills Taxonomy

Implemented:

- `app/understanding/taxonomy/skills.json`
- `app/understanding/taxonomy/loader.py`
- Skill aliases
- Taxonomy versioning
- Short-alias false-positive protection

Validated:

- `nodejs` does not incorrectly trigger `JavaScript`
- Exact `js` alias still triggers `JavaScript`
- Smoke test still passes

Commit:

- `7e8020a feat(hermes-200): move skills into editable taxonomy`

---

### 12. Parser Fallback Policy Engine

Implemented:

- `app/understanding/fallback_policy.py`
- Fallback decision model
- Safe default action handling
- Manual review decision when cloud/LLM fallbacks are disabled
- API response now includes `fallback`

Default behavior:

- Good extraction: `fallback.action = none`
- Weak extraction: `fallback.action = manual_review`

Commit:

- `80ea559 feat(hermes-200): add parser fallback policy engine`

---

### 13. Configurable Fallback Flags

Implemented:

- `HERMES_CLOUD_EXTRACTION_FALLBACK_ENABLED`
- `HERMES_LLM_FALLBACK_ENABLED`
- Both disabled by default
- `.env.example` documentation

Commits:

- `f525f50 feat(hermes-200): add configurable fallback flags`
- `12b8d4d docs(hermes-200): document fallback config flags`

---

## Latest Confirmed HERMES-200 State

Latest pushed commit:

- `12b8d4d docs(hermes-200): document fallback config flags`

Current behavior:

1. Parse text or uploaded file.
2. Extract locally first.
3. Score quality.
4. Compress into LLM-safe context.
5. Parse skills and years locally.
6. Use structured schemas.
7. Decide fallback action without calling cloud/LLM by default.
8. Return all results through API.

---

## Updated Next Recommended Steps

1. Add resume-specific extraction fields:
   - current title
   - email
   - phone
   - location
   - work authorization
   - LinkedIn
2. Add job-description-specific extraction fields:
   - job title
   - location
   - employment type
   - work authorization
   - rate/salary
   - required skills vs preferred skills
3. Add parser output validation.
4. Add optional Unstructured.io fallback wrapper, still disabled by default.
5. Add parser confidence thresholds per document type.
6. Add `/understanding/taxonomy/skills` read endpoint for debugging.

---

## Additional Completed Milestones

### 14. Skills Taxonomy Debug Endpoint

Implemented:

- `GET /understanding/taxonomy/skills`
- Returns taxonomy version
- Returns editable skills list
- Useful for debugging parser/taxonomy behavior

Validated:

- Endpoint returns `jobfynder_skills_v1`
- Endpoint returns 33 skills
- Smoke test now validates taxonomy endpoint

Commits:

- `8dcf427 feat(hermes-200): add skills taxonomy debug endpoint`
- `99f0e39 test(hermes-200): include taxonomy endpoint in smoke test`

---

## Latest Confirmed HERMES-200 State

Latest pushed commit:

- `99f0e39 test(hermes-200): include taxonomy endpoint in smoke test`

Validated with:

- `scripts/hermes-200-smoke-test.sh`

Result:

- HERMES-200 smoke test passed
- Health endpoint passed
- Parse-text passed
- Weak fallback passed
- Parse-file text upload passed
- Taxonomy endpoint passed
