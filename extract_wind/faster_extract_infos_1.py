import json
import torch
import copy
from pdf2image import convert_from_path, pdfinfo_from_path
from transformers import AutoModelForCausalLM, AutoTokenizer

custom_path = "./NuExtract3"

def merge_extracted_data(global_data: dict, new_data: dict) -> dict:
    """
    Fusionne de manière récursive les nouvelles informations extraites 
    dans le dictionnaire global sans écraser les données déjà trouvées.
    """
    for key, value in new_data.items():
        if not value: 
            continue
        
        if key in global_data:
            if isinstance(global_data[key], dict) and isinstance(value, dict):
                merge_extracted_data(global_data[key], value)
            elif not global_data[key]: 
                global_data[key] = value
        else:
            global_data[key] = value
    return global_data

def estrai_da_grande_pdf(pdf_path: str, template: dict, model, tokenizer) -> dict:
    # OPTIMIZATION 1: Get the page count
    info = pdfinfo_from_path(pdf_path)
    total_pages = info["Pages"]
    print(f"Il documento contiene {total_pages} pagine.")
    
    # OPTIMIZATION 2: Convert ALL pages to images in one continuous thread
    # This prevents reopening the file header on every single iteration.
    print("Conversione del PDF in immagini...")
    pagine_immagini = convert_from_path(pdf_path)
    
    # OPTIMIZATION 3: Use native copy.deepcopy instead of json parsing for speed
    dati_finali = copy.deepcopy(template) 
    
    schema_str = json.dumps(template, indent=4)
    prompt = f"<|input|>\n### Template:\n{schema_str}\n### Image:\n<|image|>\n<|output|>\n"
    
    # Loop over pre-converted images
    for page_num, immagine_pagina in enumerate(pagine_immagini, start=1):
        print(f"\n--- Elaborazione Pagina {page_num} / {total_pages} ---")
        
        inputs = tokenizer(prompt, images=[immagine_pagina], return_tensors="pt").to(model.device)
        
        # OPTIMIZATION 4: Inference optimizations (use_cache=True explicitly, model.eval())
        with torch.inference_mode(): # Faster/cleaner version of no_grad
            outputs = model.generate(
                **inputs, 
                max_new_tokens=1000, 
                eos_token_id=tokenizer.eos_token_id,
                use_cache=True # Speeds up generation using KV cache tokens
            )
        
        prediction = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        
        try:
            nuovi_dati = json.loads(prediction)
            dati_finali = merge_extracted_data(dati_finali, nuovi_dati)
        except json.JSONDecodeError:
            print(f"Avviso: Errore di parsing JSON alla pagina {page_num}. Salto la pagina.")
            continue
            
    return dati_finali

# --- Esempio di utilizzo ---
if __name__ == "__main__":
    percorso_grande_pdf = (
        "/home/kathleen/90_DATA_PREPROCESS/italy_poc"
        "/output/documents"
        "/10009"
        "/10009_030-12_04-RelazioneTecnicoDescrittiva.pdf"
    ) 
    
    schema_estrazione = {
        "nome_progetto": "",
        "aerogeneratori": {
            "numero_turbine": "",
            "modello_turbina": "",
            "potenza_nominale": ""
        },
        "dimensioni_tecniche": {
            "altezza_totale": "",
            "altezza_mozzo": "",
            "diametro_rotore": "",
            "lunghezza_pala": ""
        }
    }
    
    # OPTIMIZATION 5: Load model ONCE outside the loops or execution contexts
    model_id = "numind/NuExtract3"
    print("Caricamento del modello...")
    global_tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True, cache_dir=custom_path)
    global_model = AutoModelForCausalLM.from_pretrained(
        model_id, 
        torch_dtype=torch.bfloat16, 
        device_map="auto", 
        trust_remote_code=True,
        cache_dir=custom_path
    )
    global_model.eval() # Freeze layers out of training mode for speed
    
    # OPTIMIZATION 6 (Optional Next Step): Compile for faster CUDA processing if available
    # global_model = torch.compile(global_model) 

    try:
        risultato_completo = estrai_da_grande_pdf(percorso_grande_pdf, schema_estrazione, global_model, global_tokenizer)
        print("\n================ RISULTATO FINALE COMPILATO ================")
        print(json.dumps(risultato_completo, indent=8, ensure_ascii=False))
    except FileNotFoundError:
        print(f"Errore: Inserisci il tuo file '{percorso_grande_pdf}' nella cartella.")

