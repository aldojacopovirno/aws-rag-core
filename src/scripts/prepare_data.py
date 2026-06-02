import json
import csv
import os
import math
import sys
import argparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.config_manager import ConfigManager

def clean_numeric(val):
    """
    Pulisce e valida un valore di input, convertendolo in float dove possibile.
    
    Parameters
    ----------
    val : any
        Il valore in ingresso da sanificare.
        
    Returns
    -------
    float or str
        Float valido o stringa vuota in caso di dato mancante/invalido.
    """
    if val is None:
        return ''
    if isinstance(val, (int, float)):
        if math.isnan(val):
            return ''
        return val
    val_str = str(val).strip().lower()
    if val_str in ('nan', 'null', 'none', ''):
        return ''
    try:
        return float(val)
    except ValueError:
        return ''

def clean_string(val):
    """
    Pulisce e valida un valore di input stringa.
    
    Parameters
    ----------
    val : any
        Il valore stringa in ingresso.
        
    Returns
    -------
    str
        Stringa ripulita o vuota in caso di null.
    """
    if val is None:
        return ''
    val_str = str(val).strip()
    if val_str.lower() in ('nan', 'null', 'none', ''):
        return ''
    return val_str

def prepare_data(input_file: str, output_dir: str):
    """
    Elabora un file JSON sorgente convertendolo in CSV formattati per la 
    Knowledge Base AWS Bedrock, generando i file di configurazione metadati (.metadata.json).
    Si appoggia al domain_schema per configurare dinamicamente i field.
    
    Parameters
    ----------
    input_file : str
        Path al file JSON contenente i dati raw.
    output_dir : str
        Directory di destinazione per i CSV e i metadati.
    """
    config_manager = ConfigManager(schema_file_path='config/domain_schema.json')
    schema_fields = config_manager.get_metadata_fields()
    content_field = config_manager.get_content_field()
    
    print(f"Reading input file: {input_file}...")
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            records = json.load(f)
    except Exception as e:
        print(f"Error reading {input_file}: {e}")
        return
        
    total_records = len(records)
    print(f"Loaded {total_records} records.")
    
    chunk_size = 2000
    num_chunks = math.ceil(total_records / chunk_size)
    
    # Dinamicamente costruisce gli header dal domain_schema
    metadata_names = [f["name"] for f in schema_fields]
    headers = ['id', content_field] + metadata_names
    
    metadata_fields_specification = [{"fieldName": name} for name in metadata_names]
    
    metadata_template = {
        "metadataAttributes": {
            "source": "domain_dataset"
        },
        "documentStructureConfiguration": {
            "type": "RECORD_BASED_STRUCTURE_METADATA",
            "recordBasedStructureMetadata": {
                "contentFields": [{"fieldName": content_field}],
                "metadataFieldsSpecification": {
                    "fieldsToInclude": metadata_fields_specification
                }
            }
        }
    }
    
    os.makedirs(output_dir, exist_ok=True)
    
    for i in range(num_chunks):
        chunk_records = records[i * chunk_size : (i + 1) * chunk_size]
        if not chunk_records:
            break
            
        csv_filename = f"dataset_{i + 1}.csv"
        csv_path = os.path.join(output_dir, csv_filename)
        metadata_filename = f"dataset_{i + 1}.csv.metadata.json"
        metadata_path = os.path.join(output_dir, metadata_filename)
        
        print(f"Writing {len(chunk_records)} records to {csv_path}...")
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as csv_file:
            writer = csv.writer(csv_file, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(headers)
            
            for rec in chunk_records:
                m = rec.get('metadata', {})
                row = [
                    rec.get('id', ''),
                    rec.get(content_field, '')
                ]
                # Appende i metadati dinamici
                for f in schema_fields:
                    fname = f['name']
                    ftype = f['type']
                    if ftype == 'float' or ftype == 'integer':
                        row.append(clean_numeric(m.get(fname)))
                    else:
                        row.append(clean_string(m.get(fname)))
                writer.writerow(row)
                
        print(f"Writing metadata config to {metadata_path}...")
        with open(metadata_path, 'w', encoding='utf-8') as meta_file:
            json.dump(metadata_template, meta_file, indent=2)

    print("Data preparation completed successfully!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare dataset for Bedrock KB.")
    parser.add_argument("--input", type=str, required=True, help="Input JSON file")
    parser.add_argument("--outdir", type=str, required=True, help="Output directory")
    args = parser.parse_args()
    prepare_data(args.input, args.outdir)
