""" Module to ... """

import os
import sys
import time
import logging
import json
import shutil
import uuid
import fitz #pdfplumber
from datetime import datetime
import unidecode
import re
import pandas


"""
############################
# A REVOIR:
	8202
############################
"""

#ROOT_DIR = "/home/kathleen/90_DATA_PREPROCESS/sturdy-train"

#NR_PROJ = "8375"
PDF_NAME = sys.argv[3]
#"8375_REL16_00_Piano_di_dismissione_e_ripristino_signed-signed.pdf"

NR_PROJ = sys.argv[4]
FILEPATH = sys.argv[1]
#(
#	f"{ROOT_DIR}"
#	"/data/"
#	f"{NR_PROJ}/{PDF_NAME}"
#)

OUTPUT = sys.argv[2]
#(
#	f"{ROOT_DIR}"
#	"/output"
#	"/connections_extract.csv"
#)

##########################################################################

def extract_connection_municipality(text: str) -> str:
	patterns = [
		# 8143/8143_0_Valutazione preliminare art.6 Lista di controllo.pdf
		#r"NTG\s+\d+/\d+\s+kV\s+([^\w\s])([^^\1]+)\1",

		# 8132/8132_Parere_n_412_Plenaria_del_19_9_24-ID_VIP_7436.pdf
		r'(?:connessione|allaccio|collegamento|opere di connessione)[^.]*?nei?\s+Comuni?\s+di\s+([A-Za-zÀ-ÖØ-öø-ÿ\s\-’,()]+?)(?=\s*,\s*(?:il quale|che|con\s|sito|sita|Proponente|e con)|\s+(?:con\s|sito|sita|Proponente|che|il quale|e con)|\s*\.|\s*;|$)',
		
		# 8021/8021_A_13a-STUDIO_DI_IMPATTO_AMBIENTALE.pdf
		r'comune\s+di\s+([A-Za-zÀ-ÖØ-öø-ÿ\s’\'\-]+?)(?:\s*\([A-Z]{2}\)|\s*$|\.|,)',
    
	]
	for pattern in patterns:
		match = re.search(pattern, text, re.IGNORECASE)
		if match:
			return match.group(1).strip()
	return None


def extract_connection_line(text: str) -> str:
    """
    Extracts the substation name from various Italian phrasing:
    - "Stazione Elettrica (SE) di smistamento" -> 'smistamento'
    - "SE RTN 150/36 kV Caltagirone" -> 'Caltagirone'
    - "cabina primaria AT/MT LEINI" -> 'LEINI'
    """
    clean_text = re.sub(r'\s+', ' ', text)

    # Regex breakdown:
    # 1. (?: ... | ... | ... ) : Non-capturing group matching 3 possible starting phrases
    #    a) Stazione Elettrica (SE) di 
    #    b) SE RTN 150/36 kV 
    #    c) cabina primaria AT/MT 
    # 2. ([A-Za-zÀ-ÖØ-öø-ÿ\s\-]+?) : CAPTURE GROUP 1: The name itself (non-greedy)
    # 3. (?: ... ) : Non-capturing boundary group to stop cleanly at voltage, punctuation, or keywords
    
    patterns = [
    	# 8021/8021_A_13a-STUDIO_DI_IMPATTO_AMBIENTALE.pdf
    	r'linea\s+(?:(?:RTN|MT|AT)\s+)?(?:a\s+\d+\s*kV\s+)?(?:esistente\s+)?(["“\']+[A-Za-zÀ-ÖØ-öø-ÿ\s]+[\-–—]+[A-Za-zÀ-ÖØ-öø-ÿ\s]+["“\']+)',
  	
  	# "8263/8263_TSTXIB1_VIncASSE_signed.pdf"
  	r'linea\s+\d+\s*kV\s+["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]',
  	
  	# "8375/8375_48405B-signed.pdf"
  	r"sull['\u2019]esistente\s+elettrodotto\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*\s*[\-\–\—]+\s*[A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)", 
    ]
    
    for pattern in patterns:
	    match = re.search(pattern, clean_text, re.IGNORECASE)
	    
	    if match:
                return match.group(0).replace("linea", "").strip()[:65]
    return None

def extract_station_name(text: str) -> str:
    """
    Extracts the substation name from various Italian phrasing:
    - "Stazione Elettrica (SE) di smistamento" -> 'smistamento'
    - "SE RTN 150/36 kV Caltagirone" -> 'Caltagirone'
    - "cabina primaria AT/MT LEINI" -> 'LEINI'
    """
    clean_text = re.sub(r'\s+', ' ', text)

    # Regex breakdown:
    # 1. (?: ... | ... | ... ) : Non-capturing group matching 3 possible starting phrases
    #    a) Stazione Elettrica (SE) di 
    #    b) SE RTN 150/36 kV 
    #    c) cabina primaria AT/MT 
    # 2. ([A-Za-zÀ-ÖØ-öø-ÿ\s\-]+?) : CAPTURE GROUP 1: The name itself (non-greedy)
    # 3. (?: ... ) : Non-capturing boundary group to stop cleanly at voltage, punctuation, or keywords
    
    patterns = [    	
    	# 8143/8143_0_Valutazione preliminare art.6 Lista di controllo.pdf
    	#r"RTN\s+a\s+\d+/\d+\s+kV\s+[\'\u2018\u2019\`]([^'\u2018\u2019\`]+)[\'\u2018\u2019\`]",
        #r"SE\s+Terna\s+[\'\u2018\u2019\`]([^'\u2018\u2019\`]+)[\'\u2018\u2019\`]",
        r'SE\s+Terna\s*["\'«“]\s*([A-Za-zÀ-ÖØ-öø-ÿ\s\-0-9]+?)\s*["\'»”]',
    	
    	# 8132/8132_Parere_n_412_Plenaria_del_19_9_24-ID_VIP_7436.pdf
  	r'(?:S\.E\.|Stazione elettrica RTN|stazione elettrica)\s*["\u201c\u201d]?([^"\u201c\u201d\n]+)["\u201c\u201d]?',
  	
  	# 8991/8991_1_1_d_Preventivo_di_connessione.pdf
  	r'stazione di smistamento a \d+(?:[.,]\d+)?\s*kV denominata "[^"]+"',
    ]
    
    for pattern in patterns:
	    match = re.search(pattern, clean_text, re.IGNORECASE)
	    
	    if match:
                return match.group(0).strip()[:45]
    return None

def extract_station_code(text: str) -> str:
    """
    Extracts the cabin/substation code STRICTLY for electrical connections.
    Explicitly IGNORES photovoltaic park codes, project IDs, or generic practice numbers.
    """
    # Normalize newlines to spaces for safer single-line regex matching
    clean_text = re.sub(r'\s+', ' ', text)

    # 1. E-Distribuzione Delivery Cabin Code (Inherently a connection point)
    # Format: D + 3 digits + - + 1 digit + - + 6 digits (e.g., D120-2-709163)
    # The negative lookbehind/lookahead ensures it's not part of a longer alphanumeric string.
    match_cabin = re.search(r'(?<![A-Za-z0-9])(D\d{3}-\d-\d{6})(?![A-Za-z0-9])', clean_text, re.IGNORECASE)
    if match_cabin:
        return match_cabin.group(1)

    # 2. 9-digit Substation/Connection Code (e.g., 202201619)
    # STRICT CONTEXT REQUIREMENT: The 9 digits MUST be preceded by explicit 
    # electrical connection keywords. Generic terms like "progetto", "impianto", 
    # "pratica", or "ID" will NOT trigger a match.
    # 
    # Regex breakdown:
    # (?: ... ) : Non-capturing group of allowed STRICT connection anchors:
    #   - codice (della)? (SE|sottostazione|cabina|connessione)
    #   - matricola (della)? (SE|sottostazione|cabina)
    #   - punto di connessione (n.?|codice)?
    # \s*[^\d]{0,40}? : Allows up to 40 non-digit characters (spaces, punctuation, words) 
    #                   between the anchor and the number.
    # (\d{9})\b       : CAPTURE GROUP 1: Exactly 9 digits, followed by a word boundary.
    
    pattern_nine = r'(?:codice\s+(?:della\s+)?(?:SE|sottostazione|cabina|connessione)|matricola\s+(?:della\s+)?(?:SE|sottostazione|cabina)|punto\s+di\s+connessione\s+(?:n\.?|codice\s+)?)\s*[^\d]{0,40}?(\d{9})\b'
    
    match_nine = re.search(pattern_nine, clean_text, re.IGNORECASE)
    if match_nine:
        return match_nine.group(1)
    
    return None


def extract_voltage(text: str) -> str:
    """
    Extracts the voltage level. 
    Prioritizes fractional (e.g., '150/36'), then single numeric (e.g., '150'), 
    then generic terms (e.g., 'MT', 'AT/MT').
    """
    # Normalize newlines to spaces for safer matching
    clean_text = re.sub(r'\s+', ' ', text)

    # 1. Try fractional voltage first (e.g., "150/36 kV")
    match_frac = re.search(r'(\d{2,3}\s*/\s*\d{2,3}\s*/\s*\d{2,3})\s*kV', clean_text, re.IGNORECASE)
    if match_frac:
        # Clean up spaces around the slash (e.g., "150 / 36" -> "150/36")
        return match_frac.group(1).replace(' ', '')

    # 1. Try fractional voltage first (e.g., "150/36 kV")
    match_frac = re.search(r'(\d{2,3}\s*/\s*\d{2,3})\s*kV', clean_text, re.IGNORECASE)
    if match_frac:
        # Clean up spaces around the slash (e.g., "150 / 36" -> "150/36")
        return match_frac.group(1).replace(' ', '')

    # 2. Try single numeric voltage (e.g., "150kV")
    match_single = re.search(r'(\d{2,3})kV', clean_text, re.IGNORECASE)
    if match_single:
        return match_single.group(1)

    # 2. Try single numeric voltage (e.g., "150 kV")
    match_single = re.search(r'(\d{2,3})\s*kV', clean_text, re.IGNORECASE)
    if match_single:
        return match_single.group(1)

    return None

def extract_connection_line_type(text: str) -> str:
    """
    Extracts the voltage level. 
    Prioritizes fractional (e.g., '150/36'), then single numeric (e.g., '150'), 
    then generic terms (e.g., 'MT', 'AT/MT').
    """
    # Normalize newlines to spaces for safer matching
    clean_text = re.sub(r'\s+', ' ', text)

    # 3. Fallback to generic voltage levels (e.g., "MT", "AT/MT", "AT")
    match_generic = re.search(r'\b(AT/MT|MT/AT|MT/BT|BT/MT|AAT/AT|AT/AT)\b', clean_text, re.IGNORECASE)
    if match_generic:
        return match_generic.group(1).upper()
    
    match_generic = re.search(r'\s+\b(AAT|AT|MT|BT)\b\s+', clean_text, re.IGNORECASE)
    if match_generic:
        return match_generic.group(1).upper()

    return None

def extract_grid_operator(text: str) -> str:
    """
    Extracts the grid operator (RTN, E-Distribuzione) and/or topology (in antenna, entra-esce).
    Returns them combined for maximum context (e.g., 'RTN + in antenna + entra-esce').
    """
    clean_text = re.sub(r'\s+', ' ', text)

    # 1. Extract Grid Operator
    grid_match = re.search(r'\b(RTN|Rete\s+di\s+Trasmissione\s+Nazionale|E-Distribuzione|Terna)\b', clean_text, re.IGNORECASE)

    if grid_match:
    	return grid_match.group(1).strip()
    return None


def extract_connection_type(text: str) -> str:
    """
    Extracts the grid operator (RTN, E-Distribuzione) and/or topology (in antenna, entra-esce).
    Returns them combined for maximum context (e.g., 'RTN + in antenna + entra-esce').
    """
    clean_text = re.sub(r'\s+', ' ', text)

    # 2. Extract Topology
    # Matches "in antenna", "entra-esce", or "entra-esci"
    topo_match = re.search(r'\b(in\s+antenna|entra[-\s]esce|entra[-\s]esci)\b', clean_text, re.IGNORECASE)
    if topo_match:
    	return topo_match.group(1).strip().replace('-', '-')
    return  None # Normalize hyphen

def _extract_cable_length_km(text: str) -> float:
    """
    Extracts the main connection cable length from prose paragraphs.
    Anchors to keywords like 'lunghezza', 'cavidotto', or 'elettrodotto' 
    to avoid false positives from unrelated distances in the text.
    """
    # Normalize newlines to spaces
    clean_text = re.sub(r'\s+', ' ', text)

    # Regex breakdown:
    # 1. (?: ... | ... )          : Non-capturing group for the anchor keywords
    #    a) lunghezza\s+(?:di\s+)?(?:circa\s+)?  : Matches "lunghezza di circa " or "lunghezza "
    #    b) cavidotto\s+[^0-9]{0,30}?            : Matches "cavidotto " followed by up to 30 non-digit chars
    #    c) elettrodotto\s+[^0-9]{0,30}?         : Matches "elettrodotto " followed by up to 30 non-digit chars
    # 2. (\d{1,5}(?:[.,]\d{1,3})?) : CAPTURE GROUP 1: The number (handles Italian decimals like 17,98)
    # 3. \s*(km|metri|m|mt)\b      : CAPTURE GROUP 2: The unit (km, m, metri, mt)
    
    patterns = [
    	# # 8021/8021_A_13a-STUDIO_DI_IMPATTO_AMBIENTALE.pdf
    	r'(?:lunghezza\s+(?:di\s+)?(?:circa\s+)?|cavidotto\s+[^0-9]{0,30}?|elettrodotto\s+[^0-9]{0,30}?)(\d{1,5}(?:[.,]\d{1,3})?)\s*(km|metri|m|mt)\b'
    ]
    for pattern in patterns:
	    match = re.search(pattern, clean_text, re.IGNORECASE)
	    
	    if match:
                num_str = match.group(1).replace(',', '.') # Handle Italian decimal comma
                unit = match.group(2).lower()
                val = float(num_str)
		
		# Convert to km if the unit is meters
                if unit in ['m', 'metri', 'mt']:
                    val = val / 1000.0
		    
                return round(val, 2)
    return None

import re

def extract_cable_length_km(text: str) -> float | None:
    """
    Extracts the main connection cable length from Italian prose paragraphs
    about PV and electrical connections.
    """
    # Normalize whitespace
    clean_text = re.sub(r'\s+', ' ', text)

    # --- STEP 1: Try anchored patterns first (high confidence) ---
    anchored_patterns = [
        # "lunghezza (di) (circa) (pari a) X km"
        r'lunghezza\s+(?:complessiva\s+)?(?:di\s+)?(?:circa\s+)?(?:pari\s+a\s+)?(\d{1,5}(?:[.,]\d{1,3})?)\s*(km|metri|mt|m)\b',
        # "lunghezza è (di) (circa) X km"
        r'lunghezza\s+[èe]\s+(?:di\s+)?(?:circa\s+)?(\d{1,5}(?:[.,]\d{1,3})?)\s*(km|metri|mt|m)\b',
        # "lungo/a (circa) X km"
        r'lung[ao]\s+(?:circa\s+)?(\d{1,5}(?:[.,]\d{1,3})?)\s*(km|metri|mt|m)\b',
        # "cavidotto/elettrodotto di X km" or "... avente lunghezza X km"
        r'(?:cavidotto|elettrodotto|cavo|linea)\b[^0-9]{0,60}?(?:lunghezza\s+)?(?:di\s+)?(?:circa\s+)?(?:pari\s+a\s+)?(\d{1,5}(?:[.,]\d{1,3})?)\s*(km|metri|mt|m)\b',
        # "estensione (di) (circa) X km"
        r'estensione\s+(?:di\s+)?(?:circa\s+)?(\d{1,5}(?:[.,]\d{1,3})?)\s*(km|metri|mt|m)\b',
        # "percorso di X km"
        r'percorso\s+(?:di\s+)?(\d{1,5}(?:[.,]\d{1,3})?)\s*(km|metri|mt|m)\b',
    ]

    # --- STEP 2: Fallback — any plausible length + unit (last resort) ---
    fallback_patterns = [
        # e.g. "circa X km", "pari a X km", "per X km"
        r'(?:circa|pari\s+a|per)\s+(\d{1,5}(?:[.,]\d{1,3})?)\s*(km|metri|mt|m)\b',
        # bare number + km that looks like a cable length (1–999 km or up to 9999 m)
        r'\b(\d{1,5}(?:[.,]\d{1,3})?)\s*(km)\b',
    ]

    def parse_match(match) -> float:
        num_str = match.group(1).replace(',', '.')
        unit = match.group(2).lower()
        val = float(num_str)
        if unit in ['m', 'metri', 'mt']:
            val = val / 1000.0
        return round(val, 3)

    for pattern in anchored_patterns:
        match = re.search(pattern, clean_text, re.IGNORECASE)
        if match:
            return parse_match(match)

    for pattern in fallback_patterns:
        match = re.search(pattern, clean_text, re.IGNORECASE)
        if match:
            return parse_match(match)

    return None

def extract_terna_approved(text: str) -> dict:
    """
    Extracts approval and sharing statuses from the text.
    Returns True if the condition is met, otherwise returns None (null).
    """
    # Normalize newlines to spaces for safer single-line regex matching
    clean_text = re.sub(r'\s+', ' ', text)

    # 1. TERNA APPROVED
    # Looks for explicit approval keywords: "benestare", "benestariata", "autorizzata", "approvata", or "nulla osta"
    terna_pattern = r'\b(benestare|benestariata|autorizzata|approvata|nulla\s+osta)\b'
    terna_approved = True if re.search(terna_pattern, clean_text, re.IGNORECASE) else None

    return terna_approved

##########################################################################
def clean_txt(txt):
	try:
		txt = txt.lower()
		txt = txt.replace("\n"," ").replace("\t"," ")
		txt = unidecode.unidecode(txt)
		return txt
	except Exception:
		return txt

def read_large_pdf_pymupdf(pdf_path, max_pages=None, return_pages=False):
    pages_text = []
    with fitz.open(pdf_path) as doc:
        n = len(doc) if max_pages is None else min(max_pages, len(doc))
        for i in range(n):
            text = doc[i].get_text("text")
            pages_text.append(text)
    return pages_text if return_pages else "\n".join(pages_text)


def extraction(text: str) -> str:
	info = {
		"uuid": str(uuid.uuid4()),
		"nr_proj": NR_PROJ,
		"pdf_name": PDF_NAME,
		
	    	# station de raccordement
	    	"station_name": None,
	    	"station_code": None,
	    	# ligne de raccordement
	    	"connection_line": None,
	    	# type de connection (cable, antenne...etc)
	    	"connection_type": None,
	    	# gestionnaire du réseau () -> grid_operator
	    	"grid_operator": None,
	    	# voltage (MT, HT...etc)
	    	"voltage_kv": None,
		"connection_line_type": None,
	    	# cable_length:
	    	"cable_length_km": None,
	    	# municipality du projet
	    	"municipality": None,
	    	
	    	# terna_approved, stmg_accepted, shared_connection
	    	"terna_approval": None,
	    	
	    	"comment":None,
	}
	
	info["municipality"] = extract_connection_municipality(text=text)
	info["grid_operator"] = extract_grid_operator(text=text)
	info["connection_type"] = extract_connection_type(text=text)
	
	info["voltage_kv"] = extract_voltage(text=text)
	info["connection_line_type"] = extract_connection_line_type(text=text)
	
	#if not "antenna" in info["connection_type"]:	
	info["cable_length_km"] = extract_cable_length_km(text=text)
	
	info["station_name"] = extract_station_name(text=text)
	info["station_code"] = extract_station_code(text=text)
	info["connection_line"] = extract_connection_line(text=text)
	
	info["terna_approval"] = extract_terna_approved(text=text)
	return info

##########################################################################
def create_csv_empty():
	columns = [
		"uuid",
		"nr_proj",
		"pdf_name",
	    	"station_name",
	    	"station_code",
	    	"connection_line",
	    	"connection_type",
	    	"grid_operator",
	    	"voltage_kv",
		"connection_line_type",
	    	"cable_length_km",
	    	"municipality",
	    	"terna_approval",
	    	"comment",
	]
	try:
		frame = pandas.DataFrame(columns=columns)
		frame.to_csv("./connections_extract.csv", index=False)
	except Exception as err:
		print(err)


def read_csv(filename):
	try:
		return pandas.read_csv(filename)
	except (Exception):
		return None

def read_xlsx(filename: str) -> pandas.DataFrame:
    x = pandas.DataFrame([])
    try:
        x = pandas.read_excel(filename)
    except OSError as err:
        logging.error(f"{err}")
    return x


def write_csv(filename, frame):
	#split_filename = filename.split("/")
	#timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
	#filename = f"{'/'.join(split_filename[:-1])}/{timestamp}_{split_filename[-1]}"
	try:
		frame.to_csv(filename, index=False)
	except (Exception) as err:
		return print(err)

def write_xlsx(filename: str, x: pandas.DataFrame) -> None:
    try:
        x.to_excel(filename, index=False)
    except OSError as err:
        logging.error(f"Cant write file (xlsx). {err}")

##########################################################################

def main():
    #frame = read_csv(filename=OUTPUT)
    frame = read_xlsx(filename=OUTPUT)

    print(f"Working dir: {FILEPATH}\n")
	
    txt = read_large_pdf_pymupdf(FILEPATH)
    txt = clean_txt(txt)
    print(txt)
	
    info = extraction(text=txt)

    print(f"\n{json.dumps(info,indent=8)}")
    
    # append line
    frame = pandas.concat([frame, pandas.DataFrame([info])], ignore_index=True)
    
    #write_csv(filename=OUTPUT, frame=frame)
    write_xlsx(filename=OUTPUT, x=frame)


if __name__ == "__main__":
    main()
    #create_csv_empty()
