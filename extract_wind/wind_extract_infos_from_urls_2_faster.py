"""
wind_turbine_extractor.py  (faster version)

Extract wind-turbine specs (count, hub height, rotor diameter, blade length,
tip height, model, manufacturer, rated power) from large Italian wind-farm
PDFs using a SMALL local LLM served by Ollama.

Speed-ups compared to the original:
  * Map step runs concurrently (--workers). Start Ollama with
    OLLAMA_NUM_PARALLEL=<workers> so the server actually handles them in parallel.
  * Chunks are built from *relevant pages only* (hit page + following page),
    packed up to MAX_CHUNK_CHARS. No more 3-page windows with 1-page overlap
    that were then silently cut at 6000 chars.
  * Shorter prompt, static part first (prefix/KV-cache friendly), model asked
    to OMIT null fields -> far fewer generated tokens (generation is the
    slow part).
  * Explicit num_ctx / num_predict / keep_alive: no silent context truncation,
    no runaway generations, model stays loaded between calls.
  * One pooled HTTP session (keep-alive) instead of a new connection per call.
  * Reduce step is done deterministically in Python by default (instant);
    the LLM merge is still available with --llm-reduce.

Usage:
    OLLAMA_NUM_PARALLEL=4 ollama serve
    python wind_turbine_extractor.py input.pdf -o turbines.json --workers 4
    python wind_turbine_extractor.py input.pdf --model phi3:mini --llm-reduce
    
    # phi-4-mini
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import fitz  # PyMuPDF
import requests
from requests.adapters import HTTPAdapter

# --------------------------------------------------------------------------
# 1. Keyword pre-filter (EN + FR + IT)
# --------------------------------------------------------------------------

RELEVANT_KEYWORDS = [
    # English
    "turbine", "rotor diameter", "hub height", "blade length", "tip height",
    "rated power", "nameplate capacity", "swept area", "wind farm layout",
    "ground clearance", "blade tip clearance", "minimum ground clearance",
    # French
    "garde au sol", "hauteur libre", "distance minimale entre la pale et le sol",
    # Italian
    "aerogeneratore", "aerogeneratori", "turbina eolica", "turbine eoliche",
    "altezza al mozzo", "altezza mozzo", "diametro rotore", "diametro del rotore",
    "lunghezza pala", "lunghezza delle pale", "altezza massima", "altezza totale",
    "potenza nominale", "potenza installata", "numero di aerogeneratori",
    "impianto eolico", "torre eolica", "pale eoliche",
    "franco minimo", "distanza minima pala", "distanza minima delle pale dal suolo",
    "altezza minima delle pale dal suolo", "distanza pala-suolo", "franco da terra",
]

# Compiled once at import time (was recompiled on every call before).
KEYWORD_RE = re.compile("|".join(re.escape(k) for k in RELEVANT_KEYWORDS), re.IGNORECASE)

MAX_CHUNK_CHARS = 6000   # text sent to the LLM per call
CONTEXT_PAGES_AFTER = 1  # also send the page after a hit (tables split across a page break)

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_NUM_CTX = 4096    # 6000 chars of IT/EN text + prompt ~ 2.5-3k tokens
OLLAMA_NUM_PREDICT = 700 # hard cap on output tokens


# --------------------------------------------------------------------------
# 0. Resolve input source: local path or URL
# --------------------------------------------------------------------------

def is_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def download_pdf(url: str, timeout: int = 60) -> str:
    """Download a PDF from a URL to a temp file and return the local path."""
    print(f"[info] downloading PDF from {url}", file=sys.stderr)
    resp = requests.get(url, timeout=timeout, stream=True)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
        print(
            f"[warn] response Content-Type is '{content_type}', not obviously a PDF. "
            "Continuing anyway.",
            file=sys.stderr,
        )

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    total_bytes = 0
    with os.fdopen(fd, "wb") as f:
        for block in resp.iter_content(chunk_size=1 << 20):  # 1 MiB blocks (was 8 KiB)
            f.write(block)
            total_bytes += len(block)

    print(f"[info] downloaded {total_bytes / 1024:.1f} KB to {tmp_path}", file=sys.stderr)
    return tmp_path


def resolve_pdf_source(source: str) -> tuple[str, bool]:
    """Return (local_pdf_path, is_temp_file)."""
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
    with fitz.open(pdf_path) as doc:
        return [page.get_text("text") for page in doc]


def build_chunks(
    pages: list[str],
    use_filter: bool = True,
    max_chars: int = MAX_CHUNK_CHARS,
    pages_after: int = CONTEXT_PAGES_AFTER,
) -> tuple[list[Chunk], int]:
    """
    Select relevant pages (keyword hit + `pages_after` following pages), then
    pack consecutive selected pages into chunks of at most `max_chars`.
    Returns (chunks, number_of_selected_pages).
    """
    n = len(pages)
    if use_filter:
        selected: set[int] = set()
        for i, text in enumerate(pages):
            if KEYWORD_RE.search(text):
                selected.update(range(i, min(i + 1 + pages_after, n)))
        selected_pages = sorted(selected)
    else:
        selected_pages = list(range(n))

    chunks: list[Chunk] = []
    cur: list[tuple[int, str]] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur, cur_len
        if cur:
            chunks.append(
                Chunk(
                    chunk_id=len(chunks),
                    page_start=cur[0][0] + 1,
                    page_end=cur[-1][0] + 1,
                    text="\n".join(t for _, t in cur),
                )
            )
        cur, cur_len = [], 0

    prev = None
    for i in selected_pages:
        text = pages[i][:max_chars]  # a single huge page is truncated
        contiguous = prev is not None and i == prev + 1
        if cur and (not contiguous or cur_len + len(text) > max_chars):
            flush()
        cur.append((i, text))
        cur_len += len(text) + 1
        prev = i
    flush()
    return chunks, len(selected_pages)


# --------------------------------------------------------------------------
# 3. LLM call (Ollama backend)
# --------------------------------------------------------------------------

# Static instructions first, variable text last -> Ollama can reuse the cached
# prompt prefix between calls handled by the same slot.
MAP_PROMPT_TEMPLATE = """Extract wind-turbine technical specs from this Italian wind-farm permitting document excerpt (Italian or English).

Return ONLY a JSON object: {{"turbines": [ {{...}}, ... ]}}
Each turbine object may contain these keys:
  turbine_model (string, e.g. "Vestas V150-4.2 MW"), manufacturer (string),
  number_of_turbines (integer, count of this type/group), rated_power_MW (number),
  hub_height_m (number), rotor_diameter_m (number), blade_length_m (number),
  total_tip_height_m (number, max height incl. blade tip),
  ground_clearance_m (number, min distance blade tip <-> ground; IT "franco minimo"/"distanza minima pala-suolo"; FR "garde au sol"),
  source_page_range (string, copy the page range given below).
Rules:
- OMIT any key whose value is not explicitly stated in the text. Never guess or compute.
- One object per distinct turbine model/group.
- If nothing turbine-related is present, return {{"turbines": []}}.

Page range: {page_range}
TEXT:
\"\"\"
{chunk_text}
\"\"\"

JSON:"""

REDUCE_PROMPT_TEMPLATE = """You are given several JSON extractions of wind-turbine records,
independently extracted from different sections of the same document. The same
turbine model may appear more than once with partially overlapping fields.

Merge them into one entry per distinct turbine model/group, combining fields and
preferring the most specific / most complete non-null value. Keep the schema
fields exactly as given. Return ONLY a JSON object {{"turbines": [...]}}, no prose.

PARTIAL EXTRACTIONS:
{all_json}

Merged JSON:"""


_session: requests.Session | None = None


def get_session(pool_size: int = 8) -> requests.Session:
    """One pooled keep-alive session shared by all threads."""
    global _session
    if _session is None:
        s = requests.Session()
        adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _session = s
    return _session


def call_llm_ollama(prompt: str, model: str = "qwen2.5:3b-instruct", timeout: int = 300) -> str:
    """Call a small local model via Ollama and return raw text output."""
    resp = get_session().post(
        OLLAMA_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": "30m",  # don't unload/reload the model between runs
            "options": {
                "temperature": 0.0,
                "num_ctx": OLLAMA_NUM_CTX,
                "num_predict": OLLAMA_NUM_PREDICT,
            },
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["response"]


@lru_cache(maxsize=1)
def _load_transformers(model_name: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name, torch_dtype=torch.bfloat16, device_map="auto"
    )
    return tok, model


def call_llm_transformers(prompt: str, model_name: str = "Qwen/Qwen2.5-1.5B-Instruct") -> str:
    """Alternative HF backend. The model is now loaded once and cached."""
    tok, model = _load_transformers(model_name)
    messages = [{"role": "user", "content": prompt}]
    inputs = tok.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt"
    ).to(model.device)
    out = model.generate(inputs, max_new_tokens=OLLAMA_NUM_PREDICT, do_sample=False)
    return tok.decode(out[0][inputs.shape[1]:], skip_special_tokens=True)


EXPECTED_FIELDS = {
    "turbine_model", "manufacturer", "number_of_turbines", "rated_power_MW",
    "hub_height_m", "rotor_diameter_m", "blade_length_m", "total_tip_height_m",
    "ground_clearance_m",
}
_FENCE_RE = re.compile(r"^```(json)?|```$", re.MULTILINE)
_JSON_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def safe_json_parse(raw: str) -> list[dict[str, Any]]:
    """Recover the turbine list from the model's raw output."""
    raw = _FENCE_RE.sub("", raw.strip()).strip()
    try:
        parsed = json.loads(raw)  # fast path: format=json usually gives clean JSON
    except json.JSONDecodeError:
        match = _JSON_RE.search(raw)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

    if isinstance(parsed, dict):
        if isinstance(parsed.get("turbines"), list):
            return [r for r in parsed["turbines"] if isinstance(r, dict)]
        return [parsed] if EXPECTED_FIELDS & parsed.keys() else []
    if isinstance(parsed, list):
        return [r for r in parsed if isinstance(r, dict)]
    return []


# --------------------------------------------------------------------------
# 4. Map step (concurrent)
# --------------------------------------------------------------------------

def extract_from_chunk(chunk: Chunk, model: str, debug: bool = False) -> list[dict[str, Any]]:
    prompt = MAP_PROMPT_TEMPLATE.format(
        page_range=f"{chunk.page_start}-{chunk.page_end}",
        chunk_text=chunk.text,
    )
    raw = call_llm_ollama(prompt, model=model)
    parsed = safe_json_parse(raw)
    if debug:
        print(f"\n[debug] --- chunk {chunk.chunk_id} (pages {chunk.page_start}-{chunk.page_end}) raw LLM output ---",
              file=sys.stderr)
        print(raw[:1000], file=sys.stderr)
        print(f"[debug] parsed {len(parsed)} record(s) from this chunk", file=sys.stderr)
    return parsed


def run_map(chunks: list[Chunk], model: str, workers: int, verbose: bool, debug: bool) -> list[dict[str, Any]]:
    get_session(max(workers, 1))
    aborted = False

    def task(chunk: Chunk) -> list[dict[str, Any]]:
        nonlocal aborted
        if aborted:
            return []
        try:
            recs = extract_from_chunk(chunk, model=model, debug=debug)
        except requests.exceptions.ConnectionError:
            if not aborted:
                aborted = True
                print(
                    "[error] Could not reach Ollama at http://localhost:11434. "
                    f"Run `ollama serve` and `ollama pull {model}`.",
                    file=sys.stderr,
                )
            return []
        except requests.RequestException as e:
            print(f"[warn] LLM call failed for chunk {chunk.chunk_id} "
                  f"(pages {chunk.page_start}-{chunk.page_end}): {e}", file=sys.stderr)
            return []
        if verbose:
            print(f"[info] done chunk {chunk.chunk_id} (pages {chunk.page_start}-{chunk.page_end}): "
                  f"{len(recs)} record(s)", file=sys.stderr)
        return recs

    all_records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        for recs in pool.map(task, chunks):  # map() preserves chunk order
            all_records.extend(recs)
    return all_records


# --------------------------------------------------------------------------
# 5. Reduce step
# --------------------------------------------------------------------------

def _record_key(r: dict[str, Any]) -> tuple:
    model = r.get("turbine_model")
    if model:
        return ("model", re.sub(r"[^a-z0-9.]", "", str(model).lower().replace("mw", "")))
    if r.get("hub_height_m") is not None or r.get("rotor_diameter_m") is not None:
        return ("dims", r.get("hub_height_m"), r.get("rotor_diameter_m"))
    return ("unknown",)


def reduce_records_local(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic merge: group by model (or dimensions), keep the most
    frequent non-null value per field. Instant, no LLM call."""
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for r in records:
        groups.setdefault(_record_key(r), []).append(r)

    merged: list[dict[str, Any]] = []
    for recs in groups.values():
        out: dict[str, Any] = {}
        for key in dict.fromkeys(k for r in recs for k in r):
            vals = [r[key] for r in recs if r.get(key) is not None]
            if not vals:
                continue
            if key == "source_page_range":
                out[key] = ", ".join(dict.fromkeys(str(v) for v in vals))
                continue
            counts = Counter(json.dumps(v, sort_keys=True) for v in vals)
            best = counts.most_common(1)[0][0]
            out[key] = json.loads(best)
        merged.append(out)
    return merged


def reduce_records_llm(all_records: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    if len(all_records) <= 1:
        return all_records
    # Compact JSON (no indent) = fewer prompt tokens.
    prompt = REDUCE_PROMPT_TEMPLATE.format(all_json=json.dumps(all_records, ensure_ascii=False))
    raw = call_llm_ollama(prompt, model=model)
    merged = safe_json_parse(raw)
    return merged if merged else all_records


# --------------------------------------------------------------------------
# 6. Orchestration
# --------------------------------------------------------------------------

def process_pdf(
    pdf_path: str,
    model: str = "qwen2.5:3b-instruct",
    verbose: bool = True,
    debug: bool = False,
    workers: int = 4,
    use_filter: bool = True,
    llm_reduce: bool = False,
) -> list[dict[str, Any]]:
    local_path, is_temp = resolve_pdf_source(pdf_path)
    try:
        pages = extract_pages(local_path)
        total_chars = sum(len(p) for p in pages)
        if verbose:
            print(f"[info] {pdf_path}: {len(pages)} pages, {total_chars} characters", file=sys.stderr)
        if total_chars < 200 * max(len(pages), 1):
            print(
                "[warn] Very little text extracted per page. This PDF is likely scanned "
                "(image-only) and needs OCR before this pipeline will find anything.",
                file=sys.stderr,
            )

        chunks, n_pages_sel = build_chunks(pages, use_filter=use_filter)
        if verbose:
            print(f"[info] {n_pages_sel}/{len(pages)} pages selected -> {len(chunks)} chunk(s)", file=sys.stderr)
        if not chunks and pages:
            print(
                "[warn] 0 pages matched the keyword filter. The vocabulary may differ from "
                "RELEVANT_KEYWORDS (e.g. 'WTG', 'H hub', 'Ø rotore'). Try --no-filter or add terms.",
                file=sys.stderr,
            )

        all_records = run_map(chunks, model, workers, verbose, debug)
        if verbose:
            print(f"[info] {len(all_records)} raw records, merging "
                  f"({'LLM' if llm_reduce else 'local'})", file=sys.stderr)

        if llm_reduce:
            return reduce_records_llm(all_records, model)
        return reduce_records_local(all_records)
    finally:
        if is_temp:
            try:
                os.remove(local_path)
            except OSError:
                pass


def summarize(results: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """key -> list of unique non-null values (union of keys over ALL records,
    order preserved, works with unhashable values)."""
    out: dict[str, list[Any]] = {}
    for rec in results:
        for key, value in rec.items():
            if value is None:
                continue
            bucket = out.setdefault(key, [])
            if value not in bucket:
                bucket.append(value)
    return out


def main():
    ap = argparse.ArgumentParser(description="Extract wind turbine specs from a PDF using a small local LLM.")
    ap.add_argument("pdf", help="Path to a local PDF, or an http(s) URL to a PDF")
    ap.add_argument("-o", "--output", default="turbines.json", help="Output JSON path")
    ap.add_argument("--model", default="qwen2.5:3b-instruct", help="Ollama model name")
    ap.add_argument("-w", "--workers", type=int, default=4,
                    help="Parallel LLM requests (set OLLAMA_NUM_PARALLEL to match)")
    ap.add_argument("--llm-reduce", action="store_true", help="Merge records with an LLM call (slower)")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--debug", action="store_true", help="Print raw LLM output per chunk")
    ap.add_argument("--no-filter", action="store_true", help="Skip keyword pre-filter, run LLM on every page")
    args = ap.parse_args()

    results = process_pdf(
        args.pdf,
        model=args.model,
        verbose=not args.quiet,
        debug=args.debug,
        workers=args.workers,
        use_filter=not args.no_filter,
        llm_reduce=args.llm_reduce,
    )

    if not results:
        print("[warn] no turbine records extracted; writing empty output.", file=sys.stderr)
    new = summarize(results)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(results)} turbine record(s) to {args.output}")


if __name__ == "__main__":
    main()
