# HERMES-200 Understanding Tool Stack Decision

Status: Draft baseline
Module: HERMES-200 Understanding
Purpose: Convert unstructured recruiting data into validated structured intelligence.

## Core Rule

Local first.
Cloud extraction only when useful.
Compress before LLM.
LLM only when parser confidence is low.

## What HERMES-200 Must Understand

- Resumes
- Job descriptions
- Hotlists
- Recruiter messages
- Email text
- Telegram messages
- WhatsApp-style text
- Attachments
- Later: web/job page text

## Final Extraction Flow

Input file or text
-> normalize input
-> MarkItDown local extraction
-> extraction quality check
-> pdfplumber fallback for weak PDFs
-> Unstructured.io fallback when local extraction is weak and quota/privacy allow
-> normalized plain text
-> language detection
-> rule-based extraction
-> skill/entity extraction
-> schema validation
-> confidence scoring
-> duplicate detection
-> Headroom compression before LLM fallback
-> Portkey LLM fallback only when needed
-> validation again
-> handoff to Jobfynder API, Postgres, Typesense, or human review

## Phase 1 - Parser Foundation

Install and configure first:

- MarkItDown
- pdfplumber
- python-docx
- Unstructured.io dynamic fallback
- spaCy
- RapidFuzz
- LangDetect
- Pydantic
- Tiktoken
- Headroom compression layer

Purpose:

- Convert documents to text
- Normalize recruiter messages
- Extract obvious fields without LLM
- Detect language
- Match skills and aliases
- Validate structured output
- Estimate token cost before LLM fallback
- Compress long text before LLM fallback

## Phase 2 - Deduplication and Validation

Add after parser foundation:

- SimHash or MinHash
- jsonschema or Cerberus

Purpose:

- Detect duplicate resumes
- Detect duplicate jobs
- Detect duplicate hotlists
- Validate external API payloads

## Phase 3 - Observability and Evaluation

Add after first parser flows work:

- Langfuse
- Promptfoo
- Great Expectations

Purpose:

- Track LLM cost, latency, and quality
- Test prompt changes against benchmark samples
- Detect parse quality degradation

## Phase 4 - Web and Source Intelligence

Add later:

- Scrapling
- Exa MCP Server
- Headroom deeper integration for RAG/tool/log compression

Purpose:

- Extract useful web text
- Enrich recruiter/company/job context
- Avoid illegal or restricted scraping
- Use only compliant sources

## Tool Decisions

### MarkItDown

Default local document-to-text converter.

Use first for:
- PDF
- DOCX
- PPTX
- HTML
- TXT

### pdfplumber

Local PDF fallback.

Use when:
- MarkItDown output is weak
- Tables or layout matter
- PDF text extraction quality is low

### Unstructured.io

Dynamic cloud extraction fallback.

Use only when:
- Local extraction confidence is low
- File type or layout is complex
- Free-tier quota is available
- Privacy/compliance allows external processing

Do not use Unstructured.io for every document by default.

### python-docx

Direct DOCX handler.

Use for:
- DOCX structure extraction
- Future DOCX template generation

### spaCy

Zero-LLM NLP extraction.

Use for:
- Names
- Organizations
- Locations
- Dates
- Entity candidates

### RapidFuzz

Fuzzy matching.

Use for:
- Skills
- Aliases
- Misspellings
- Abbreviations

Examples:
- js -> JavaScript
- k8s -> Kubernetes

### LangDetect

Language detection.

Use for:
- Non-English routing
- Confidence scoring
- Bad input detection

### Pydantic

Main internal schema validation.

Use for:
- ResumeParseResult
- JobParseResult
- HotlistParseResult
- RecruiterMessageParseResult

### Tiktoken

Token estimation.

Use before:
- LLM fallback
- Headroom compression decision
- Cost-sensitive processing

### Headroom

Compression layer before LLM.

Use when:
- Text is long
- LLM fallback is needed
- Tool output, logs, files, RAG chunks, or conversation history would waste tokens

Initial rule:
- If text is above 2,000 estimated tokens and LLM fallback is needed, compress first.

### SimHash / MinHash

Near-duplicate detection.

Use for:
- Similar resumes
- Reworded jobs
- Duplicate hotlists
- Repeated recruiter messages

### Langfuse

LLM observability.

Use for:
- Cost tracking
- Latency tracking
- Prompt version tracking
- LLM fallback monitoring

### Promptfoo

Prompt evaluation.

Use after:
- 20 to 50 benchmark parser samples are collected

### Great Expectations

Data quality monitoring.

Use after:
- Parsed data flows regularly into database

### Scrapling / Exa MCP Server

Use later for:
- Web extraction
- Source intelligence
- Company/recruiter enrichment

Do not add these to Phase 1 unless required.

## First Build Target

Create internal parser pipeline:

raw input
-> normalized text
-> detected language
-> extracted entities
-> extracted skills
-> validated schema
-> confidence score
-> duplicate fingerprint
-> structured JSON response

LLM fallback is not included in the first parser commit.

## Handoff Targets

Later HERMES-200 handoff targets:

- Jobfynder API
- Postgres
- Typesense
- Human review queue
- Langfuse trace for LLM fallback
