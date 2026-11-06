"""
Module to download and store pdfs.
"""
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
"""

import io
import requests
from pypdf import PdfReader


class RequestHTTPS:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
        })
        self._warmed_up = False

    def _warm_up(self, base="https://va.mite.gov.it/"):
        if not self._warmed_up:
            self.session.get(base, timeout=60)  # collects cookies
            self._warmed_up = True

    def request_get(self, url: str, timeout_seconds: int = 60) -> bytes | None:
        try:
            self._warm_up()
            response = self.session.get(
                url,
                timeout=timeout_seconds,
                headers={"Referer": "https://va.mite.gov.it/"},
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as err:
            print(f"Failed to fetch PDF. {err}")
            return None

        content = response.content
        if not content.lstrip()[:5] == b"%PDF-":
            ctype = response.headers.get("Content-Type")
            print(f"Not a PDF (Content-Type={ctype}, final URL={response.url})")
            with open("debug_response.html", "wb") as f:
                f.write(content)
            return None
        return content


class FileDownloaderPdf:
    def __init__(self):
        self.connector_https = RequestHTTPS()

    def get_and_store_pdf(self, url: str, output_path: str) -> bool:
        content = self.connector_https.request_get(url)
        if content is None:
            return False
        with open(output_path, "wb") as f:
            f.write(content)
        return True

    def get_pdf_from_url(self, url: str) -> str | None:
        content = self.connector_https.request_get(url)
        if content is None:
            return None
        reader = PdfReader(io.BytesIO(content))
        pages = (page.extract_text() or "" for page in reader.pages)
        return "\n".join(p for p in pages if p)

"""

#######################################################################
import os
import re
import json
import requests
from typing import Optional, Literal
from pydantic import BaseModel, field_validator

OPENWEBUI_URL = "https://402a8e9.jsz4n.dev".rstrip("/") #os.getenv("OPENWEBUI_URL", "http://localhost:3000")
API_KEY = "sk-6adaac828d3e4d97993468ce651d883e" #os.getenv("OPENWEBUI_API_KEY")
MODEL = "qwen3:4b"

URL = f"{OPENWEBUI_URL}/v1/chat/completions"

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

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
/no_think"""


class PVInfo(BaseModel):
    surface: Optional[float] = None
    number_of_pannels: Optional[int] = None
    type_parc: Optional[Literal["sol", "flottant"]] = None
    pannel_type: Literal["fix", "tracker", "undefined"] = "undefined"
    battery_storage: bool = False
    agrivoltaic: bool = False
    type_agri: Optional[Literal["culture", "elevage", "culture-elevage"]] = None
    detail_agri: Optional[str] = None

    @field_validator("number_of_pannels", mode="before")
    @classmethod
    def clean_int(cls, v):
        if isinstance(v, str):
            v = re.sub(r"[^\d]", "", v)
            return int(v) if v else None
        return v

    @field_validator("surface", mode="before")
    @classmethod
    def clean_float(cls, v):
        if isinstance(v, str):
            v = v.replace(",", ".")
            m = re.search(r"\d+(\.\d+)?", v)
            return float(m.group()) if m else None
        return v


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def extract_chunk(text: str) -> PVInfo:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Document:\n\"\"\"\n{text}\n\"\"\"\n\nJSON:"},
        ],
        "temperature": 0,
        "stream": False,
    }
    r = requests.post(url, headers=HEADERS, json=payload, timeout=300)
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"]
    info = PVInfo(**parse_json(raw))

    # post-processing consistency
    if not info.agrivoltaic:
        info.type_agri, info.detail_agri = None, None
    return info


def chunk_text(text: str, size: int = 6000, overlap: int = 500):
    i = 0
    while i < len(text):
        yield text[i:i + size]
        i += size - overlap


def merge(results: list[PVInfo]) -> PVInfo:
    """Keep the first non-null value per field; booleans are OR-ed."""
    out = PVInfo()
    for field in ["surface", "number_of_pannels", "type_parc", "type_agri", "detail_agri"]:
        for r in results:
            if getattr(r, field) is not None:
                setattr(out, field, getattr(r, field))
                break
    out.battery_storage = any(r.battery_storage for r in results)
    out.agrivoltaic = any(r.agrivoltaic for r in results)
    for r in results:  # prefer a defined panel type
        if r.pannel_type != "undefined":
            out.pannel_type = r.pannel_type
            break
    return out


def extract_document(text: str) -> PVInfo:
    results = []
    for chunk in chunk_text(text):
        try:
            results.append(extract_chunk(chunk))
        except Exception as e:
            print("Chunk failed:", e)
    return merge(results) if results else PVInfo()


#########################################################################

def main():
    print("Hello from italy-ollama!")
    
    txt = FileDownloaderPdf().get_pdf_from_url(
    	url=URL
    )
    print(txt)
    
    #print(extract_document(txt).model_dump_json(indent=8))


if __name__ == "__main__":
    main()
