from __future__ import annotations

import argparse
import json
import re
import sys
import copy
from dataclasses import dataclass, field
from typing import Any

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
# 3. LLM call (Ollama backend & Optimized Transformers)
# --------------------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"

# UPDATED: Schema constraints modified to accept strings/integers/numbers OR list formats
EXTRACTION_SCHEMA_HINT = """
Return ONLY a JSON object of this exact shape (no prose, no markdown fences):
{
  "turbines": [
    {
      "turbine_model": string or array of strings or null,       // e.g. ["Vestas V150-4.2 MW"] or "Vestas V150"
      "manufacturer": string or array of strings or null,        // e.g. ["Vestas", "Enercon"] or "Vestas"
      "number_of_turbines": integer or array of integers or null, // e.g. [10, 5] or 15
      "rated_power_MW": number or array of numbers or null,      // e.g. [4.2, 4.0] or 4.2
      "hub_height_m": number or null,
      "rotor_diameter_m": number or null,
      "blade_length_m": number or null,
      "total_tip_height_m": number or null,                      // max height incl. blade tip
      "source_page_range": string                                // e.g. "12-14", copy from context given
    }
  ]
}
Rules:
- turbine_model, manufacturer, number_of_turbines, and rated_power_MW can be represented as lists/arrays if multiple discrete variations are grouped together or declared in text.
- Only include a field value if it is explicitly stated in the text. Otherwise use null.
- Do not guess or compute missing values.
- If multiple separate turbine models/groups are described across different records, add multiple objects to "turbines".
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
turbine data may appear more than once with partially overlapping fields.

Merge these into a single clean result: one entry per distinct turbine
model/group config. When the same model or group appears multiple times, combine the fields,
preferring the most specific / most complete non-null value. Ensure lists/arrays are preserved if multiple options exist. Keep the schema
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


# Global variables to prevent reloading the model on every single token iteration loop
_GLOBAL_MODEL = None
_GLOBAL_TOKENIZER = None

def call_llm_transformers(prompt: str, model_name: str = "Qwen/Qwen2.5-1.5B-Instruct") -> str:
    """
    Optimized alternative backend using Hugging Face transformers directly.
    Caches the model structure globally to eliminate runtime setup bottlenecks.
    """
    global _GLOBAL_MODEL, _GLOBAL_TOKENIZER
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if _GLOBAL_MODEL is None or _GLOBAL_TOKENIZER is None:
        _GLOBAL_TOKENIZER = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        _GLOBAL_MODEL = AutoModelForCausalLM.from_pretrained(
            model_name, 
            torch_dtype=torch.bfloat16, 
            device_map="auto",
            trust_remote_code=True
        )
        _GLOBAL_MODEL.eval()  # Freeze graph configurations for dynamic execution

    messages = [{"role": "user", "content": prompt}]
    inputs = _GLOBAL_TOKENIZER.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to(_GLOBAL_MODEL.device)
    
    with torch.inference_mode():  # Faster throughput than standard torch.no_grad()
        out = _GLOBAL_MODEL.generate(
            inputs, 
            max_new_tokens=1000, 
            do_sample=False, 
            temperature=0.0,
            use_cache=True
        )
    return _GLOBAL_TOKENIZER.decode(out[0][inputs.shape[1]:], skip_special_tokens=True)


def safe_json_parse(raw: str) -> dict[str, Any]:
    """Recover the JSON object safely from raw text string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Regex fallback query string in case markdown elements leaked through
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {"turbines": []}

# --------------------------------------------------------------------------
# 4. Core Pipeline Execution
# --------------------------------------------------------------------------

def process_wind_farm_pdf(pdf_path: str, use_transformers: bool = False, model_name: str = "qwen2.5:3b-instruct") -> dict[str, Any]:
    print("Estrazione del testo dal file PDF...")
    pages = extract_pages(pdf_path)
    
    print("Creazione dei chunk di testo...")
    chunks = build_chunks(pages)
    
    print("Filtraggio delle pagine rilevanti con parole chiave...")
    relevant_chunks = filter_relevant_chunks(chunks)
    print(f"Trovati {len(relevant_chunks)} chunk rilevanti su {len(chunks)} totali.")
    
    partial_extractions = []
    
    # --- Phase 1: MAP ---
    for c in relevant_chunks:
        page_range_str = f"{c.page_start}-{c.page_end}"
        print(f"Elaborazione pagine: {page_range_str}...")
        
        prompt = MAP_PROMPT_TEMPLATE.format(
            schema=EXTRACTION_SCHEMA_HINT,
            page_range=page_range_str,
            chunk_text=c.text
        )
        
        if use_transformers:
            raw_output = call_llm_transformers(prompt, model_name=model_name)
        else:
            raw_output = call_llm_ollama(prompt, model=model_name)
            
        data = safe_json_parse(raw_output)
        if "turbines" in data and data["turbines"]:
            partial_extractions.extend(data["turbines"])
            
    if not partial_extractions:
        return {"turbines": []}
        
    # --- Phase 2: REDUCE ---
    print("\nFase finale: Combinazione e riduzione dei dati estratti...")
    reduce_prompt = REDUCE_PROMPT_TEMPLATE.format(
        all_json=json.dumps({"turbines": partial_extractions}, indent=2)
    )
    
    if use_transformers:
        final_output = call_llm_transformers(reduce_prompt, model_name=model_name)
    else:
        final_output = call_llm_ollama(reduce_prompt, model=model_name)
        
    return safe_json_parse(final_output)

# --- Example Driver Execution Context ---
# --- Example Driver Execution Context ---
if __name__ == "__main__":
    # Test execution stub representing typical usage configurations
    # Replace 'input_document.pdf' with your actual PDF file path
    filename = (
    	"/home/kathleen/90_DATA_PREPROCESS/italy_poc"
    	"/output/documents"
    	"/10009"
    	"/10009_030-12_04-RelazioneTecnicoDescrittiva.pdf"
    )
    try:
        pipeline_output = process_wind_farm_pdf(filename)
        print("\n================ FINAL COMPILED RESULT ================")
        print(json.dumps(pipeline_output, indent=4, ensure_ascii=False))
    except Exception as e:
        print(f"An error occurred during pipeline execution: {e}")

