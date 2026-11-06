"""
wind_turbine_extractor.py
Extract wind-turbine specs (count, hub height, rotor diameter, blade length,
tip height, model, manufacturer, rated power) from large Italian wind-farm
PDFs using a SMALL local LLM.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any

import fitz  # PyMuPDF
import requests

# --------------------------------------------------------------------------
# 1. Keyword pre-filter (EN + IT) — cheap way to skip irrelevant pages
# --------------------------------------------------------------------------
RELEVANT_KEYWORDS = [
    # English
    "turbine ", "rotor diameter ", "hub height ", "blade length ", "tip height ",
    "rated power ", "nameplate capacity ", "swept area ", "wind farm layout ",
    "length of blades ", "blade ",
    # Italian
    "aerogeneratore ", "aerogeneratori ", "turbina eolica ", "turbine eoliche ",
    "altezza al mozzo ", "altezza mozzo ", "diametro rotore ", "diametro del rotore ",
    "lunghezza pala ", "lunghezza delle pale ", "lunghezza della pala ", "pala ", "pale ",
    "altezza massima ", "altezza totale ",
    "potenza nominale ", "potenza installata ", "numero di aerogeneratori ",
    "impianto eolico ", "torre eolica ", "pale eoliche ",
]

CHUNK_SIZE_PAGES = 3       # pages per chunk
CHUNK_OVERLAP_PAGES = 1    # overlap so tables spanning a page break survive

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
      "blade_length_m": number or null,      // Length of the blades
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
{chunk_text}
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

def safe_json_parse(raw: str) -> list[dict[str, Any]]:
    """
    Recover the turbine list from the model's raw output.
    Expected shape: { "turbines": [ {...}, ... ]}
    """
    raw = raw.strip()
    # Clean up markdown code blocks if the model accidentally adds them
    raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
    
    # Find the outermost JSON object or array
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
        # Fallback: A dict that isn't the wrapper but looks like a single turbine record
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
        print(f"\n[debug] --- chunk {chunk.chunk_id} (pages {chunk.page_start}-{chunk.page_end}) raw LLM output ---", file=sys.stderr)
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
    pages = extract_pages(pdf_path)
    total_chars = sum(len(p) for p in pages)
    
    if verbose:
        print(f"[info] {pdf_path}: {len(pages)} pages extracted, {total_chars} characters total", file=sys.stderr)
        
    if total_chars < 200 * max(len(pages), 1):
        print(
            "[warn] Very little text extracted per page. This PDF is likely scanned "
            "(image-only) and needs OCR before this pipeline will find anything.",
            file=sys.stderr,
        )
        
    chunks = build_chunks(pages)
    relevant = filter_relevant_chunks(chunks)
    
    if verbose:
        print(f"[info] {len(chunks)} chunks total, {len(relevant)} passed keyword filter", file=sys.stderr)
        
    if not relevant and chunks:
        print(
            "[warn] 0 chunks matched the keyword filter, but the PDF does contain text. "
            "Try --no-filter to run the LLM on every chunk.",
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
                f"[error] Could not reach Ollama. Is it running? Make sure the model is pulled: `ollama pull {model}`.",
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

def main():
    ap = argparse.ArgumentParser(description="Extract wind turbine specs from a PDF using a small local LLM.")
    ap.add_argument("pdf", help="Path to the input PDF")
    ap.add_argument("-o", "--output", default="turbines.json", help="Output JSON path")
    ap.add_argument("--model", default="qwen2.5:3b-instruct", help="Ollama model name")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--debug", action="store_true", help="Print raw LLM output per chunk")
    ap.add_argument("--no-filter", action="store_true", help="Skip keyword pre-filter")
    args = ap.parse_args()
    
    if args.no_filter:
        global filter_relevant_chunks
        filter_relevant_chunks = lambda chunks: chunks  # noqa: E731
        
    results = process_pdf(args.pdf, model=args.model, verbose=not args.quiet, debug=args.debug)
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    print(f"Wrote {len(results)} turbine record(s) to {args.output}")

if __name__ == "__main__":
    main()
