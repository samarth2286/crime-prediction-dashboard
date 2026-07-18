import os
import joblib
import logging
import sqlite3
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from db_client import get_mongo_client, get_sql_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# Paths to models
BASE_DIR = os.path.dirname(__file__)
ENCODERS_PATH = os.path.join(BASE_DIR, "label_encoders.joblib")
HOTSPOT_MODEL_PATH = os.path.join(BASE_DIR, "hotspot_model.joblib")
CRIME_TYPE_MODEL_PATH = os.path.join(BASE_DIR, "crime_type_model.joblib")
TOTAL_CRIMES_MODEL_PATH = os.path.join(BASE_DIR, "total_crimes_model.joblib")

# Globals for models and encoders
encoders = None
hotspot_model = None
crime_type_model = None
total_crimes_model = None

def load_all_models():
    global encoders, hotspot_model, crime_type_model, total_crimes_model
    try:
        logger.info("Loading machine learning models and encoders...")
        encoders = joblib.load(ENCODERS_PATH)
        hotspot_model = joblib.load(HOTSPOT_MODEL_PATH)
        crime_type_model = joblib.load(CRIME_TYPE_MODEL_PATH)
        total_crimes_model = joblib.load(TOTAL_CRIMES_MODEL_PATH)
        logger.info("All models loaded successfully.")
    except Exception as e:
        logger.error(f"Error loading models: {e}")
        logger.warning("Backend starting without models. Ensure train_models.py has run successfully.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load ML models
    load_all_models()
    yield
    # Shutdown: Clean up resources if needed
    pass

app = FastAPI(
    title="Crime Prediction System API",
    description="Backend API for predicting and analyzing crime hotspots and types in India.",
    lifespan=lifespan
)

# Enable CORS for frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins in development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def encode_value(encoder, val, field_name="value"):
    val_upper = str(val).strip().upper()
    if val_upper in encoder.classes_:
        return int(encoder.transform([val_upper])[0])
    # Fallback to UNKNOWN
    if "UNKNOWN" in encoder.classes_:
        return int(encoder.transform(["UNKNOWN"])[0])
    # If no UNKNOWN fallback exists, use the first class to prevent crash
    logger.warning(f"Value '{val_upper}' not found in encoder for {field_name} and no 'UNKNOWN' class exists. Using fallback 0.")
    return 0

# --- API Endpoints ---

@app.get("/")
def read_root():
    return {"status": "running", "message": "Crime Prediction API is active."}

@app.get("/districts")
def get_districts():
    """Returns a structured dictionary mapping states to their lists of districts."""
    try:
        conn = get_sql_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT state_name, district_name FROM districts ORDER BY state_name, district_name")
        rows = cursor.fetchall()
        conn.close()
        
        result = {}
        for row in rows:
            state = row['state_name']
            district = row['district_name']
            if state not in result:
                result[state] = []
            result[state].append(district)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

@app.get("/predict")
def predict(
    state: str = Query(..., description="Name of the State"),
    district: str = Query(..., description="Name of the District"),
    year: int = Query(..., description="Year to predict for")
):
    """
    Takes state, district, and year and returns:
    1. Predicted Risk Level (LOW, MEDIUM, HIGH)
    2. Most likely crime type and probability distribution
    3. Total predicted crime cases
    """
    if hotspot_model is None or crime_type_model is None or total_crimes_model is None:
        raise HTTPException(status_code=503, detail="Machine learning models are not loaded on server. Run training first.")
        
    state_str = state.strip().upper()
    district_str = district.strip().upper()
    
    try:
        # Encode inputs
        state_enc = encode_value(encoders['state_encoder'], state_str, "state")
        district_enc = encode_value(encoders['district_encoder'], district_str, "district")
        
        # 1. Predict Risk Level (Model 1)
        features = [[state_enc, district_enc, year]]
        risk_class = int(hotspot_model.predict(features)[0])
        risk_labels = {0: "LOW", 1: "MEDIUM", 2: "HIGH"}
        risk_level = risk_labels.get(risk_class, "MEDIUM")
        
        # 2. Predict Total Crimes (Model 3)
        total_predicted = int(round(max(0, float(total_crimes_model.predict(features)[0]))))
        
        # 3. Predict Crime Type Probabilities (Model 2)
        # XGBoost outputs multiclass probabilities
        probs = crime_type_model.predict_proba(features)[0]
        crime_encoder = encoders['crime_encoder']
        
        crime_preds = {}
        for idx, prob in enumerate(probs):
            crime_name = crime_encoder.classes_[idx]
            # Convert to float and round to 4 decimal places
            crime_preds[crime_name] = round(float(prob), 4)
            
        # Sort crime predictions by probability descending
        sorted_crimes = dict(sorted(crime_preds.items(), key=lambda item: item[1], reverse=True))
        most_likely = list(sorted_crimes.keys())[0]
        
        return {
            "state": state_str,
            "district": district_str,
            "year": year,
            "risk_level": risk_level,
            "most_likely_crime": most_likely,
            "crime_prediction": sorted_crimes,
            "total_predicted": total_predicted
        }
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=f"Prediction error: {e}")

@app.get("/history")
def get_history(
    state: str = Query(..., description="Name of the State"),
    district: str = Query(..., description="Name of the District")
):
    """Retrieves historical raw crime records from MongoDB for a state and district."""
    state_str = state.strip().upper()
    district_str = district.strip().upper()
    
    try:
        mongo_client = get_mongo_client()
        mongo_db = mongo_client['crime_db']
        raw_collection = mongo_db['raw_records']
        
        # Fetch documents
        records = raw_collection.find({"state": state_str, "district": district_str})
        
        # Sort by year ascending
        records = sorted(records, key=lambda x: x.get('year', 0))
        
        # Remove MongoDB '_id' field for JSON serialization
        for r in records:
            if "_id" in r:
                del r["_id"]
                
        return records
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

@app.get("/map-data")
def get_map_data(year: int = Query(2012, description="Year for which to retrieve map risk levels")):
    """
    Returns data for all districts to be displayed on the map:
    - Coordinates (lat/long)
    - Population
    - Total Crimes
    - Crime Rate per 100k
    - Risk Level (Red, Orange, Green)
    - Breakdown of crimes
    Uses historical actual data if year <= 2012, otherwise falls back to ML predictions.
    """
    try:
        # 1. Fetch metadata of all districts from SQL
        sql_conn = get_sql_conn()
        cursor = sql_conn.cursor()
        cursor.execute("SELECT state_name, district_name, latitude, longitude, population FROM districts")
        districts = cursor.fetchall()
        sql_conn.close()
        
        # 2. Check if we have historical data in MongoDB for this year
        is_historical = (year <= 2012)
        
        mongo_records = {}
        if is_historical:
            # Query all MongoDB documents for this year to show actual records
            mongo_client = get_mongo_client()
            mongo_db = mongo_client['crime_db']
            raw_collection = mongo_db['raw_records']
            docs = raw_collection.find({"year": year})
            for doc in docs:
                key = (doc['state'], doc['district'])
                mongo_records[key] = doc
                
        # Load thresholds for classifying risk levels
        p33 = encoders['p33'] if encoders else 150.0
        p66 = encoders['p66'] if encoders else 380.0
        
        map_points = []
        for dist in districts:
            st = dist['state_name']
            dt = dist['district_name']
            lat = dist['latitude']
            lng = dist['longitude']
            pop = dist['population']
            key = (st, dt)
            
            if is_historical and key in mongo_records:
                doc = mongo_records[key]
                total_crimes = doc['total_ipc_crimes']
                rate = (total_crimes / pop) * 100000
                
                # Determine risk level based on thresholds
                if rate <= p33:
                    risk = "LOW"
                elif rate <= p66:
                    risk = "MEDIUM"
                else:
                    risk = "HIGH"
                
                # Crime breakdown from MongoDB
                # Convert the values to display percentages for the chart
                crimes_dict = doc['crimes']
                total_mapped_crimes = sum(crimes_dict.values())
                
                # Map specific crime keys to match display names
                display_crimes = {}
                from process_data import CSV_PATH
                # Standard mapping
                mapping = {
                    'theft': 'Theft',
                    'hurt': 'Hurt',
                    'cheating': 'Cheating',
                    'burglary': 'Burglary',
                    'murder': 'Murder',
                    'rape': 'Rape',
                    'kidnapping': 'Kidnapping',
                    'robbery': 'Robbery',
                    'riots': 'Riots',
                    'arson': 'Arson'
                }
                
                for k, v in crimes_dict.items():
                    disp = mapping.get(k, k.capitalize())
                    display_crimes[disp] = display_crimes.get(disp, 0) + v
                
                # Normalize values to percentages
                normalized_crimes = {}
                if total_mapped_crimes > 0:
                    for k, v in display_crimes.items():
                        # Keep only the top 10 categories we care about
                        if k in mapping.values():
                            normalized_crimes[k] = round(v / total_mapped_crimes, 4)
                
                map_points.append({
                    "state": st,
                    "district": dt,
                    "latitude": lat,
                    "longitude": lng,
                    "population": pop,
                    "total_crimes": total_crimes,
                    "crime_rate_per_100k": round(rate, 2),
                    "risk_level": risk,
                    "is_prediction": False,
                    "crime_prediction": normalized_crimes
                })
            else:
                # Run ML model prediction for this future year
                if hotspot_model is None or total_crimes_model is None or crime_type_model is None:
                    # If models aren't loaded, return standard placeholder
                    map_points.append({
                        "state": st,
                        "district": dt,
                        "latitude": lat,
                        "longitude": lng,
                        "population": pop,
                        "total_crimes": 0,
                        "crime_rate_per_100k": 0.0,
                        "risk_level": "LOW",
                        "is_prediction": True,
                        "crime_prediction": {}
                    })
                    continue
                    
                state_enc = encode_value(encoders['state_encoder'], st, "state")
                district_enc = encode_value(encoders['district_encoder'], dt, "district")
                features = [[state_enc, district_enc, year]]
                
                # Predict Risk
                risk_class = int(hotspot_model.predict(features)[0])
                risk_labels = {0: "LOW", 1: "MEDIUM", 2: "HIGH"}
                risk = risk_labels.get(risk_class, "MEDIUM")
                
                # Predict Total
                total_crimes = int(round(max(0, float(total_crimes_model.predict(features)[0]))))
                rate = (total_crimes / pop) * 100000
                
                # Predict breakdown
                probs = crime_type_model.predict_proba(features)[0]
                crime_encoder = encoders['crime_encoder']
                normalized_crimes = {}
                for idx, prob in enumerate(probs):
                    crime_name = crime_encoder.classes_[idx]
                    normalized_crimes[crime_name] = round(float(prob), 4)
                    
                map_points.append({
                    "state": st,
                    "district": dt,
                    "latitude": lat,
                    "longitude": lng,
                    "population": pop,
                    "total_crimes": total_crimes,
                    "crime_rate_per_100k": round(rate, 2),
                    "risk_level": risk,
                    "is_prediction": True,
                    "crime_prediction": normalized_crimes
                })
                
        return map_points
    except Exception as e:
        logger.error(f"Error compiling map-data: {e}")
        raise HTTPException(status_code=500, detail=f"Database or prediction error: {e}")
