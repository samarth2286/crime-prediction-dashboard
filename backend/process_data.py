import os
import hashlib
import pandas as pd
import sqlite3
from db_client import get_mongo_client, get_sql_conn

# --- Paths ---
CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "01_District_wise_crimes_committed_IPC_2001_2012.csv")

# --- State Centroids Dictionary ---
STATE_CENTROIDS = {
    'ANDHRA PRADESH': (15.9129, 79.7400),
    'ARUNACHAL PRADESH': (28.2180, 94.7278),
    'ASSAM': (26.2006, 92.9376),
    'BIHAR': (25.0961, 85.3131),
    'CHHATTISGARH': (21.2787, 81.8661),
    'GOA': (15.2993, 74.1240),
    'GUJARAT': (22.2587, 71.1924),
    'HARYANA': (29.0588, 76.0856),
    'HIMACHAL PRADESH': (31.1048, 77.1734),
    'JAMMU & KASHMIR': (33.7782, 76.5762),
    'JHARKHAND': (23.6102, 85.2799),
    'KARNATAKA': (15.3173, 75.7139),
    'KERALA': (10.8505, 76.2711),
    'MADHYA PRADESH': (22.9734, 78.6569),
    'MAHARASHTRA': (19.7515, 75.7139),
    'MANIPUR': (24.6637, 93.9063),
    'MEGHALAYA': (25.4670, 91.3662),
    'MIZORAM': (23.1645, 92.9376),
    'NAGALAND': (26.1584, 94.5624),
    'ODISHA': (20.5048, 84.4101),
    'PUNJAB': (31.1471, 75.3412),
    'RAJASTHAN': (27.0238, 74.2179),
    'SIKKIM': (27.5330, 88.5122),
    'TAMIL NADU': (11.1271, 78.6569),
    'TRIPURA': (23.9408, 91.9882),
    'UTTAR PRADESH': (26.8467, 80.9462),
    'UTTARAKHAND': (30.0668, 79.0193),
    'WEST BENGAL': (22.9868, 87.8550),
    'A & N ISLANDS': (11.7401, 92.6586),
    'CHANDIGARH': (30.7333, 76.7794),
    'D & N HAVELI': (20.1809, 73.0169),
    'DAMAN & DIU': (20.4283, 72.8397),
    'DELHI UT': (28.6139, 77.2090),
    'LAKSHADWEEP': (10.5726, 72.6417),
    'PUDUCHERRY': (11.9416, 79.8083)
}

def get_district_coordinates(state, district):
    state_upper = state.strip().upper()
    lat, lng = STATE_CENTROIDS.get(state_upper, (21.0, 78.0))
    
    # Generate deterministic offset using md5 hash of state + district
    h = hashlib.md5((state_upper + "_" + district.strip().upper()).encode('utf-8')).hexdigest()
    # Offsets in range [-0.5, 0.5] degrees so they stay within the state boundary
    offset_lat = (int(h[:4], 16) / 65535.0 - 0.5) * 1.0
    offset_lng = (int(h[4:8], 16) / 65535.0 - 0.5) * 1.0
    
    return round(lat + offset_lat, 4), round(lng + offset_lng, 4)

def get_district_population(state, district):
    dist_clean = district.strip().upper()
    state_clean = state.strip().upper()
    
    # Real population approximations for major Indian cities to add realism
    overrides = {
        'MUMBAI': 12442373,
        'MUMBAI COMM.': 12442373,
        'DELHI UT': 16787941,
        'BANGALORE': 8443675,
        'BANGALORE COMM.': 8443675,
        'PUNE': 3124458,
        'PUNE COMM.': 3124458,
        'KOLKATA': 4496694,
        'CHENNAI': 4646732,
        'HYDERABAD CITY': 6731790,
        'AHMEDABAD': 5577940,
        'AHMEDABAD COMM.': 5577940,
        'THANE': 11060148,
    }
    
    if dist_clean in overrides:
        return overrides[dist_clean]
    
    # Deterministic population generation between 300,000 and 2,500,000
    h = hashlib.md5((state_clean + "_" + dist_clean).encode('utf-8')).hexdigest()
    pop = 300000 + int(h[8:13], 16) % 2200000
    return pop

def main():
    print(f"Reading crime data from: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH)
    
    # 1. Clean Column Names
    # Map raw CSV columns to clean, standardized names
    column_mapping = {
        'STATE/UT': 'state',
        'DISTRICT': 'district',
        'YEAR': 'year',
        'MURDER': 'murder',
        'ATTEMPT TO MURDER': 'attempt_to_murder',
        'CULPABLE HOMICIDE NOT AMOUNTING TO MURDER': 'culpable_homicide',
        'RAPE': 'rape',
        'KIDNAPPING & ABDUCTION': 'kidnapping',
        'DACOITY': 'dacoity',
        'ROBBERY': 'robbery',
        'BURGLARY': 'burglary',
        'THEFT': 'theft',
        'RIOTS': 'riots',
        'CRIMINAL BREACH OF TRUST': 'breach_of_trust',
        'CHEATING': 'cheating',
        'COUNTERFIETING': 'counterfeiting',
        'ARSON': 'arson',
        'HURT/GREVIOUS HURT': 'hurt',
        'DOWRY DEATHS': 'dowry_deaths',
        'ASSAULT ON WOMEN WITH INTENT TO OUTRAGE HER MODESTY': 'assault_on_women',
        'INSULT TO MODESTY OF WOMEN': 'insult_to_modesty',
        'CRUELTY BY HUSBAND OR HIS RELATIVES': 'cruelty_by_husband',
        'IMPORTATION OF GIRLS FROM FOREIGN COUNTRIES': 'importation_of_girls',
        'CAUSING DEATH BY NEGLIGENCE': 'negligence',
        'OTHER IPC CRIMES': 'other_ipc_crimes',
        'TOTAL IPC CRIMES': 'total_ipc_crimes'
    }
    
    # Filter the dataframe to only keep the columns we map
    df = df.rename(columns=column_mapping)
    available_cols = [c for c in column_mapping.values() if c in df.columns]
    df = df[available_cols]
    
    # 2. Filter Summary Rows
    # Remove rows where the district contains "TOTAL"
    df = df[~df['district'].str.contains('TOTAL', case=False, na=False)]
    
    # Strip spaces and uppercase state and district names
    df['state'] = df['state'].str.strip().str.upper()
    df['district'] = df['district'].str.strip().str.upper()
    df['year'] = df['year'].astype(int)
    
    print(f"Cleaned dataset contains {df.shape[0]} rows and {df.shape[1]} columns.")
    
    # 3. Connect to Databases
    mongo_client = get_mongo_client()
    mongo_db = mongo_client['crime_db']
    raw_collection = mongo_db['raw_records']
    
    # Clear existing data in MongoDB
    raw_collection.delete_many({})
    
    # Get unique districts for SQL table population
    unique_districts = df.groupby(['state', 'district']).size().reset_index()[['state', 'district']]
    
    print("Populating SQL database...")
    sql_conn = get_sql_conn()
    cursor = sql_conn.cursor()
    
    # Create the districts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS districts (
            state_name TEXT,
            district_name TEXT,
            latitude REAL,
            longitude REAL,
            population INTEGER,
            latest_crime_rate_per_100k REAL,
            PRIMARY KEY (state_name, district_name)
        )
    """)
    cursor.execute("DELETE FROM districts") # clear previous metadata
    
    # Calculate latest (2012) crime rates to store in SQL metadata
    df_2012 = df[df['year'] == 2012]
    
    # Populate structured districts metadata
    districts_to_insert = []
    for idx, row in unique_districts.iterrows():
        st = row['state']
        dt = row['district']
        lat, lng = get_district_coordinates(st, dt)
        pop = get_district_population(st, dt)
        
        # Get 2012 total crimes for this district
        match_2012 = df_2012[(df_2012['state'] == st) & (df_2012['district'] == dt)]
        total_crimes_2012 = match_2012['total_ipc_crimes'].values[0] if not match_2012.empty else 0
        crime_rate_2012 = (total_crimes_2012 / pop) * 100000
        
        districts_to_insert.append((st, dt, lat, lng, pop, round(crime_rate_2012, 2)))
        
    cursor.executemany("""
        INSERT INTO districts (state_name, district_name, latitude, longitude, population, latest_crime_rate_per_100k)
        VALUES (?, ?, ?, ?, ?, ?)
    """, districts_to_insert)
    sql_conn.commit()
    sql_conn.close()
    print(f"Populated SQL database with {len(districts_to_insert)} districts.")
    
    # 4. Populate MongoDB with raw incident records
    print("Populating MongoDB (fallback) with raw records...")
    raw_records = []
    for idx, row in df.iterrows():
        # Build document structure
        doc = row.to_dict()
        # Separate features from crime counts
        crimes_dict = {
            k: int(v) for k, v in doc.items() 
            if k not in ['state', 'district', 'year', 'total_ipc_crimes']
        }
        
        mongo_doc = {
            'state': doc['state'],
            'district': doc['district'],
            'year': doc['year'],
            'total_ipc_crimes': int(doc['total_ipc_crimes']),
            'crimes': crimes_dict
        }
        raw_records.append(mongo_doc)
        
    # Insert in chunks of 1000 to keep it clean
    chunk_size = 1000
    for i in range(0, len(raw_records), chunk_size):
        raw_collection.insert_many(raw_records[i:i+chunk_size])
        
    print(f"Populated MongoDB with {len(raw_records)} documents.")
    print("Data processing completed successfully.")

if __name__ == "__main__":
    main()
