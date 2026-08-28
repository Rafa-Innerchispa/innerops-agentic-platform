#!/usr/bin/env python3
"""
Script de importación local del Catastro General del SRI a MongoDB.
Permite descargar e indexar el archivo oficial del SRI de Ecuador o semilla pre-cargada.
"""

import os
import sys
import zipfile
import requests
import io
import argparse

# Include project path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from raphiia_openai.mongo_store import get_db

# Pre-populated prominent Ecuadorian companies for immediate offline validation
SEED_COMPANIES = [
    {
        "ruc": "1790016919001",
        "name": "CORPORACION FAVORITA C.A.",
        "address": "Av. General Enríquez s/n, Sangolquí",
        "city": "Sangolquí",
        "status": "ACTIVO"
    },
    {
        "ruc": "1790010932001",
        "name": "PRONACA PROCESADORA DE AVES AVICOLA C.A.",
        "address": "Los Shyris 2680 y Gaspar de Villarroel, Quito",
        "city": "Quito",
        "status": "ACTIVO"
    },
    {
        "ruc": "1791251237001",
        "name": "CONECEL S.A. (CLARO)",
        "address": "Av. Francisco de Orellana y Alberto Borges, Guayaquil",
        "city": "Guayaquil",
        "status": "ACTIVO"
    },
    {
        "ruc": "0990026238001",
        "name": "OTECEL S.A. (MOVISTAR)",
        "address": "Av. República de El Salvador N36-84, Quito",
        "city": "Quito",
        "status": "ACTIVO"
    },
    {
        "ruc": "1790010045001",
        "name": "BANCO PICHINCHA C.A.",
        "address": "Av. Amazonas 4560 y Pereira, Quito",
        "city": "Quito",
        "status": "ACTIVO"
    },
    {
        "ruc": "0990005737001",
        "name": "BANCO GUAYAQUIL S.A.",
        "address": "P. Carbo 317 y 9 de Octubre, Guayaquil",
        "city": "Guayaquil",
        "status": "ACTIVO"
    },
    {
        "ruc": "1790022234001",
        "name": "CERVECERIA NACIONAL CN S.A.",
        "address": "Vía a Daule Km 16.5, Guayaquil",
        "city": "Guayaquil",
        "status": "ACTIVO"
    },
    {
        "ruc": "1790009454001",
        "name": "DIFARE S.A. (FARMACIAS FYBECA / SANA SANA)",
        "address": "Av. de las Américas s/n, Guayaquil",
        "city": "Guayaquil",
        "status": "ACTIVO"
    }
]

def seed_database():
    db = get_db()
    col = db["sri_catastro"]
    
    # Create indexes for fast lookup
    col.create_index("ruc", unique=True)
    
    count = 0
    for company in SEED_COMPANIES:
        res = col.update_one(
            {"ruc": company["ruc"]},
            {"$set": company},
            upsert=True
        )
        if res.upserted_id or res.modified_count:
            count += 1
            
    print(f"Semilla insertada/actualizada con éxito: {count} registros clave.")

def download_and_import(url: str):
    print(f"Descargando catastro SRI de: {url} ...")
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        
        # Extract zip file
        z = zipfile.ZipFile(io.BytesIO(r.content))
        file_names = z.namelist()
        print(f"Archivos en el ZIP: {file_names}")
        
        # Read the first txt/csv file
        target_file = [f for f in file_names if f.endswith('.txt') or f.endswith('.csv')][0]
        with z.open(target_file) as f:
            db = get_db()
            col = db["sri_catastro"]
            
            # Process lines (CSV)
            import csv
            reader = csv.reader(io.TextIOWrapper(f, encoding='utf-8', errors='ignore'), delimiter='|')
            
            count = 0
            for row in reader:
                # SRI format parsing (adjust fields as per SRI layout)
                if len(row) >= 3:
                    ruc = row[0].strip()
                    name = row[1].strip()
                    city = row[2].strip() if len(row) > 2 else ""
                    
                    if len(ruc) == 13 and ruc.isdigit():
                        col.update_one(
                            {"ruc": ruc},
                            {"$set": {"ruc": ruc, "name": name, "city": city, "status": "ACTIVO"}},
                            upsert=True
                        )
                        count += 1
                        if count % 10000 == 0:
                            print(f"Importados {count} registros...")
                            
            print(f"Importación masiva completada: {count} RUCs guardados localmente.")
    except Exception as e:
        print(f"Error en descarga/importación: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Importador SRI Catastro")
    parser.add_argument("--seed", action="store_true", help="Cargar datos de semilla de grandes empresas")
    parser.add_argument("--url", type=str, help="URL del ZIP del Catastro SRI")
    
    args = parser.parse_args()
    
    if args.seed or not args.url:
        seed_database()
        
    if args.url:
        download_and_import(args.url)
