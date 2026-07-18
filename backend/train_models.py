import os
import joblib
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from xgboost import XGBClassifier

# Import helpers from process_data for consistency
from process_data import get_district_population, CSV_PATH

# Define top 10 crime categories for mapping
CRIME_COLUMNS_MAPPING = {
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

def load_and_preprocess_data():
    print(f"Loading CSV from {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH)
    
    # Standardize names
    df = df.rename(columns={
        'STATE/UT': 'state',
        'DISTRICT': 'district',
        'YEAR': 'year',
        'TOTAL IPC CRIMES': 'total_ipc_crimes',
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
        'OTHER IPC CRIMES': 'other_ipc_crimes'
    })
    
    # Filter summary rows
    df = df[~df['district'].str.contains('TOTAL', case=False, na=False)]
    df['state'] = df['state'].str.strip().str.upper()
    df['district'] = df['district'].str.strip().str.upper()
    df['year'] = df['year'].astype(int)
    
    # Calculate population and crime rate per 100k
    print("Calculating populations and crime rates...")
    df['population'] = df.apply(lambda r: get_district_population(r['state'], r['district']), axis=1)
    df['crime_rate_per_100k'] = (df['total_ipc_crimes'] / df['population']) * 100000
    
    # Define Risk Level based on percentiles of crime_rate_per_100k
    p33 = df['crime_rate_per_100k'].percentile(33) if hasattr(df['crime_rate_per_100k'], 'percentile') else np.percentile(df['crime_rate_per_100k'], 33)
    p66 = df['crime_rate_per_100k'].percentile(66) if hasattr(df['crime_rate_per_100k'], 'percentile') else np.percentile(df['crime_rate_per_100k'], 66)
    
    print(f"Risk level thresholds: p33={p33:.2f}, p66={p66:.2f}")
    
    def get_risk_label(rate):
        if rate <= p33:
            return 0  # LOW
        elif rate <= p66:
            return 1  # MEDIUM
        else:
            return 2  # HIGH
            
    df['risk_level'] = df['crime_rate_per_100k'].apply(get_risk_label)
    
    return df, p33, p66

def main():
    df, p33, p66 = load_and_preprocess_data()
    
    # Initialize and fit encoders
    print("Encoding categorical labels...")
    state_encoder = LabelEncoder()
    district_encoder = LabelEncoder()
    
    # We add an 'UNKNOWN' label to allow robust fallback in production
    states = list(df['state'].unique()) + ['UNKNOWN']
    districts = list(df['district'].unique()) + ['UNKNOWN']
    
    state_encoder.fit(states)
    district_encoder.fit(districts)
    
    df['state_encoded'] = state_encoder.transform(df['state'])
    df['district_encoded'] = district_encoder.transform(df['district'])
    
    # --- Train Model 1: Crime Hotspot Classifier (Random Forest) ---
    print("\n--- Training Model 1: Crime Hotspot Classifier ---")
    X1 = df[['state_encoded', 'district_encoded', 'year']]
    y1 = df['risk_level']
    
    X1_train, X1_test, y1_train, y1_test = train_test_split(X1, y1, test_size=0.2, random_state=42, stratify=y1)
    
    rf_model = RandomForestClassifier(n_estimators=100, max_depth=12, random_state=42)
    rf_model.fit(X1_train, y1_train)
    
    y1_pred = rf_model.predict(X1_test)
    print("Random Forest Classifier Results:")
    print(classification_report(y1_test, y1_pred, target_names=['LOW', 'MEDIUM', 'HIGH']))
    
    # Fit full model
    rf_model.fit(X1, y1)
    
    # --- Train Model 3: Total Cases Regressor (Random Forest Regressor) ---
    print("\n--- Training Model 3: Total Crimes Regressor ---")
    y_reg = df['total_ipc_crimes']
    reg_model = RandomForestRegressor(n_estimators=100, max_depth=12, random_state=42)
    reg_model.fit(X1, y_reg)
    print("Total Crimes Regressor trained.")
    
    # --- Train Model 2: Crime Type Predictor (XGBoost) ---
    print("\n--- Training Model 2: Crime Type Predictor ---")
    
    # Reshape data into weighted multi-class dataset
    expanded_rows = []
    
    # Categories mapped to standard names
    crime_categories = list(CRIME_COLUMNS_MAPPING.keys())
    
    # Target encoding for crimes: index 0 to 9
    crime_encoder = LabelEncoder()
    crime_labels = list(CRIME_COLUMNS_MAPPING.values())
    crime_encoder.fit(crime_labels)
    
    print("Expanding aggregated counts into weighted rows...")
    for idx, row in df.iterrows():
        st_enc = row['state_encoded']
        dt_enc = row['district_encoded']
        yr = row['year']
        
        # Add a sample for each crime type
        for col, display_name in CRIME_COLUMNS_MAPPING.items():
            count = int(row.get(col, 0))
            if count > 0:
                expanded_rows.append({
                    'state_encoded': st_enc,
                    'district_encoded': dt_enc,
                    'year': yr,
                    'crime_type': display_name,
                    'weight': count
                })
                
    df_expanded = pd.DataFrame(expanded_rows)
    df_expanded['crime_type_encoded'] = crime_encoder.transform(df_expanded['crime_type'])
    
    X2 = df_expanded[['state_encoded', 'district_encoded', 'year']]
    y2 = df_expanded['crime_type_encoded']
    weights = df_expanded['weight']
    
    X2_train, X2_test, y2_train, y2_test, w_train, w_test = train_test_split(
        X2, y2, weights, test_size=0.2, random_state=42, stratify=y2
    )
    
    xgb_model = XGBClassifier(
        n_estimators=80, 
        max_depth=6, 
        learning_rate=0.1, 
        random_state=42, 
        objective='multi:softprob'
    )
    xgb_model.fit(X2_train, y2_train, sample_weight=w_train)
    
    y2_pred = xgb_model.predict(X2_test)
    print("XGBoost Multiclass Classifier Results (Top Crime Types):")
    print(classification_report(y2_test, y2_pred, target_names=crime_labels, sample_weight=w_test))
    
    # Fit full model
    xgb_model.fit(X2, y2, sample_weight=weights)
    
    # --- Save Encoders and Models ---
    print("\nSaving models and encoders to disk...")
    encoders = {
        'state_encoder': state_encoder,
        'district_encoder': district_encoder,
        'crime_encoder': crime_encoder,
        'p33': p33,
        'p66': p66
    }
    
    os.makedirs(os.path.dirname(__file__), exist_ok=True)
    joblib.dump(encoders, os.path.join(os.path.dirname(__file__), "label_encoders.joblib"))
    joblib.dump(rf_model, os.path.join(os.path.dirname(__file__), "hotspot_model.joblib"))
    joblib.dump(xgb_model, os.path.join(os.path.dirname(__file__), "crime_type_model.joblib"))
    joblib.dump(reg_model, os.path.join(os.path.dirname(__file__), "total_crimes_model.joblib"))
    
    print("All models trained and saved successfully.")

if __name__ == "__main__":
    main()
