""" Module to ... """

import os
import time
import logging
import json
import shutil
import fitz #pdfplumber
import unidecode
import re


ROOT_DIR = "/home/kathleen/90_DATA_PREPROCESS/italy_poc_bis"
FILEPATH = (
	f"{ROOT_DIR}"
	"/data/"
	"8132/8132_RDE-01_STMG_e_accettazione.pdf"
	# "8021/8021_A_13a-STUDIO_DI_IMPATTO_AMBIENTALE.pdf"
	# "8132/8132_Parere_n_412_Plenaria_del_19_9_24-ID_VIP_7436.pdf"
	# "8132/8132_RDE-01_STMG_e_accettazione.pdf"
	# "8143/8143_0_Valutazione preliminare art.6 Lista di controllo.pdf"
	# "8202/8202_MiTE_2023-0023281.pdf"
	# "8202/8202_J6W2V96_RelazioneOpereConnessione-signed.pdf"
	# "8240/8240_AS245-ET08-R_Relazione_tecnica_descrittiva_opere_RTN.pdf"
	#"8240/8240_parere_n_383_id_vip_7610_plenaria_pnr-pniec.pdf"
	#"8240/8240_RDS-10_Viarch_Bufala.pdf"
	#"8263/8263_TSTXIB1_VIncASSE_signed.pdf"
	#"8263/8263_APR01_VIncA_SSE_signed.pdf"
)

##########################################################################

def _extract_substation_name(text: str) -> str:
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
    	
    	# 8143/8143_0_Valutazione preliminare art.6 Lista di controllo.pdf
    	r"RTN\s+a\s+\d+/\d+\s+kV\s+[\'\u2018\u2019\`]([^'\u2018\u2019\`]+)[\'\u2018\u2019\`]",
        r"SE\s+Terna\s+[\'\u2018\u2019\`]([^'\u2018\u2019\`]+)[\'\u2018\u2019\`]",
    	
    	# 8132/8132_Parere_n_412_Plenaria_del_19_9_24-ID_VIP_7436.pdf
  	#r'(?:S\.E\.|Stazione elettrica RTN|stazione elettrica)\s*["\u201c\u201d]?([^"\u201c\u201d\n]+)["\u201c\u201d]?',
  	
  	# "8263/8263_TSTXIB1_VIncASSE_signed.pdf"
  	r'linea\s+\d+\s*kV\s+["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]',
  	
  	# "8375/8375_48405B-signed.pdf"
  	r"sull['\u2019]esistente\s+elettrodotto\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*\s*[\-\–\—]\s*[A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)", 
    ]
    
    for pattern in patterns:
	    match = re.search(pattern, clean_text, re.IGNORECASE)
	    
	    if match:
                return match.group(1).strip()
    return None

def _extract_substation_code(text: str) -> str:
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



def _extract_connection_municipality(text: str) -> str:
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


def _extract_voltage(text: str) -> str:
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

    # 3. Fallback to generic voltage levels (e.g., "MT", "AT/MT", "AT")
    match_generic = re.search(r'\b(AT/MT|MT|AT)\b', clean_text, re.IGNORECASE)
    if match_generic:
        return match_generic.group(1).upper()

    return None


def _extract_connection_type(text: str) -> str:
    """
    Extracts the grid operator (RTN, E-Distribuzione) and/or topology (in antenna, entra-esce).
    Returns them combined for maximum context (e.g., 'RTN + in antenna + entra-esce').
    """
    clean_text = re.sub(r'\s+', ' ', text)

    # 1. Extract Grid Operator
    grid_match = re.search(r'\b(RTN|Rete\s+di\s+Trasmissione\s+Nazionale|E-Distribuzione|Terna)\b', clean_text, re.IGNORECASE)
    grid = grid_match.group(1).strip() if grid_match else None

    # 2. Extract Topology
    # Matches "in antenna", "entra-esce", or "entra-esci"
    topo_match = re.search(r'\b(in\s+antenna|entra[-\s]esce|entra[-\s]esci)\b', clean_text, re.IGNORECASE)
    topology = topo_match.group(1).strip().replace('-', '-') if topo_match else None # Normalize hyphen

    # 3. Combine findings cleanly
    parts = [p for p in [grid, topology] if p]
    
    if not parts:
        return None
        
    # If both are found, join them. If only one, return just that one.
    return " + ".join(parts)	


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


def _extract_terna_approved(text: str) -> dict:
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


def _extract_stmg_accepted(text: str) -> dict:
    """
    Extracts approval and sharing statuses from the text.
    Returns True if the condition is met, otherwise returns None (null).
    """
    # Normalize newlines to spaces for safer single-line regex matching
    clean_text = re.sub(r'\s+', ' ', text)

    # 2. STMG ACCEPTED
    # Looks for "STMG" and "accettata/accettazione" appearing in the same sentence/proximity
    patterns = [
    	#  8021/8021_A_13a-STUDIO_DI_IMPATTO_AMBIENTALE.pdf
    	r'\bSTMG\b.*?\b(accettata|accettazione)\b|\b(accettata|accettazione)\b.*?\bSTMG\b'
    ]
    for pattern in patterns:
    	value = re.search(pattern, clean_text, re.IGNORECASE)
    	if value:
    		return True
    return None
    

def _extract_shared_connection(text: str) -> dict:
    """
    Extracts approval and sharing statuses from the text.
    Returns True if the condition is met, otherwise returns None (null).
    """
    # Normalize newlines to spaces for safer single-line regex matching
    clean_text = re.sub(r'\s+', ' ', text)

    # 3. SHARED CONNECTION
    # Looks for keywords indicating shared infrastructure or a lead producer
    patterns = [
    	# #  8021/8021_A_13a-STUDIO_DI_IMPATTO_AMBIENTALE.pdf
    	r'\b(capofila|condivisione|in\s+capo\s+ad\s+altro|shared|compartecipazione)\b'
    ]
    for pattern in patterns:
    	value = re.search(pattern, clean_text, re.IGNORECASE)
    	if value:
    		return True
    return None
  
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
    	
    	# 8143/8143_0_Valutazione preliminare art.6 Lista di controllo.pdf
    	#r"RTN\s+a\s+\d+/\d+\s+kV\s+[\'\u2018\u2019\`]([^'\u2018\u2019\`]+)[\'\u2018\u2019\`]",
        #r"SE\s+Terna\s+[\'\u2018\u2019\`]([^'\u2018\u2019\`]+)[\'\u2018\u2019\`]",
    	
    	# 8132/8132_Parere_n_412_Plenaria_del_19_9_24-ID_VIP_7436.pdf
  	#r'(?:S\.E\.|Stazione elettrica RTN|stazione elettrica)\s*["\u201c\u201d]?([^"\u201c\u201d\n]+)["\u201c\u201d]?',
  	
  	# "8263/8263_TSTXIB1_VIncASSE_signed.pdf"
  	#r'linea\s+\d+\s*kV\s+["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]',
  	
  	# "8375/8375_48405B-signed.pdf"
  	#r"sull['\u2019]esistente\s+elettrodotto\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*\s*[\-\–\—]\s*[A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)", 
    ]
    
    for pattern in patterns:
	    match = re.search(pattern, clean_text, re.IGNORECASE)
	    
	    if match:
                return match.group(0).replace("linea", "").strip()
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
    	# 8021/8021_A_13a-STUDIO_DI_IMPATTO_AMBIENTALE.pdf
    	#r'linea\s+(?:(?:RTN|MT|AT)\s+)?(?:a\s+\d+\s*kV\s+)?(?:esistente\s+)?(["“\']+[A-Za-zÀ-ÖØ-öø-ÿ\s]+[\-–—]+[A-Za-zÀ-ÖØ-öø-ÿ\s]+["“\']+)',
    	
    	# 8143/8143_0_Valutazione preliminare art.6 Lista di controllo.pdf
    	#r"RTN\s+a\s+\d+/\d+\s+kV\s+[\'\u2018\u2019\`]([^'\u2018\u2019\`]+)[\'\u2018\u2019\`]",
        #r"SE\s+Terna\s+[\'\u2018\u2019\`]([^'\u2018\u2019\`]+)[\'\u2018\u2019\`]",
    	
    	# 8132/8132_Parere_n_412_Plenaria_del_19_9_24-ID_VIP_7436.pdf
  	r'(?:S\.E\.|Stazione elettrica RTN|stazione elettrica)\s*["\u201c\u201d]?([^"\u201c\u201d\n]+)["\u201c\u201d]?',
  	
  	# "8263/8263_TSTXIB1_VIncASSE_signed.pdf"
  	#r'linea\s+\d+\s*kV\s+["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]',
  	
  	# "8375/8375_48405B-signed.pdf"
  	#r"sull['\u2019]esistente\s+elettrodotto\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*\s*[\-\–\—]\s*[A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*)", 
    ]
    
    for pattern in patterns:
	    match = re.search(pattern, clean_text, re.IGNORECASE)
	    
	    if match:
                return match.group(0).strip()
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

def extract_cable_length_km(text: str) -> float:
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

def main():
    print(f"Working dir: {FILEPATH}\n")
	
    txt = read_large_pdf_pymupdf(FILEPATH)
    txt = clean_txt(txt)
    print(txt)
    
    info = {
        "substation_name": _extract_substation_name(text=txt),
        "substation_code": _extract_substation_code(text=txt),
        "voltage_kv": _extract_voltage(text=txt),
        "connection_type": _extract_connection_type(text=txt),
        "cable_length_km": _extract_cable_length_km(text=txt),
        "connection_municipality": _extract_connection_municipality(text=txt),

        "terna_approved": _extract_terna_approved(text=txt),
        "stmg_accepted": _extract_stmg_accepted(text=txt),
        "shared_connection": _extract_shared_connection(text=txt)
    }
    
    print(f"\n{json.dumps(info,indent=8)}")
	
    info = extraction(text=txt)

    print(f"\n{json.dumps(info,indent=8)}")


if __name__ == "__main__":
    main()
