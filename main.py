
import os
import time
import shutil
import pandas

INPUTS = {
	"GET_FILES": True,
	"COPY_FILES": True,
	"EXTRACT_FILES": True,
}

"""-------------------------------------------------------
	CHECK:
		- set 5 more revelent files in db and add uuid_proj
		- check MT/AT/BT ...etc with real values
		- region, province, hamlet
		
	OFFSETS:
		0 -> 5 10020-10088
		5 -> 10 10097-10107
		10 -> 15 10133-10176
		15 -> 20 10185-10224
		20 -> 25 -10288
		25 -> 30 10239-10348
		30 -> 35 10400-10442
		35 -> 40 10454-10492
		40 -> 45 
		45 -> 50 10537-10564
		50 -> 55 10568-10641
		55 -> 60 10652-10677
		60 -> 65 10686-10754
		65 -> 70 10791-10876
		70 -> 82 10885-11026
		84 ->    11220
		87 ->    11296
		
		132 ->   8010
		178 ->   8258
		193 ->   8374
		225 ->   8598
		255 ->   8960		
		294 ->   9217
	10641
	
	python -m scraper_italia download --offset 20 --limit 5
	python -m scraper_italia download --offset 138 --limit 5
	python -m scraper_italia download --offset 199 --limit 1
	python -m scraper_italia download --offset 212 --limit 1
	python -m scraper_italia download --offset 294 --limit 1
----------------------------------------------------------"""

def main(nr_proj):
    print("Hello from sturdy-train!")
   
    ROOT_DIR = (
    	"/home/kathleen/90_DATA_PREPROCESS"
    )
    NR_PROJ = nr_proj #"9263"

    PDF_DIR = (
    	f"{ROOT_DIR}"
    	#"/italy_poc"
    	"/italy_poc/output/documents/"
    	f"{NR_PROJ}"
    )

    # ─────────────────────────────────────────────────────
    #  Run photovoltaic_connection_pipeline_large_pdfs
    # ─────────────────────────────────────────────────────
    pdf_dir = PDF_DIR
    
    output_dir = f"{ROOT_DIR}/sturdy-train/data/{NR_PROJ}"
    
    print(output_dir)
    
    
    if not os.path.exists(output_dir):
    	# create dir
        try:
            os.mkdir(output_dir)
            print(f"Directory '{output_dir}' created successfully.")
        except FileExistsError:
            print(f"Directory '{output_dir}' already exists.")
        except PermissionError:
            print(f"Permission denied: Unable to create '{output_dir}'.")
        except Exception as e:
            print(f"An error occurred: {e}")

    time.sleep(2)
   
    print(f"\nSelect files: {NR_PROJ}")

    if INPUTS["GET_FILES"]:
        command = f"python photovoltaic_connection_pipeline_large_pdfs.py {PDF_DIR} {output_dir}"
        os.system(command)
    
    time.sleep(3)

    # ─────────────────────────────────────────────────────
    #  Copy files into data/
    # ─────────────────────────────────────────────────────
    filename = os.path.join(output_dir, "partial_results.csv")
    frame =  pandas.read_csv(filename)

    if INPUTS["COPY_FILES"]:    
        for i, row in frame.iterrows():
    	    print(f"\nCopy file: {row['source_file']}")
    	
    	    src = os.path.join(pdf_dir, row['source_file'])
    	    dest = os.path.join(output_dir, row['source_file'])
    	    shutil.copy(src, dest)

    time.sleep(3)

    # ─────────────────────────────────────────────────────
    #  ###
    # ─────────────────────────────────────────────────────
    FILEPATH = (
	f"{ROOT_DIR}/sturdy-train/data/{NR_PROJ}"
    )

    OUTPUT = (
	f"{ROOT_DIR}/sturdy-train"
	"/output"
	"/connections_extract.xlsx"
    )
    
    print(FILEPATH)
    print(OUTPUT)
    
    if INPUTS["EXTRACT_FILES"]:  
       #for i, row in frame.iterrows():
       for url in frame['source_file'].unique():
    	   #url = row['source_file']
    	   print(f"\nCopy file: {url}")
    	
    	   src = os.path.join(FILEPATH, url)
    	   command = f"python extract_pv_info.py {src} {OUTPUT} {url} {NR_PROJ}"
    	   os.system(command)

    time.sleep(3)

if __name__ == "__main__":
    PROJS = [
	8100
    ]
    for nr_proj in PROJS:
    	main(nr_proj=nr_proj)
