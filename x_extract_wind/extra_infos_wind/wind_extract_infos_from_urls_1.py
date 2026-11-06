"""
wind_turbine_extractor.py

Extract wind-turbine specs (count, hub height, rotor diameter, blade length,
tip height, model, manufacturer, rated power) from large Italian wind-farm
PDFs (VIA/PFTE/relazione tecnica documents, etc.) using a SMALL local LLM.

Pipeline (map-reduce over the document):
  1. Extract text page-by-page (PyMuPDF).
  2. Build overlapping multi-page chunks (so a table split across pages
     isn't cut in half).
  3. Cheaply pre-filter chunks with keyword matching (EN + IT) so the LLM
     only runs on the ~10-20% of pages that actually mention turbine specs.
     This is what makes it feasible on large PDFs with a small model.
  4. "Map": ask the small LLM to extract a JSON array of turbine records
     from each relevant chunk, constrained by a strict schema.
  5. "Reduce": feed all partial JSON extractions back into the LLM once,
     asking it to merge duplicates (the same turbine model described in
     the summary AND in the technical annex) into one clean list.

Model backend: Ollama (local, no API key, easy quantized small models).
  Install:  https://ollama.com
  Pull:     ollama pull qwen2.5:3b-instruct      (good JSON adherence)
            ollama pull phi3:mini                (alternative, ~3.8B)
  Ollama exposes an OpenAI-ish local HTTP API at http://localhost:11434.

If you'd rather use Hugging Face `transformers` directly instead of Ollama,
see `call_llm_transformers()` at the bottom — swap it in for `call_llm_ollama`.

Usage:
    python wind_turbine_extractor.py input.pdf -o turbines.json
    python wind_turbine_extractor.py input.pdf -o turbines.json --model phi3:mini
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import fitz  # PyMuPDF
import requests

# --------------------------------------------------------------------------
# 1. Keyword pre-filter (EN + IT) — cheap way to skip irrelevant pages
# --------------------------------------------------------------------------

RELEVANT_KEYWORDS = [
    # English
    "turbine", "rotor diameter", "hub height", "blade length", "tip height",
    "rated power", "nameplate capacity", "swept area", "wind farm layout",
    # Italian
    "aerogeneratore", "aerogeneratori", "turbina eolica", "turbine eoliche",
    "altezza al mozzo", "altezza mozzo", "diametro rotore", "diametro del rotore",
    "lunghezza pala", "lunghezza delle pale", "altezza massima", "altezza totale",
    "potenza nominale", "potenza installata", "numero di aerogeneratori",
    "impianto eolico", "torre eolica", "pale eoliche",
]

CHUNK_SIZE_PAGES = 3       # pages per chunk
CHUNK_OVERLAP_PAGES = 1    # overlap so tables spanning a page break survive


# --------------------------------------------------------------------------
# 0. Resolve input source: local path or URL
# --------------------------------------------------------------------------

def is_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def download_pdf(url: str, timeout: int = 60) -> str:
    """Download a PDF from a URL to a temp file and return the local path.
    Caller is responsible for deleting the file when done (see cleanup in main)."""
    print(f"[info] downloading PDF from {url}", file=sys.stderr)
    resp = requests.get(url, timeout=timeout, stream=True)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
        print(
            f"[warn] response Content-Type is '{content_type}', not obviously a PDF. "
            "Continuing anyway, but extraction may fail if this isn't really a PDF.",
            file=sys.stderr,
        )

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    total_bytes = 0
    with os.fdopen(fd, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            total_bytes += len(chunk)

    print(f"[info] downloaded {total_bytes / 1024:.1f} KB to {tmp_path}", file=sys.stderr)
    return tmp_path


def resolve_pdf_source(source: str) -> tuple[str, bool]:
    """
    Return (local_pdf_path, is_temp_file).
    If `source` is a URL, download it to a temp file (is_temp_file=True, caller
    should clean it up). Otherwise treat it as a local path unchanged.
    """
    if is_url(source):
        return download_pdf(source), True
    return source, False


# --------------------------------------------------------------------------
# 2. PDF text extraction and chunking
# --------------------------------------------------------------------------

@dataclass
class Chunk:
    chunk_id: int
    page_start: int
    page_end: int
    text: str


def extract_pages(pdf_path: str) -> list[str]:
    """Return a list of per-page text, 1 entry per page."""
    doc = fitz.open(pdf_path)
    pages = [page.get_text("text") for page in doc]
    doc.close()
    return pages


def build_chunks(
    pages: list[str],
    size: int = CHUNK_SIZE_PAGES,
    overlap: int = CHUNK_OVERLAP_PAGES,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    step = max(size - overlap, 1)
    i = 0
    cid = 0
    while i < len(pages):
        page_slice = pages[i : i + size]
        if page_slice:
            chunks.append(
                Chunk(
                    chunk_id=cid,
                    page_start=i + 1,
                    page_end=i + len(page_slice),
                    text="\n".join(page_slice),
                )
            )
            cid += 1
        i += step
    return chunks


def filter_relevant_chunks(chunks: list[Chunk]) -> list[Chunk]:
    pattern = re.compile("|".join(re.escape(k) for k in RELEVANT_KEYWORDS), re.IGNORECASE)
    return [c for c in chunks if pattern.search(c.text)]


# --------------------------------------------------------------------------
# 3. LLM call (Ollama backend)
# --------------------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"

EXTRACTION_SCHEMA_HINT = """
Return ONLY a JSON object of this exact shape (no prose, no markdown fences):
{
  "turbines": [
    {
      "turbine_model": string or null,       // e.g. "Vestas V150-4.2 MW"
      "manufacturer": string or null,        // e.g. "Vestas", "Enercon"
      "number_of_turbines": integer or null, // count of this turbine type/group
      "rated_power_MW": number or null,
      "hub_height_m": number or null,
      "rotor_diameter_m": number or null,
      "blade_length_m": number or null,
      "total_tip_height_m": number or null,  // max height incl. blade tip
      "source_page_range": string            // e.g. "12-14", copy from context given
    }
  ]
}
Rules:
- Only include a field value if it is explicitly stated in the text. Otherwise use null.
- Do not guess or compute missing values.
- If multiple turbine models/groups are described, add multiple objects to "turbines".
- If nothing turbine-related is actually present, return {"turbines": []}.
- ALWAYS return a top-level JSON OBJECT with a "turbines" key -- never a bare array.
"""

MAP_PROMPT_TEMPLATE = """You are extracting technical specs of wind turbines from an
Italian wind-farm permitting document. Text may be in Italian or English.

{schema}

Source page range for this excerpt: {page_range}

TEXT EXCERPT:
\"\"\"
{chunk_text}
\"\"\"

JSON object:"""

REDUCE_PROMPT_TEMPLATE = """You are given several JSON extractions of wind-turbine records,
independently extracted from different sections of the same document. The same
turbine model may appear more than once (e.g. once in a project summary, once in
a technical annex) with partially overlapping fields.

Merge these into a single clean result: one entry per distinct turbine
model/group. When the same model appears multiple times, combine the fields,
preferring the most specific / most complete non-null value. Keep the schema
fields exactly as given. Return ONLY a JSON object of the shape
{{"turbines": [...]}}, no prose.

PARTIAL EXTRACTIONS:
{all_json}

Merged JSON object:"""


def call_llm_ollama(prompt: str, model: str = "qwen2.5:3b-instruct", timeout: int = 120) -> str:
    """Call a small local model via Ollama and return raw text output."""
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",   # Ollama's constrained JSON mode -> much fewer parse errors
            "options": {"temperature": 0.0},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["response"]


def call_llm_transformers(prompt: str, model_name: str = "Qwen/Qwen2.5-1.5B-Instruct") -> str:
    """
    Alternative backend using Hugging Face transformers directly, if you don't
    want to run Ollama. Loads once per process in real use (cache the pipeline
    globally instead of reloading per call).
    """
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name, torch_dtype=torch.bfloat16, device_map="auto"
    )
    messages = [{"role": "user", "content": prompt}]
    inputs = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to(model.device)
    out = model.generate(inputs, max_new_tokens=800, do_sample=False, temperature=0.0)
    return tok.decode(out[0][inputs.shape[1]:], skip_special_tokens=True)


def safe_json_parse(raw: str) -> list[dict[str, Any]]:
    """
    Recover the turbine list from the model's raw output.
    Expected shape: {"turbines": [ {...}, ... ]}
    Also tolerates a bare array or a single object, in case the model
    (or a future prompt tweak) deviates from the wrapped-object schema.
    """
    raw = raw.strip()
    raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
    match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, dict):
        if "turbines" in parsed and isinstance(parsed["turbines"], list):
            return parsed["turbines"]
        # A dict that isn't the wrapper but looks like a single turbine record
        # (has at least one expected field) -- treat as one record.
        expected_fields = {
            "turbine_model", "manufacturer", "number_of_turbines", "rated_power_MW",
            "hub_height_m", "rotor_diameter_m", "blade_length_m", "total_tip_height_m",
        }
        if expected_fields & parsed.keys():
            return [parsed]
        return []
    if isinstance(parsed, list):
        return parsed
    return []


# --------------------------------------------------------------------------
# 4. Map step
# --------------------------------------------------------------------------

def extract_from_chunk(chunk: Chunk, model: str, debug: bool = False) -> list[dict[str, Any]]:
    prompt = MAP_PROMPT_TEMPLATE.format(
        schema=EXTRACTION_SCHEMA_HINT,
        page_range=f"{chunk.page_start}-{chunk.page_end}",
        chunk_text=chunk.text[:6000],  # guard against runaway chunk length
    )
    raw = call_llm_ollama(prompt, model=model)
    parsed = safe_json_parse(raw)
    if debug:
        print(f"\n[debug] --- chunk {chunk.chunk_id} (pages {chunk.page_start}-{chunk.page_end}) raw LLM output ---",
              file=sys.stderr)
        print(raw[:1000], file=sys.stderr)
        print(f"[debug] parsed {len(parsed)} record(s) from this chunk", file=sys.stderr)
    return parsed


# --------------------------------------------------------------------------
# 5. Reduce step
# --------------------------------------------------------------------------

def reduce_records(all_records: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    if not all_records:
        return []
    if len(all_records) == 1:
        return all_records
    prompt = REDUCE_PROMPT_TEMPLATE.format(all_json=json.dumps(all_records, ensure_ascii=False, indent=2))
    raw = call_llm_ollama(prompt, model=model)
    merged = safe_json_parse(raw)
    return merged if merged else all_records  # fall back to unmerged if reduce fails


# --------------------------------------------------------------------------
# 6. Orchestration
# --------------------------------------------------------------------------

def process_pdf(
    pdf_path: str,
    model: str = "qwen2.5:3b-instruct",
    verbose: bool = True,
    debug: bool = False,
) -> list[dict[str, Any]]:
    local_path, is_temp = resolve_pdf_source(pdf_path)
    try:
        pages = extract_pages(local_path)
        total_chars = sum(len(p) for p in pages)
        if verbose:
            print(f"[info] {pdf_path}: {len(pages)} pages extracted, {total_chars} characters total", file=sys.stderr)
        if total_chars < 200 * max(len(pages), 1):
            # Fewer than ~200 chars/page on average almost always means the PDF is
            # scanned images with no text layer -> PyMuPDF text extraction returns nothing.
            print(
                "[warn] Very little text extracted per page. This PDF is likely scanned "
                "(image-only) and needs OCR before this pipeline will find anything. "
                "See the note about pytesseract in the script docstring.",
                file=sys.stderr,
            )

        chunks = build_chunks(pages)
        relevant = filter_relevant_chunks(chunks)
        if verbose:
            print(f"[info] {len(chunks)} chunks total, {len(relevant)} passed keyword filter", file=sys.stderr)
        if not relevant and chunks:
            print(
                "[warn] 0 chunks matched the keyword filter, but the PDF does contain text. "
                "The document's vocabulary may differ from RELEVANT_KEYWORDS (e.g. abbreviations "
                "like 'WTG', 'H hub', 'Ø rotore'). Try --no-filter to run the LLM on every chunk, "
                "or add the missing terms to RELEVANT_KEYWORDS.",
                file=sys.stderr,
            )

        all_records: list[dict[str, Any]] = []
        for i, chunk in enumerate(relevant, 1):
            if verbose:
                print(f"[info] extracting chunk {i}/{len(relevant)} (pages {chunk.page_start}-{chunk.page_end})", file=sys.stderr)
            try:
                records = extract_from_chunk(chunk, model=model, debug=debug)
            except requests.exceptions.ConnectionError:
                print(
                    "[error] Could not reach Ollama at http://localhost:11434. "
                    "Is Ollama running? Try: `ollama serve` in another terminal, and "
                    f"make sure the model is pulled: `ollama pull {model}`.",
                    file=sys.stderr,
                )
                continue
            except requests.RequestException as e:
                print(f"[warn] LLM call failed for chunk {i}: {e}", file=sys.stderr)
                continue
            all_records.extend(records)

        if verbose:
            print(f"[info] {len(all_records)} raw records before merge, running reduce step", file=sys.stderr)

        return reduce_records(all_records, model=model)
    finally:
        if is_temp:
            try:
                os.remove(local_path)
                if verbose:
                    print(f"[info] cleaned up temp file {local_path}", file=sys.stderr)
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description="Extract wind turbine specs from a PDF using a small local LLM.")
    ap.add_argument("pdf", help="Path to a local PDF, or an http(s) URL to a PDF")
    ap.add_argument("-o", "--output", default="turbines.json", help="Output JSON path")
    ap.add_argument("--model", default="qwen2.5:3b-instruct", help="Ollama model name")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--debug", action="store_true", help="Print raw LLM output per chunk, plus diagnostics")
    ap.add_argument("--no-filter", action="store_true", help="Skip keyword pre-filter, run LLM on every chunk")
    args = ap.parse_args()

    if args.no_filter:
        global filter_relevant_chunks
        filter_relevant_chunks = lambda chunks: chunks  # noqa: E731

    results = process_pdf(args.pdf, model=args.model, verbose=not args.quiet, debug=args.debug)

    if not results:
        print("[warn] no turbine records extracted; writing empty output.", file=sys.stderr)
        new = {}
    else:
        new = {
            key: list(set([value.get(key) for value in results if not value.get(key) is None]))
            for key, value in results[0].items()
        }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(results)} turbine record(s) to {args.output}")


if __name__ == "__main__":
    main()
