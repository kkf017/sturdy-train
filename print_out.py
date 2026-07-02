""" Script .... """


import os
import uuid
import json
import time
import logging
import numpy
import pandas

import unidecode
import unicodedata
from functools import lru_cache
import requests
import math

import re

FILENAME = (
	"/home/kathleen/90_DATA_PREPROCESS/sturdy-train"
	"/output/CLEAN_connections_extract.xlsx"
)


FINAL = (
	"/home/kathleen/90_DATA_PREPROCESS/sturdy-train/output"
	"/enrich_connections_extract.xlsx"
)


CONNECTIONS = (
	"/home/kathleen/90_DATA_PREPROCESS/sturdy-train"
	"/output/connections_extract.xlsx"
)
########################################################################
#

def read_xlsx(filename: str) -> pandas.DataFrame:
    """
    Subfunction to read a file (xlsx).
    """
    x = pandas.DataFrame([])
    try:
        x = pandas.read_excel(filename)
    except OSError as err:
        logging.error(f"{err}")
    return x


def write_xlsx(filename: str, x: pandas.DataFrame) -> None:
    """
    Subfunction to write a file (xlsx).
    """
    try:
        x.to_excel(filename, index=False)
    except OSError as err:
        logging.error(f"Cant write file (xlsx). {err}")

########################################################################
#

def set_columns(frame):
	print(f"Create columns.")
	new = []
	for i, row in frame.iterrows():
		new.append(
			{
				#"uuid_proj": None,
				"uuid": row['uuid'],
				"nr_proj": row['nr_proj'],
				#"pdf_name": row['pdf_name'],
				"station_name": row['station_name'],
				"region": None,
				"nr_province": None, 
				"province": None,
				"code_istat": None,
				"municipality": row['municipality'],
				"hamlet": None,
				"station_code": row['station_code'],
				"connection_line": row['connection_line'],
				"connection_type": row['connection_type'],
				"grid_operator": row['grid_operator'],
				"voltage_kv": row['voltage_kv'],
				"connection_line_type": row['connection_line_type'],
				"cable_length_km": row['cable_length_km'],
				"terna_approval": row['terna_approval'],
				"doc_1": row['pdf_name'],
				"doc_2": None,
				"doc_3": None,
				"doc_4": None,
				"doc_5": None,
				"comment": row['comment'],
			}
		)
	return pandas.DataFrame(new)
	
#########################################################################
#
def set_uuid(frame):
	print(f"Create uuid.")
	for i, _ in frame.iterrows():
		if not isinstance(frame.loc[i, 'uuid'], str):
			#print(f"Cell is None ({i}). {frame.loc[i, 'uuid']}")
			pass
		else:
			frame.loc[i, 'uuid'] = str(uuid.uuid4())
	return frame


def set_string(frame, column):
	print(f"Clean municipality name.")
	for i, row in frame.iterrows():
		try:
			values = [
				unidecode.unidecode(value.strip().replace(',','').lower()) 
				for value in frame.loc[i, column].split(",")
			]
			frame.loc[i, column] = ", ".join(value)
		except:
			pass
		#print(f"{row['municipality']} -> {frame.loc[i, 'municipality']}")
	return frame


def set_connection(frame):
	print(f"Clean connection_line.")
	for i, row in frame.iterrows():
		try:
			sub = " / ".join([
				"-".join([ 
					unidecode.unidecode(s.strip()).lower()
				 	for s in (value.lower().replace("–","-")).split("-")
				 ])
				 for value in row["connection_line"].split(",")
			])
			frame.loc[i, "connection_line"] = sub
		except AttributeError:
			pass
	return frame

#########################################################################
#

COMUNI_URL = "https://raw.githubusercontent.com/matteocontrini/comuni-json/master/comuni.json"


def _normalize(s) -> str:
    """Lowercase and strip accents, so 'Citta' matches 'Città', etc."""
    s = str(s)  # coerce non-str input (e.g. NaN floats) instead of crashing
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.strip().lower()


@lru_cache(maxsize=1)
def _load_comuni():
    resp = requests.get(COMUNI_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_comune_codes(nome_comune) -> dict | None:
    """
    Given an Italian municipality name, return its region, province and
    municipality (ISTAT) codes. Returns None if not found or if the input
    is missing/invalid (None, NaN, empty string).
    """
    if nome_comune is None:
        return None
    if isinstance(nome_comune, float) and math.isnan(nome_comune):
        return None
    nome_comune = str(nome_comune).strip()
    if not nome_comune:
        return None

    comuni = _load_comuni()
    target = _normalize(nome_comune)

    for c in comuni:
        if _normalize(c["nome"]) == target:
            return {
                "comune": c["nome"],
                "codice_istat": c["codice"],
                "codice_catastale": c.get("codiceCatastale"),
                "sigla_provincia": c["sigla"],
                "provincia": {
                    "nome": c["provincia"]["nome"],
                    "codice": c["provincia"]["codice"],
                },
                "regione": {
                    "nome": c["regione"]["nome"],
                    "codice": c["regione"]["codice"],
                },
            }
    return None


def get_region(frame):
	print(f"Get municipality information.")
	for i, row in frame.iterrows():
		try:
			value = (row['municipality'].split(","))[0].strip()
			x = get_comune_codes(nome_comune=value)
			#print(f"\n{row['municipality']}: \n\t{json.dumps(x, indent=8)}")
			
			frame.loc[i, 'region'] = unidecode.unidecode(x.get('regione').get('nome')).lower()
			frame.loc[i, 'nr_province'] = x.get('provincia').get('codice')
			frame.loc[i, 'province'] = unidecode.unidecode(x.get('provincia').get('nome')).lower()
			frame.loc[i, 'code_istat'] = x.get('codice_istat')
			#frame.loc[i, 'municipality'] = x.get('')
			
		except:
			pass
	return frame

#########################################################################
#
# Voltage bands in kV: (min_exclusive, max_inclusive)
VOLTAGE_BANDS = {
    "BT":  (0, 1),
    "MT":  (1, 35),
    "AT":  (35, 150),
    "AAT": (150, float("inf")),
}


def classify_voltage(kv: float) -> str | None:
    """Return the voltage category (BT/MT/AT/AAT) for a single kV value."""
    if kv is None or kv < 0:
        return None
    for category, (low, high) in VOLTAGE_BANDS.items():
        if low < kv <= high or (low == 0 and kv == 0):
            return category
    return None


def _parse_voltage_field(voltage) -> list[float]:
    """
    Parse a voltage field that may be a single number (20) or a
    slash-separated pair representing a transformation station ("20/150").
    Returns a list of floats.
    """
    if voltage is None:
        return []
    if isinstance(voltage, (int, float)):
        return [float(voltage)]

    s = str(voltage).replace(",", ".").strip()
    parts = re.split(r"[/\-]", s)
    values = []
    for p in parts:
        p = p.strip()
        if p:
            try:
                values.append(float(p))
            except ValueError:
                pass
    return values


def check_voltage_type(voltage, tipo: str) -> dict:
    """
    Check whether a voltage (kV) is consistent with a declared connection
    type (e.g. 'MT', 'AT', 'MT/AT', 'AT/BT', ...).

    Parameters
    ----------
    voltage : float | str
        Voltage in kV. Can be a single value (20) or a slash-separated
        pair for transformation stations ("20/150").
    tipo : str
        Declared connection/line type, e.g. "MT", "AT/BT", "MT/AT".

    Returns
    -------
    dict with:
        - "valid": bool, whether the voltage is consistent with tipo
        - "expected_categories": list of categories implied by tipo
        - "actual_categories": categories inferred from the voltage value(s)
        - "detail": human-readable explanation
    """
    if tipo is None or (isinstance(tipo, float) and str(tipo) == "nan"):
        return {"valid": False, "expected_categories": [], "actual_categories": [],
                "detail": "Missing connection type"}

    expected = [t.strip().upper() for t in re.split(r"[/\-]", str(tipo)) if t.strip()]
    unknown = [t for t in expected if t not in VOLTAGE_BANDS]
    if unknown:
        return {"valid": False, "expected_categories": expected, "actual_categories": [],
                "detail": f"Unrecognized type token(s): {unknown}"}

    voltages = _parse_voltage_field(voltage)
    if not voltages:
        return {"valid": False, "expected_categories": expected, "actual_categories": [],
                "detail": "Missing or unparseable voltage"}

    actual = [classify_voltage(v) for v in voltages]

    if len(expected) == 1:
        # Simple line/station: BT, MT, AT or AAT
        valid = actual[0] == expected[0] if len(voltages) == 1 else all(a == expected[0] for a in actual)
        detail = f"{voltages} kV classified as {actual}, expected {expected}"
    else:
        # Transformation type e.g. MT/AT: each side must belong to the pair
        if len(voltages) == len(expected):
            # one value per side, e.g. "20/150" vs "MT/AT"
            valid = all(a in expected for a in actual)
        else:
            # single voltage given: must match at least one of the two bands
            valid = all(a in expected for a in actual) and len(actual) > 0
        detail = f"{voltages} kV classified as {actual}, expected one of {expected}"

    return {
        "valid": valid,
        "expected_categories": expected,
        "actual_categories": actual,
        "detail": detail,
    }


def check_voltage(frame):
	print(f"Check voltage and tipo.")
	for i, row in frame.iterrows():
		value = check_voltage_type(row['voltage_kv'], row['connection_line_type'])
		#print(f"\n({i}), {row['voltage_kv']}, {row['connection_line_type']} -> \n\t {json.dumps(value, indent=8)}")
		
		try:
			frame.loc[i,'connection_line_type'] = "/".join(
				value.get("actual_categories")
			)
		except TypeError:
			pass 
		#print(f"{frame.loc[i,'connection_line_type']}")
	return frame

#########################################################################
#
def get_index(value, frame):
    try:
        return numpy.where(frame == value)[0]
    except IndexError:
        return None

def get_revelent_files(frame, connections):
	files = ["doc_2", "doc_3", "doc_4", "doc_5"]
	for i, row in frame.iterrows():
		index = get_index(row['nr_proj'], connections)
		
		for j in range(min(len(files), len(index))):
			frame.loc[i, files[j]] = connections.loc[index[j], "pdf_name"]
			#print(f"For {row['nr_proj']} ({min(len(files), len(index))}): {frame.loc[i, files[j]]}")
	return frame

#########################################################################
#

def main():
	frame = read_xlsx(filename=FILENAME)
	print(f"Frame size: {frame.shape}")
	
	connections = read_xlsx(filename=CONNECTIONS)
	print(f"Frame size: {frame.shape}")
	
	frame = set_columns(frame)
	time.sleep(1.5)
	
	frame = set_uuid(frame)
	time.sleep(1.5)
	
	frame = set_string(frame, "station_name")
	frame = set_string(frame, "municipality")
	time.sleep(1.5)
	
	frame = get_region(frame)
	time.sleep(1.5)
	
	frame = set_connection(frame)
	time.sleep(1.5)
	
	
	frame = check_voltage(frame)
	time.sleep(1.5)
	
	frame = get_revelent_files(frame, connections)
	time.sleep(1.5)
	
	write_xlsx(filename="./enrich_connections_extract.xlsx", x=frame)


if __name__ == "__main__":
	main()
