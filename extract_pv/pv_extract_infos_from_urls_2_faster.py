"""
pv_extract_infos.py

Extract photovoltaic (PV) plant information from large Italian permitting PDFs
(local path or URL) using a SMALL local LLM served by Ollama.

Output per document:
    surface            float | None   hectares covered by the panels
    number_of_pannels  int | None
    type_parc          "sol" | "flottant" | None
    pannel_type        "fix" | "tracker" | "undefined"   (default: --default-pannel-type)
    battery_storage    bool
    agrivoltaic        bool
    type_agri          "culture" | "elevage" | "culture-elevage" | None
    detail_agri        str | None   (French, e.g. "ovins", "oliviers")

Pipeline (same idea as the wind version):
  1. extract text per page (PyMuPDF), drop headers/footers repeated on many pages
  2. score pages with PV keywords, keep the best ones (+ the following page)
  3. pack pages into chunks, run the LLM on each chunk concurrently (map)
  4. validate each partial answer in Python (types, enums, evidence guards)
  5. merge partial answers deterministically (reduce) -> one record

Usage:
    OLLAMA_NUM_PARALLEL=4 ollama serve
    python pv_extract_infos.py https://va.mite.gov.it/File/Documento/720831 -o pv.json
    python pv_extract_infos.py a.pdf b.pdf --model qwen2.5:7b-instruct --workers 2
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
from typing import Any
from urllib.parse import urlparse

import fitz  # PyMuPDF
import requests
from requests.adapters import HTTPAdapter

# --------------------------------------------------------------------------
# 1. Keyword pre-filter (IT + EN + FR)
# --------------------------------------------------------------------------

RELEVANT_KEYWORDS = [
    # modules / panels
    "moduli fotovoltaici", "modulo fotovoltaico", "pannelli fotovoltaici", "numero totale moduli",
    "numero di moduli", "numero moduli", "numero di pannelli", "n. moduli", "n° moduli",
    "pv modules", "solar panels", "number of modules", "nombre de modules", "nombre de panneaux",
    # surface
    "superficie", "ettari", "area di impianto", "area pannellata", "superficie captante",
    "superficie pannellata", "area recintata", "surface area", "hectares", "superficie totale",
    # type of park
    "impianto fotovoltaico", "parco fotovoltaico", "campo fotovoltaico", "a terra", "galleggiante",
    "flottante", "specchio d'acqua", "bacino", "floating", "ground-mounted", "au sol", "flottant",
    # tracker / fixed
    "inseguitor", "tracker", "monoassiale", "biassiale", "strutture fisse", "struttura fissa",
    "struttura di sostegno", "infissione", "infisse", "fixed tilt", "inclinazione fissa",
    # storage
    "bess", "sistema di accumulo", "sistemi di accumulo", "accumulo elettrochimico",
    "batteria", "batterie", "storage", "stoccaggio",
    # agrivoltaics
    "agrivoltaic", "agro-fotovoltaic", "agrofotovoltaic", "agro fotovoltaic", "pascolo", "pascolamento",
    "ovin", "bovin", "caprin", "allevamento", "apicoltura", "coltivazion", "seminativ", "colture",
    "foraggi", "oliveto", "uliveto", "vigneto", "frutteto", "attività agricola", "attività zootecnica",
    # power (helps locate the technical data sheet page)
    "mwp", "kwp", "potenza di picco", "scheda tecnica", "dati tecnici",
]
KEYWORD_RE = re.compile(
    "|".join(re.escape(k) for k in RELEVANT_KEYWORDS) + r"|\bha\b",
    re.IGNORECASE,
)

# Evidence guards: the LLM may only answer True if the chunk contains such words.
# "accumulo" alone is NOT evidence (it appears as "accumulo di cariche elettrostatiche",
# "accumulo del gas naturale" in boilerplate standards).
BATTERY_RE = re.compile(
    r"\bBESS\b|batteri[ae]|sistem[ai] di accumulo|accumulo elettrochimic|accumulo (?:di )?energia"
    r"|storage|stoccaggio (?:di )?energia|energy storage",
    re.IGNORECASE,
)
AGRI_RE = re.compile(
    r"agri-?\s?volta|agro-?\s?fotovolta|agro-?\s?volta|agrisolar|pascol|apicolt|allevament"
    r"|colture? (?:tra|fra|sotto|all.interno)|coltivazion\w* (?:tra|fra|sotto|all.interno)"
    r"|attività zootecnic|attività agricol\w* (?:integrat|compatibil|consociat)",
    re.IGNORECASE,
)

MAX_CHUNK_CHARS = 6000    # text sent to the LLM per call
MAX_PAGES = 12            # keep at most this many best-scoring pages (before +following page)
CONTEXT_PAGES_AFTER = 1   # also send the page after a hit (tables split across a page break)

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_NUM_CTX = 4096     # prompt ~700 tokens + 6000 chars of IT text (~1800 tokens) + output
OLLAMA_NUM_PREDICT = 300  # the JSON answer is ~100 tokens

DEFAULT_PANNEL_TYPE = "fix"


# --------------------------------------------------------------------------
# 0. Resolve input source: local path or URL
# --------------------------------------------------------------------------

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
}


def is_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def download_pdf(url: str, timeout: int = 60) -> str:
    """Download a PDF to a temp file and return its path. Fails clearly if the server sent HTML."""
    print(f"[info] downloading PDF from {url}", file=sys.stderr)
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, stream=True)
    resp.raise_for_status()

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    total = 0
    with os.fdopen(fd, "wb") as f:
        for block in resp.iter_content(chunk_size=1 << 20):
            f.write(block)
            total += len(block)

    with open(tmp_path, "rb") as f:
        head = f.read(1024).lstrip()
    if not head.startswith(b"%PDF-"):
        os.remove(tmp_path)
        raise RuntimeError(
            f"{url} did not return a PDF (Content-Type={resp.headers.get('Content-Type')!r}, "
            f"final URL={resp.url}, first bytes={head[:40]!r})"
        )
    print(f"[info] downloaded {total / 1024:.1f} KB", file=sys.stderr)
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
    with fitz.open(pdf_path) as doc:
        return [page.get_text("text") for page in doc]


def strip_repeated_lines(pages: list[str]) -> list[str]:
    """Remove running headers/footers (company name, address, VAT number, page numbers)
    that appear on many pages. They carry no information and cost tokens."""
    n = len(pages)
    if n < 5:
        return pages
    counts: Counter[str] = Counter()
    for p in pages:
        counts.update({ln.strip() for ln in p.splitlines() if ln.strip()})
    threshold = max(3, int(0.3 * n))
    drop = {ln for ln, c in counts.items() if c >= threshold}
    cleaned = []
    for p in pages:
        lines = [
            ln.strip() for ln in p.splitlines()
            if ln.strip() and ln.strip() not in drop and not re.fullmatch(r"\d{1,3}", ln.strip())
        ]
        cleaned.append("\n".join(lines))
    return cleaned


def build_chunks(
    pages: list[str],
    use_filter: bool = True,
    max_chars: int = MAX_CHUNK_CHARS,
    max_pages: int = MAX_PAGES,
    pages_after: int = CONTEXT_PAGES_AFTER,
) -> tuple[list[Chunk], int]:
    """Score pages by keyword hits, keep the `max_pages` best (+ following pages),
    pack consecutive pages into chunks of at most `max_chars`."""
    n = len(pages)
    if use_filter:
        scores = [(len(KEYWORD_RE.findall(t)), i) for i, t in enumerate(pages)]
        best = sorted((s for s in scores if s[0] > 0), key=lambda s: (-s[0], s[1]))[:max_pages]
        selected: set[int] = set()
        for _, i in best:
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
            chunks.append(Chunk(
                chunk_id=len(chunks),
                page_start=cur[0][0] + 1,
                page_end=cur[-1][0] + 1,
                text="\n".join(t for _, t in cur),
            ))
        cur, cur_len = [], 0

    prev = None
    for i in selected_pages:
        text = pages[i][:max_chars]
        contiguous = prev is not None and i == prev + 1
        if cur and (not contiguous or cur_len + len(text) > max_chars):
            flush()
        cur.append((i, text))
        cur_len += len(text) + 1
        prev = i
    flush()
    return chunks, len(selected_pages)


# --------------------------------------------------------------------------
# 3. LLM call (Ollama)
# --------------------------------------------------------------------------

# Static instructions first, variable text last -> Ollama can reuse the cached prompt prefix.
MAP_PROMPT_TEMPLATE = """Extract photovoltaic (PV) plant information from this excerpt of an Italian permitting document (Italian or English).

Return ONLY a JSON object with these keys:
  surface_panels_ha (number): area in hectares covered by the PV modules/panels themselves ("superficie moduli", "superficie captante", "area pannellata"). Convert m2 to ha (divide by 10000).
  surface_site_ha (number): total area of the plant/project site in hectares ("superficie complessiva", "area di impianto", "area recintata", "superficie occupata"). Convert m2 to ha.
  number_of_pannels (integer): TOTAL number of PV modules of the whole project ("numero totale moduli"). Not per string, not per sub-field. No thousands separators.
  type_parc ("sol" | "flottant"): "sol" if ground-mounted ("a terra", "impianto a terra", "strutture infisse al suolo"); "flottant" if floating ("galleggiante", "flottante", "su specchio d'acqua", "bacino").
  pannel_type ("fix" | "tracker"): "tracker" if solar trackers are used ("inseguitori", "tracker", "monoassiale", "biassiale"); "fix" if fixed structures ("strutture fisse", "struttura fissa", "inclinazione fissa", tilt with fixed azimuth).
  battery_storage (true): ONLY if a battery / BESS / electrochemical storage system is part of THIS project ("BESS", "sistema di accumulo", "batterie"). The word "accumulo" in other meanings (electrostatic charge, gas, water) does NOT count.
  agrivoltaic (true): ONLY if the project combines PV with real agricultural activity ("agrivoltaico", "agro-fotovoltaico", grazing, crops between or under the panels). Agricultural land alone, or land restoration after works, does NOT count.
  type_agri ("culture" | "elevage" | "culture-elevage"): only if agrivoltaic: crops = "culture", livestock = "elevage", both = "culture-elevage".
  detail_agri (string, in French): only if agrivoltaic: the precise activity, e.g. "ovins", "bovins", "prairie fourragere", "ble", "oliviers", "apiculture".
Rules:
- OMIT any key whose value is not explicitly stated in the text. Never guess, never compute, never invent.
- If nothing about a PV plant is present, return {}.

TEXT:
\"\"\"
<<CHUNK_TEXT>>
\"\"\"

JSON:"""

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


def call_llm_ollama(prompt: str, model: str, timeout: int = 300) -> str:
    resp = get_session().post(
        OLLAMA_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
            "options": {
                "temperature": 0.0,
                "num_ctx": OLLAMA_NUM_CTX,
                "num_predict": OLLAMA_NUM_PREDICT,
            },
        },
        timeout=timeout,
    )
    if not resp.ok:
        raise requests.HTTPError(f"Ollama {resp.status_code}: {resp.text[:300]}", response=resp)
    return resp.json()["response"]


_FENCE_RE = re.compile(r"^```(json)?|```$", re.MULTILINE)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def safe_json_parse(raw: str) -> dict[str, Any]:
    """Recover one JSON object from the model's raw output ({} on failure)."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = _FENCE_RE.sub("", raw.strip()).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        m = _JSON_RE.search(raw)
        if not m:
            return {}
        try:
            parsed = json.loads(m.group())
        except json.JSONDecodeError:
            return {}
    if isinstance(parsed, list):
        parsed = next((x for x in parsed if isinstance(x, dict)), {})
    return parsed if isinstance(parsed, dict) else {}


# --------------------------------------------------------------------------
# 4. Validation of one partial answer
# --------------------------------------------------------------------------

def _to_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d+(?:[.,]\d+)?", str(v).replace(" ", ""))
    return float(m.group().replace(",", ".")) if m else None


def _to_int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    digits = re.sub(r"[^\d]", "", str(v))
    return int(digits) if digits else None


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "oui", "si", "sì")


def _choice(v: Any, allowed: set[str]) -> str | None:
    v = str(v).strip().lower() if v is not None else None
    return v if v in allowed else None


def _surface(v: Any) -> float | None:
    x = _to_float(v)
    if x is None or x <= 0:
        return None
    if x >= 2000:  # implausible in hectares: the model most likely returned m2
        x = x / 10_000
    return round(x, 2)


def normalize_record(rec: dict[str, Any], chunk_text: str) -> dict[str, Any]:
    """Coerce types, check enums, and require textual evidence for the boolean flags.
    Returns a dict that only contains the keys that survived validation."""
    out: dict[str, Any] = {}

    if (x := _surface(rec.get("surface_panels_ha"))) is not None:
        out["surface_panels_ha"] = x
    if (x := _surface(rec.get("surface_site_ha"))) is not None:
        out["surface_site_ha"] = x

    n = _to_int(rec.get("number_of_pannels"))
    if n is not None and n >= 10:
        out["number_of_pannels"] = n

    if (c := _choice(rec.get("type_parc"), {"sol", "flottant"})):
        out["type_parc"] = c
    if (c := _choice(rec.get("pannel_type"), {"fix", "tracker"})):
        out["pannel_type"] = c

    if _to_bool(rec.get("battery_storage", False)) and BATTERY_RE.search(chunk_text):
        out["battery_storage"] = True

    if _to_bool(rec.get("agrivoltaic", False)) and AGRI_RE.search(chunk_text):
        out["agrivoltaic"] = True
        if (c := _choice(rec.get("type_agri"), {"culture", "elevage", "culture-elevage"})):
            out["type_agri"] = c
        detail = rec.get("detail_agri")
        if isinstance(detail, str) and detail.strip():
            out["detail_agri"] = detail.strip()
    return out


def extract_from_chunk(chunk: Chunk, model: str, debug: bool = False) -> dict[str, Any]:
    prompt = MAP_PROMPT_TEMPLATE.replace("<<CHUNK_TEXT>>", chunk.text)
    raw = call_llm_ollama(prompt, model=model)
    rec = normalize_record(safe_json_parse(raw), chunk.text)
    if debug:
        print(f"\n[debug] --- chunk {chunk.chunk_id} (pages {chunk.page_start}-{chunk.page_end}) ---",
              file=sys.stderr)
        print(raw[:600], file=sys.stderr)
        print(f"[debug] validated: {rec}", file=sys.stderr)
    return rec


# --------------------------------------------------------------------------
# 5. Map step (concurrent)
# --------------------------------------------------------------------------

def run_map(chunks: list[Chunk], model: str, workers: int, verbose: bool, debug: bool) -> list[dict[str, Any]]:
    get_session(max(workers, 1))
    aborted = False

    def task(chunk: Chunk) -> dict[str, Any]:
        nonlocal aborted
        if aborted:
            return {}
        try:
            rec = extract_from_chunk(chunk, model=model, debug=debug)
        except requests.exceptions.ConnectionError:
            if not aborted:
                aborted = True
                print(f"[error] Could not reach Ollama at {OLLAMA_URL}. "
                      f"Run `ollama serve` and `ollama pull {model}`.", file=sys.stderr)
            return {}
        except requests.RequestException as e:
            print(f"[warn] LLM call failed for chunk {chunk.chunk_id} "
                  f"(pages {chunk.page_start}-{chunk.page_end}): {e}", file=sys.stderr)
            return {}
        if verbose:
            print(f"[info] done chunk {chunk.chunk_id} (pages {chunk.page_start}-{chunk.page_end}): "
                  f"{sorted(rec)}", file=sys.stderr)
        return rec

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        return [r for r in pool.map(task, chunks) if r]


# --------------------------------------------------------------------------
# 6. Reduce step: one record per document
# --------------------------------------------------------------------------

def _most_common(values: list[Any], tie_break=max) -> Any:
    """Most frequent value; on a tie, apply tie_break (e.g. max) to the tied values."""
    if not values:
        return None
    counts = Counter(values)
    top = max(counts.values())
    return tie_break(v for v, c in counts.items() if c == top)


def merge_records(records: list[dict[str, Any]], default_pannel_type: str = DEFAULT_PANNEL_TYPE) -> dict[str, Any]:
    def vals(key: str) -> list[Any]:
        return [r[key] for r in records if key in r]

    surface_panels = _most_common(vals("surface_panels_ha"))
    surface_site = _most_common(vals("surface_site_ha"))

    types_agri = set(vals("type_agri"))
    if "culture-elevage" in types_agri or {"culture", "elevage"} <= types_agri:
        type_agri = "culture-elevage"
    else:
        type_agri = next(iter(types_agri), None)

    details = list(dict.fromkeys(d.lower() for d in vals("detail_agri")))
    agrivoltaic = any(r.get("agrivoltaic") for r in records)

    return {
        # panel area if stated, otherwise the total site area
        "surface": surface_panels if surface_panels is not None else surface_site,
        "number_of_pannels": _most_common(vals("number_of_pannels")),
        "type_parc": _most_common(vals("type_parc"), tie_break=min),   # "flottant" < "sol"
        "pannel_type": _most_common(vals("pannel_type"), tie_break=max) or default_pannel_type,  # "tracker" > "fix"
        "battery_storage": any(r.get("battery_storage") for r in records),
        "agrivoltaic": agrivoltaic,
        "type_agri": type_agri if agrivoltaic else None,
        "detail_agri": ", ".join(details) if agrivoltaic and details else None,
    }


# --------------------------------------------------------------------------
# 7. Orchestration
# --------------------------------------------------------------------------

def process_pdf(
    source: str,
    model: str = "qwen2.5:3b-instruct",
    verbose: bool = True,
    debug: bool = False,
    workers: int = 4,
    use_filter: bool = True,
    default_pannel_type: str = DEFAULT_PANNEL_TYPE,
) -> dict[str, Any]:
    local_path, is_temp = resolve_pdf_source(source)
    try:
        pages = extract_pages(local_path)
        total_chars = sum(len(p) for p in pages)
        if verbose:
            print(f"[info] {source}: {len(pages)} pages, {total_chars} characters", file=sys.stderr)
        if total_chars < 200 * max(len(pages), 1):
            print("[warn] Very little text per page: the PDF is probably scanned and needs OCR.",
                  file=sys.stderr)

        pages = strip_repeated_lines(pages)
        chunks, n_sel = build_chunks(pages, use_filter=use_filter)
        if verbose:
            print(f"[info] {n_sel}/{len(pages)} pages selected -> {len(chunks)} chunk(s)", file=sys.stderr)
        if not chunks and pages:
            print("[warn] 0 pages matched the keyword filter. Try --no-filter or add terms to "
                  "RELEVANT_KEYWORDS.", file=sys.stderr)

        records = run_map(chunks, model, workers, verbose, debug)
        if verbose:
            print(f"[info] {len(records)} partial record(s), merging", file=sys.stderr)
        return merge_records(records, default_pannel_type)
    finally:
        if is_temp:
            try:
                os.remove(local_path)
            except OSError:
                pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract PV plant information from PDFs with a small local LLM.")
    ap.add_argument("sources", nargs="+", help="Local PDF path(s) or http(s) URL(s)")
    ap.add_argument("-o", "--output", default="pv_infos.json", help="Output JSON path")
    ap.add_argument("--model", default="qwen2.5:3b-instruct", help="Ollama model name")
    ap.add_argument("-w", "--workers", type=int, default=4,
                    help="Parallel LLM requests (set OLLAMA_NUM_PARALLEL to match)")
    ap.add_argument("--default-pannel-type", choices=["fix", "undefined"], default=DEFAULT_PANNEL_TYPE,
                    help="Value used when the document does not say fixed or tracker")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--debug", action="store_true", help="Print raw LLM output per chunk")
    ap.add_argument("--no-filter", action="store_true", help="Skip the keyword pre-filter")
    args = ap.parse_args()

    results = []
    for src in args.sources:
        try:
            info = process_pdf(
                src,
                model=args.model,
                verbose=not args.quiet,
                debug=args.debug,
                workers=args.workers,
                use_filter=not args.no_filter,
                default_pannel_type=args.default_pannel_type,
            )
        except Exception as e:  # keep going with the other documents
            print(f"[error] {src}: {e}", file=sys.stderr)
            continue
        results.append({"source": src, **info})
        print(json.dumps(info, ensure_ascii=False, indent=2))

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(results)} record(s) to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
