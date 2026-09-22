"""
Script to match laureats.
"""
import sys
import time
import sqlite3
import pandas
import Levenshtein
import unidecode

# Tableau Groupe A - (A et A-2) ET EXCLUE pour tous 

DB = "./wind/projects.db"
FILEPATH = (
	"./wind/AS_A_2019_1/ammesi/"
	"Graduatoria_DM2019_Bando1_AS_A_TABELLA_A.xlsx"
)

MATCH = (
	"./wind/AS_A_2019_1/ammesi/"
	"[AMMESSI]_AS_A_2019_1.xlsx"
)
#################################################
#
def load_database(filename: str, table: str) -> pandas.DataFrame:
    """
    Function to extract database (table).
    """
    frame = None
    try:
        conn = sqlite3.connect(filename)
        frame = pandas.read_sql_query(f"""SELECT * FROM {table};""", conn, params=())
        conn.close()
        print(f"Successful extraction. {frame.shape}")
    except sqlite3.OperationalError as err:
        print(f"Failed extraction. {err}")
        sys.exit(-1)
    return frame

def read_xlsx(filename:str) -> pandas.DataFrame:
	"""
	Function to read a file (.xlsx).
	"""
	x = pandas.DataFrame([])
	try:
		x = pandas.read_excel(filename)
	except OSError as err:
		print(f"Error when reading file (.xlsx). {err}")
	return x

def write_xlsx(filename: str, x: pandas.DataFrame) -> None:
	"""
	Function to write a file (.xlsx).
	"""
	try:
		x.to_excel(filename, index=False)
	except OSError as err:
		print(f"Error when writing file. {err}")

#################################################
#
def clean_str(name: str) -> str | None:
    """
    Function to check matching. (municipality)
    """
    excepts = {
    }
    try:
    	new = unidecode.unidecode((name.strip()).lower())
    	for key, value in excepts.items():
    		new = new.replace(key, value)
    	return new
    except (ValueError, AttributeError, TypeError):
    	return name

def distance_levenshtein(a: str | None, b: str | None) -> float:
    """
    Function to get Levenshtein distance.
    """
    if a is None or b is None:
        return 0.0
    return Levenshtein.ratio(a, b)

def get_match_1(row_a:str, row_b:str) -> bool:
	row_a = str(row_a)
	row_b = str(row_b)
	for a in row_a.split(","):
		for b in row_b.split(","):
			if 0.85 < distance_levenshtein(
				clean_str(a), 
				clean_str(b)
			):
				return True
	return False


def get_match_2(row_a:str, row_b:str) -> float:
	return distance_levenshtein(
		clean_str(row_a), 
		clean_str(row_b)
	)
#################################################
#

KEY_X_VALUE = {
	"global_wind_power_tracker": {
		"region": None,
		"province": None,
		"municipality": None,
		"owner": None,
	},
	"wind": {
		"region": None,
		"province": None,
		"municipality": None,
		"owner": None,
	}
}

def main():
    print("Hello from italy-laureats!")
    frame = load_database(filename=DB, table="projects")
    print(f"Extract table: {frame.shape} \n{frame.columns}")
    
    frame_laureats = read_xlsx(filename=FILEPATH)
    print(f"Extract laureats: {frame_laureats.shape} \n{frame_laureats.columns}")
    
    matchs = []
    for i, row_a in frame_laureats.iterrows():
    	for j, row_b in frame.iterrows():
    		match_region =  get_match_1(row_a["Regione"], row_b["region"])
    		match_province =  get_match_1(row_a["Provincia"], row_b["province"])
    		match_municipality =  get_match_1(row_a["Comune"], row_b["municipality"])
    		
    		match_owner =  get_match_2(row_a["Ragione Sociale"], row_b["proponent"])
    		
    		print(f"\nMatch (region): {row_a['Regione']}, {row_b['region']} -> {match_region}")
    		print(f"Match (province): {row_a['Provincia']}, {row_b['province']} -> {match_province}")
    		print(f"Match (municipality): {row_a['Comune']}, {row_b['municipality']} -> {match_municipality}")
    		print(f"Match (owner): {row_a['Ragione Sociale']}, {row_b['proponent']} -> {match_owner}")
    		#time.sleep(0.5)
    		#input("Press enter.")
    		
    		if match_region and match_province and match_municipality:
    			matchs.append( {
    				"PC_EOL": row_a['Codice di richiesta FER'],
    				"Projects": f"{row_b['project_id']}-{row_b['doc_set_id']}",
    				"region_a": row_a["Regione"],
    				"region_b": row_b["region"],
    				"province_a": row_a["Provincia"],
    				"province_b": row_b["province"],
    				"municipality_a": row_a["Comune"],
    				"minicipality_b": row_b["municipality"],
    				"coeff_municipality": match_municipality,
    				"owner_a": row_a["Ragione Sociale"],
    				"owner_b": row_b["proponent"],
    				"coeff_owner": match_owner,
    				
    				"power_a": row_a["Potenza conteggiata ai fini del contingente (kW)"],
    				"power_b": row_b['power_mw'],
    				
    				"time_a": row_a["Data e ora di completamento della richiesta di iscrizione all'Asta"],
    					#'Data e ora di completamento della domanda di partecipazione alla procedura'],
    				"time_b": row_b['submission_date']
    				
    			})
    
    write_xlsx(filename=MATCH, x=pandas.DataFrame(matchs))
    


if __name__ == "__main__":
    main()
