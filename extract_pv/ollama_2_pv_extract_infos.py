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
import ollama
from typing import Optional, Literal
from pydantic import BaseModel

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


class PVInfo(BaseModel):
    surface: Optional[float] = None
    number_of_pannels: Optional[int] = None
    type_parc: Optional[Literal["sol", "flottant"]] = None
    pannel_type: Literal["fix", "tracker", "undefined"] = "undefined"
    battery_storage: bool = False
    agrivoltaic: bool = False
    type_agri: Optional[Literal["culture", "elevage", "culture-elevage"]] = None
    detail_agri: Optional[str] = None


# SYSTEM_PROMPT: reuse yours, but remove the "/no_think" line
# (the think=False parameter below replaces it)


def extract_pv_infos(text: str) -> PVInfo:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)

    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f'Document:\n"""\n{text}\n"""\n\nJSON:'},
        ],
        format=PVInfo.model_json_schema(),   # forces output matching the schema
        think=False,                         # disables Qwen3 thinking mode
        options={
            "temperature": 0,
            "num_ctx": 16384,                # context window, adjust to your RAM/VRAM
        },
    )
    info = PVInfo.model_validate_json(response.message.content)

    if not info.agrivoltaic:
        info.type_agri, info.detail_agri = None, None
    return info



#########################################################################

def main():
    txt = FileDownloaderPdf().get_pdf_from_url(url=URL)
    if not txt:
        raise SystemExit("No text extracted from the PDF")
    print(json.dumps(extract_pv_infos(txt), indent=8, ensure_ascii=False))


if __name__ == "__main__":
    main()
