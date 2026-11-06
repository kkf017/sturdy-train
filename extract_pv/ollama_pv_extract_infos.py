"""
Module to download and store pdfs.
"""
import os
import io
import requests
from requests.exceptions import (
	HTTPError, 
	ConnectionError, 
	Timeout, 
	RequestException
)
from pypdf import PdfReader

URL = (
	"https://va.mite.gov.it/File/Documento/720831"
)

class RequestHTTPS:
    ### Class to execute request HTTPS.###

    def __init__(self):
        ### Initialize the request class.
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3"
        }
    
    def request_get(self, url: str, timeout_seconds: int = 60) -> bytes | None:
        ### Function to get https request.####
        try:
            response = requests.get(
            	url, 
            	headers=self.headers, 
            	timeout=timeout_seconds
            )
            response.raise_for_status()
            return response.content
        except (HTTPError, ConnectionError, Timeout, RequestException) as err:
            print(f"Failed to fetch PDF. {err}")
            return None

class FileDownloaderPdf:
    ### Class to get and store pdfs.###

    def __init__(self):
        ### Initialize the file downloader.
        self.connector_https = RequestHTTPS()

    def get_and_store_pdf(self,) -> None:
        ### Function to get and store pdf from url.
        pass
        # 3. Open a local file in 'write binary' (wb) mode and save the content
        # with open(output_path, "wb") as file:
        #     file.write(response.content)

    def get_pdf_from_url(self, url: str) -> str | None:
        ### Function to get pdf from url.
        response = self.connector_https.request_get(url=url)
        
        if response is None:
            return None
            
        pdf_file = io.BytesIO(response)
        reader = PdfReader(pdf_file)
        
        text = ""
        for page in reader.pages:
            txt = page.extract_text()
            if txt:
                text += txt + "\n"
        return text

######################################################################
import json
import re
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:3b-instruct"

SYSTEM_PROMPT = """You extract structured information from Italian documents about photovoltaic (PV) parks.
Return ONLY a valid JSON object, with no explanation, no markdown, no code fences.

JSON schema (use exactly these keys):
{
  "surface": float | null,
  "number_of_pannels": int | null,
  "type_parc": "sol" | "flottant" | null,
  "pannel_type": "fix" | "tracker" | "undefined",
  "battery_storage": true | false,
  "agrivoltaic": true | false,
  "type_agri": "culture" | "elevage" | "culture-elevage" | null,
  "detail_agri": string | null
}

Field rules:
- surface: area in HECTARES covered by the PV panels (e.g. "superficie occupata dai moduli", "area pannellata",
  "superficie captante"). Convert m² to ha (divide by 10 000). If only the total site area ("superficie
  complessiva / dell'area di progetto") is given and no panel area, use that value. Number only, no unit.
- number_of_pannels: total number of PV modules ("moduli fotovoltaici", "pannelli", "moduli"). Integer, no
  separators. If several numbers appear, take the total for the whole project.
- type_parc: "sol" for ground-mounted ("a terra", "impianto a terra"); "flottant" for floating
  ("galleggiante", "flottante", "su specchio d'acqua", "bacino").
- pannel_type: "tracker" if solar trackers are mentioned ("inseguitori solari", "tracker", "ad inseguimento
  monoassiale", "biassiale"); "fix" if fixed structures ("strutture fisse", "fisso", "inclinazione fissa");
  "undefined" if nothing is said.
- battery_storage: true only if batteries or storage are part of the project ("sistema di accumulo", "BESS",
  "batterie", "storage elettrochimico"). Otherwise false.
- agrivoltaic: true if the project combines PV with agricultural activity ("agrivoltaico", "agro-fotovoltaico",
  "attività agricola", "pascolo", "coltivazione tra le file"). Otherwise false.
- type_agri: only if agrivoltaic is true: "culture" (crops), "elevage" (livestock, e.g. "pascolo ovino",
  "allevamento"), or "culture-elevage" (both). Otherwise null.
- detail_agri: only if agrivoltaic is true: precise activity in French (e.g. "ovins", "prairie fourragère",
  "blé", "oliviers", "apiculture"). Otherwise null.

If a value is not stated in the text, use null (or the default given above). Never invent values.
"""

# SYSTEM_PROMPT: reuse yours, without the "/no_think" line

SCHEMA = {
    "type": "object",
    "properties": {
        "surface": {"type": ["number", "null"]},
        "number_of_pannels": {"type": ["integer", "null"]},
        "type_parc": {"enum": ["sol", "flottant", None]},
        "pannel_type": {"enum": ["fix", "tracker", "undefined"]},
        "battery_storage": {"type": "boolean"},
        "agrivoltaic": {"type": "boolean"},
        "type_agri": {"enum": ["culture", "elevage", "culture-elevage", None]},
        "detail_agri": {"type": ["string", "null"]},
    },
    "required": [
        "surface", "number_of_pannels", "type_parc", "pannel_type",
        "battery_storage", "agrivoltaic", "type_agri", "detail_agri",
    ],
}

DEFAULTS = {
    "surface": None,
    "number_of_pannels": None,
    "type_parc": None,
    "pannel_type": "undefined",
    "battery_storage": False,
    "agrivoltaic": False,
    "type_agri": None,
    "detail_agri": None,
}


def _to_float(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d+(?:[.,]\d+)?", str(v))
    return float(m.group().replace(",", ".")) if m else None


def _to_int(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    digits = re.sub(r"[^\d]", "", str(v))
    return int(digits) if digits else None


def _to_bool(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "oui", "si", "sì")


def _to_choice(v, allowed, default):
    v = str(v).strip().lower() if v is not None else None
    return v if v in allowed else default


def validate(data: dict) -> dict:
    """Normalize the model output so every field has the expected type/value."""
    out = dict(DEFAULTS)
    out["surface"] = _to_float(data.get("surface"))
    out["number_of_pannels"] = _to_int(data.get("number_of_pannels"))
    out["type_parc"] = _to_choice(data.get("type_parc"), {"sol", "flottant"}, None)
    out["pannel_type"] = _to_choice(
        data.get("pannel_type"), {"fix", "tracker", "undefined"}, "undefined"
    )
    out["battery_storage"] = _to_bool(data.get("battery_storage", False))
    out["agrivoltaic"] = _to_bool(data.get("agrivoltaic", False))
    out["type_agri"] = _to_choice(
        data.get("type_agri"), {"culture", "elevage", "culture-elevage"}, None
    )
    detail = data.get("detail_agri")
    out["detail_agri"] = str(detail).strip() or None if detail else None

    # consistency: agri fields only make sense if agrivoltaic is true
    if not out["agrivoltaic"]:
        out["type_agri"] = None
        out["detail_agri"] = None
    return out


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def extract_pv_infos(text: str, num_ctx: int = 16384) -> dict:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f'Document:\n"""\n{text}\n"""\n\nJSON:'},
        ],
        "format": SCHEMA,          # constrains the output; use "json" if your Ollama rejects schemas
        "think": False,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": num_ctx},
    }

    r = requests.post(OLLAMA_URL, json=payload, timeout=600)
    if not r.ok:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:500]}")

    raw = r.json()["message"]["content"]
    return validate(parse_json(raw))


# ---- long documents: chunk + merge ----

def chunk_text(text: str, size: int = 8000, overlap: int = 500):
    i = 0
    while i < len(text):
        yield text[i:i + size]
        i += size - overlap


def merge(results: list[dict]) -> dict:
    out = dict(DEFAULTS)
    for key in ("surface", "number_of_pannels", "type_parc", "type_agri", "detail_agri"):
        for r in results:
            if r[key] is not None:
                out[key] = r[key]
                break
    out["battery_storage"] = any(r["battery_storage"] for r in results)
    out["agrivoltaic"] = any(r["agrivoltaic"] for r in results)
    for r in results:
        if r["pannel_type"] != "undefined":
            out["pannel_type"] = r["pannel_type"]
            break
    if not out["agrivoltaic"]:
        out["type_agri"] = out["detail_agri"] = None
    return out


def extract_document(text: str) -> dict:
    results = []
    for chunk in chunk_text(text):
        try:
            results.append(extract_pv_infos(chunk))
        except Exception as e:
            print("Chunk failed:", e)
    return merge(results) if results else dict(DEFAULTS)


#########################################################################

def main():
    txt = FileDownloaderPdf().get_pdf_from_url(url=URL)
    if not txt:
        raise SystemExit("No text extracted from the PDF")
    print(json.dumps(extract_document(txt), indent=8, ensure_ascii=False))


if __name__ == "__main__":
    main()
