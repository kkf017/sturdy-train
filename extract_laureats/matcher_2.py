"""
Script to match Global_Wind_Power_tracker.
"""
import sys
import time
import sqlite3
import pandas
import Levenshtein
import unidecode

DB = "./wind/projects.db"
FILEPATH = (
	"./data/Global_Wind_Power_Tracker/"
	"Global-Wind-Power-Tracker-February-2026.xlsx"
)

MATCH = (
	"./data/Global_Wind_Power_Tracker/"
	"global_wind_power_tracker.xlsx"
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

def read_xlsx(filename:str, sheet:str=None) -> pandas.DataFrame:
	"""
	Function to read a file (.xlsx).
	"""
	x = pandas.DataFrame([])
	try:
		if sheet is None:
			x = pandas.read_excel(filename)
		else:
			x = pandas.read_excel(filename, sheet_name=sheet)
		
	except OSError as err:
		print(f"Error when reading file (.xlsx). {err}")
	return x

def write_xlsx(filename: str, x: pandas.DataFrame, sheet:str=None) -> None:
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
			if 0.65 < distance_levenshtein(
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
		"region": "State/Province",
		"province": None,
		"municipality": "City",
		"latitude": "Latitude",
		"longitude": "Longitude",
		"owner": "Operator", # "Operator", "Owner"
	},
	"wind": {
		"region": "region",
		"province": "province",
		"municipality": "municipality",
		"owner": "proponent",
	}
}

def main():
    print("Hello from italy-Global-Wind-Tracker!")
    frame = load_database(filename=DB, table="projects")
    print(f"Extract table: {frame.shape} \n{frame.columns}")
    
    frame_laureats = read_xlsx(filename=FILEPATH, sheet="Data")
    print(f"Extract laureats: {frame_laureats.shape} \n{frame_laureats.columns}")

    frame_laureats = frame_laureats[frame_laureats["Country/Area"]=="Italy"]
    frame_laureats = frame_laureats[frame_laureats["Installation Type"]=="Onshore"]

    matchs = []
    for i, row_a in frame_laureats.iterrows():
    	for j, row_b in frame.iterrows():
    		match_region =  get_match_1(
    			row_a[KEY_X_VALUE["global_wind_power_tracker"]["region"]], 
    			row_b[KEY_X_VALUE["wind"]["region"]]
    		)
    		#match_province =  get_match_1(row_a["Provincia"], row_b["province"])
    		match_municipality =  get_match_1(
    			row_a[KEY_X_VALUE["global_wind_power_tracker"]["municipality"]], 
    			row_b[KEY_X_VALUE["wind"]["municipality"]]
    		)
    		
    		match_owner =  get_match_2(
    			row_a[KEY_X_VALUE["global_wind_power_tracker"]["owner"]], 
    			row_b[KEY_X_VALUE["wind"]["owner"]]
    		)
    		
    		print(f"\nMatch (region): {row_a[KEY_X_VALUE['global_wind_power_tracker']['region']]}, {row_b[KEY_X_VALUE['wind']['region']]} -> {match_region}")
    		#print(f"Match (province): {row_a['Provincia']}, {row_b['province']} -> {match_province}")
    		print(f"Match (municipality): {row_a[KEY_X_VALUE['global_wind_power_tracker']['municipality']]}, {row_b[KEY_X_VALUE['wind']['municipality']]} -> {match_municipality}")
    		#print(f"Match (owner): {row_a['Ragione Sociale']}, {row_b['proponent']} -> {match_owner}")
    		#time.sleep(0.25)
    		#input("Press enter.")
    		
    		if match_region and match_municipality:
    			matchs.append( {
    				"global_wind_power_tracker": row_a['Project Name'],
    				"Projects": f"{row_b['project_id']}-{row_b['doc_set_id']}",
    				"region_a": row_a[KEY_X_VALUE["global_wind_power_tracker"]["region"]],
    				"region_b": row_b[KEY_X_VALUE["wind"]["region"]],
    				"municipality_a": row_a[KEY_X_VALUE["global_wind_power_tracker"]["municipality"]],
    				"minicipality_b": row_b[KEY_X_VALUE["wind"]["municipality"]],
    				"coeff_municipality": match_municipality,
    				
    				
    				"owner_a": row_a[KEY_X_VALUE["global_wind_power_tracker"]["owner"]],
    				"owner_a_bis": row_a["Owner"],
    				"owner_b": row_b[KEY_X_VALUE["wind"]["owner"]],
    				"coeff_owner": match_owner,
    				
    				"power_a": row_a['Capacity (MW)'],
    				"power_b": row_b['power_mw'],
    				
    				"time_a": row_a['Start year'],
    				"time_b": row_b['submission_date']
    				
    			})

    write_xlsx(filename=MATCH, x=pandas.DataFrame(matchs))

if __name__ == "__main__":
    main()
