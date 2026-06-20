import sys
from datetime import datetime, timedelta
import random
from werkzeug.security import generate_password_hash
from database import db

def seed_data():
    print("Starting full database seeding for all network PHCs...")
    
    # Initialize database tables if they do not exist (critical for fresh Render builds)
    db.init_db()
    
    # 1. Clear existing data (to allow clean re-seeding)
    print("Clearing old tables...")
    tables = [
        "reports", "ai_submissions", "patient_statistics", 
        "disease_trends", "shortage_alerts", "medicine_requests", 
        "inventory_history", "inventory", "medicines", "users", "phcs"
    ]
    for table in tables:
        try:
            db.execute(f"DELETE FROM {table};")
        except Exception as e:
            print(f"Notice: clearing table {table} failed: {e}")
            
    # Reset SQLite sequence counters to reset auto-increment primary keys to 1
    if not db.is_postgres:
        try:
            db.execute("DELETE FROM sqlite_sequence;")
            print("SQLite sequence counters reset.")
        except Exception as e:
            print(f"Notice: resetting sqlite_sequence failed: {e}")

    # 2. Sync PHCs from Supabase
    print("Fetching and syncing PHCs from Supabase...")
    db.sync_phcs_from_supabase()
    
    # Fetch all PHCs loaded from Supabase
    phc_list = db.query("SELECT * FROM phcs", fetch_all=True)
    if not phc_list:
        print("No PHCs available. Seeding failed.")
        return
        
    print(f"Seeding dataset for {len(phc_list)} integrated PHCs...")

    # Find the first PHC ID to bind the 3 demo users
    first_phc_id = phc_list[0]['id']

    # 3. Seed Users (mapped to the first PHC for session login, Switcher handles context)
    print("Inserting user accounts...")
    users = [
        ("supervisor", generate_password_hash("password123"), "Dr. Anil Kumar", "Supervisor", first_phc_id),
        ("officer", generate_password_hash("password123"), "Dr. Sneha Patil", "Medical Officer", first_phc_id),
        ("operator", generate_password_hash("password123"), "Rajesh Gowda", "Data Entry Operator", first_phc_id)
    ]
    for username, pw_hash, name, role, phc_id in users:
        db.execute(
            "INSERT INTO users (username, password_hash, full_name, role, phc_id) VALUES (%s, %s, %s, %s, %s);",
            (username, pw_hash, name, role, phc_id)
        )
        
    supervisor_user = db.query("SELECT id FROM users WHERE username = 'supervisor'", fetch_one=True)
    supervisor_id = supervisor_user['id'] if supervisor_user else 1

    # 4. Seed Base Medicines Formulary
    print("Inserting medicines formulary...")
    medicines = [
        (1, "Paracetamol 650mg", "Analgesics", "Cipla Ltd", "Tablet"),
        (2, "Amoxicillin 500mg", "Antibiotics", "Alkem Laboratories", "Tablet"),
        (3, "Metformin 500mg", "Antidiabetics", "Sun Pharma", "Tablet"),
        (4, "Cetirizine 10mg", "Antihistamines", "Dr. Reddy's", "Tablet"),
        (5, "ORS Sachet 21.8g", "Rehydration", "FDC Ltd", "Sachet"),
        (6, "Cough Syrup 100ml", "Respiratory", "Abbott India", "Syrup"),
        (7, "Amlodipine 5mg", "Antihypertensives", "Lupin Ltd", "Tablet"),
        (8, "Ibuprofen 400mg", "Analgesics", "Cipla Ltd", "Tablet"),
        (9, "Azithromycin 500mg", "Antibiotics", "Sun Pharma", "Tablet"),
        (10, "Pantoprazole 40mg", "Antacids", "Alkem Laboratories", "Tablet"),
        (11, "Atorvastatin 10mg", "Cardiovascular", "Zydus Cadila", "Tablet"),
        (12, "Omeprazole 20mg", "Antacids", "Torrent Pharmaceuticals", "Capsule"),
        (13, "Losartan 50mg", "Antihypertensives", "Glenmark", "Tablet"),
        (14, "Metoprolol 50mg", "Cardiovascular", "IPCA Laboratories", "Tablet"),
        (15, "Salbutamol Inhaler", "Respiratory", "Cipla Ltd", "Inhaler"),
        (16, "Ranitidine 150mg", "Antacids", "Cadila Healthcare", "Tablet"),
        (17, "Ciprofloxacin 500mg", "Antibiotics", "Cipla Ltd", "Tablet"),
        (18, "Folic Acid 5mg", "Vitamins/Supplements", "Emcure", "Tablet"),
        (19, "Iron Supplement", "Vitamins/Supplements", "Abbott India", "Tablet"),
        (20, "Albendazole 400mg", "Antiparasitic", "GlaxoSmithKline", "Tablet"),
        (21, "Azelastine Nasal Spray", "Antihistamines", "Cipla Ltd", "Spray"),
        (22, "Calcium + Vitamin D3", "Vitamins/Supplements", "Shelcal", "Tablet"),
        (23, "Diazepam 5mg", "Sedatives", "Ranbaxy", "Tablet"),
        (24, "Diclofenac Gel 30g", "Analgesics", "Novartis", "Ointment"),
        (25, "Domperidone 10mg", "Antiemetics", "Janssen", "Tablet"),
        (26, "Erythromycin 250mg", "Antibiotics", "Abbott India", "Tablet"),
        (27, "Gliclazide 80mg", "Antidiabetics", "Servier", "Tablet"),
        (28, "Hydrochlorothiazide 12.5mg", "Diuretics", "Lupin Ltd", "Tablet"),
        (29, "Levofloxacin 500mg", "Antibiotics", "Sanofi", "Tablet"),
        (30, "Prednisolone 5mg", "Corticosteroids", "Pfizer", "Tablet")
    ]
    for med_id, name, category, manufacturer, form in medicines:
        db.execute(
            "INSERT INTO medicines (id, name, category, manufacturer, dosage_form) VALUES (%s, %s, %s, %s, %s);",
            (med_id, name, category, manufacturer, form)
        )

    # Fetch medicines as dicts (needed for seed_phc_data)
    medicines_db = db.query("SELECT * FROM medicines", fetch_all=True)

    # 5. Generate and Shuffle Unique Metric Combinations
    # Tuple format: (num_available, num_low, num_critical, num_pending)
    combinations = []
    for a in range(12, 21):          # 9 values (12 to 20 available meds)
        for l in range(1, 5):       # 4 values (1 to 4 low stock warning)
            for c in range(1, 5):   # 4 values (1 to 4 critical shortages)
                for p in range(0, 4): # 4 values (0 to 3 pending requests)
                    combinations.append((a, l, c, p))
                    
    random.shuffle(combinations)
    
    if len(combinations) < len(phc_list):
        print(f"Warning: Not enough unique combinations ({len(combinations)}) for {len(phc_list)} PHCs.")
        while len(combinations) < len(phc_list):
            extra = combinations.copy()
            random.shuffle(extra)
            combinations.extend(extra)

    # 6. Seed Unique Data for each of the 120 PHCs
    print("Generating unique parameters per health centre...")
    today = datetime.now()
    
    for idx, phc in enumerate(phc_list):
        phc_id = phc['id']
        phc_district = phc['district']
        target_counts = combinations[idx]
        
        db.seed_phc_data(
            phc_id=phc_id,
            district=phc_district,
            target_counts=target_counts,
            medicines=medicines_db,
            supervisor_id=supervisor_id,
            today=today
        )
        
    print(f"Database successfully seeded for all {len(phc_list)} PHCs.")

if __name__ == '__main__':
    seed_data()
