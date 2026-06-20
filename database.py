import os
import sqlite3
from urllib.parse import urlparse
from config import Config

# Dynamic PostgreSQL loading to prevent errors if psycopg2 is not installed
psycopg2 = None
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    pass

class Database:
    def __init__(self):
        self.db_url = Config.DATABASE_URL
        self.is_postgres = self.db_url.startswith('postgresql://') or self.db_url.startswith('postgres://')
        
        if self.is_postgres and psycopg2 is None:
            print("WARNING: PostgreSQL connection requested but psycopg2 is not installed. Falling back to SQLite.")
            self.is_postgres = False
            self.db_url = 'sqlite:///rhim_phc.db'
            
        self.sqlite_db_path = 'rhim_phc.db'
        if not self.is_postgres:
            # Parse sqlite path if configured via url format e.g. sqlite:///path
            if self.db_url.startswith('sqlite:///'):
                self.sqlite_db_path = self.db_url.replace('sqlite:///', '')

    def get_connection(self):
        if self.is_postgres:
            return psycopg2.connect(self.db_url)
        else:
            conn = sqlite3.connect(self.sqlite_db_path)
            conn.row_factory = sqlite3.Row
            # Enable foreign keys in SQLite
            conn.execute("PRAGMA foreign_keys = ON;")
            return conn

    def query(self, sql, params=None, fetch_one=False, fetch_all=False, commit=False):
        """
        Executes a query and handles DB-agnostic parameters.
        Use %s for parameter placeholders. They will be automatically converted to ? for SQLite.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Translate query placeholders for SQLite
        if not self.is_postgres:
            sql = sql.replace('%s', '?')
            
        try:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
                
            result = None
            if fetch_one:
                if self.is_postgres:
                    # Convert psycopg2 tuple or RealDict to regular dict
                    row = cursor.fetchone()
                    if row:
                        # If RealDictCursor is not used, fetchone returns a tuple, so we need dict conversion
                        # By default we will handle it as a dictionary or tuple
                        if hasattr(cursor, 'description') and cursor.description:
                            columns = [col[0] for col in cursor.description]
                            result = dict(zip(columns, row)) if not isinstance(row, dict) else row
                else:
                    row = cursor.fetchone()
                    if row:
                        result = dict(row)
            elif fetch_all:
                if self.is_postgres:
                    rows = cursor.fetchall()
                    if hasattr(cursor, 'description') and cursor.description:
                        columns = [col[0] for col in cursor.description]
                        result = [dict(zip(columns, r)) if not isinstance(r, dict) else r for r in rows]
                else:
                    rows = cursor.fetchall()
                    result = [dict(r) for r in rows]
            
            if commit:
                conn.commit()
                
            return result
        except Exception as e:
            if commit:
                conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()

    def sync_phcs_from_supabase(self):
        """
        Connects to Supabase REST API to load PHC records.
        Saves them to the local 'phcs' table.
        Falls back to local mock data if Supabase returns an empty set or a network error occurs.
        """
        import urllib.request
        import json
        import ssl
        
        print("Synchronizing PHC records with Supabase...")
        
        url = Config.SUPABASE_URL.rstrip('/') + "/phcs?select=*"
        headers = {
            "apikey": Config.SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {Config.SUPABASE_ANON_KEY}"
        }
        
        req = urllib.request.Request(url, headers=headers)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # Safe fallback for compatibility in restricted environments
        
        supabase_phcs = []
        try:
            with urllib.request.urlopen(req, context=ctx) as response:
                data = response.read()
                supabase_phcs = json.loads(data.decode('utf-8'))
                print(f"Supabase connection success! Found {len(supabase_phcs)} PHC(s).")
        except Exception as e:
            print(f"Supabase Connection Error: {e}. Falling back to default PHC data.")
            
        # If Supabase returned valid PHC records, populate them
        if supabase_phcs:
            try:
                # Sync Supabase PHC records using UPSERT to prevent cascading deletes
                for idx, phc in enumerate(supabase_phcs, start=1):
                    phc_id = phc.get('id') or phc.get('ID') or idx
                    phc_name = phc.get('PHC_Name') or phc.get('name') or f"PHC {idx}"
                    phc_code = phc.get('PHC_Code') or phc.get('code') or f"PHC-CODE-{idx}"
                    phc_district = phc.get('District') or phc.get('district') or "Unknown District"
                    phc_state = phc.get('Mandal/Village') or phc.get('state') or "Unknown State"
                    
                    existing = self.query("SELECT id FROM phcs WHERE id = %s", (phc_id,), fetch_one=True)
                    if existing:
                        self.execute(
                            "UPDATE phcs SET name = %s, code = %s, district = %s, state = %s WHERE id = %s;",
                            (phc_name, phc_code, phc_district, phc_state, phc_id)
                        )
                    else:
                        self.execute(
                            "INSERT INTO phcs (id, name, code, district, state) VALUES (%s, %s, %s, %s, %s);",
                            (phc_id, phc_name, phc_code, phc_district, phc_state)
                        )
                    print(f"Synced PHC: {phc_name} (Code: {phc_code})")
                print("Supabase PHC synchronization completed successfully.")
                return True
            except Exception as e:
                print(f"Error caching Supabase records: {e}. Reverting database state...")
                
        # If Supabase has no records or sync failed, seed local fallback
        # First check if there are any records in local phcs table
        local_count = self.query("SELECT COUNT(*) as count FROM phcs", fetch_one=True)['count']
        if local_count == 0:
            print("No local PHCs found. Injecting local fallback seed (Kanakapura PHC)...")
            self.execute(
                "INSERT INTO phcs (id, name, code, district, state) VALUES (%s, %s, %s, %s, %s);",
                (1, "Kanakapura PHC (Local Fallback)", "PHC-KAN-001", "Ramanagara", "Karnataka")
            )
        return False

    def execute(self, sql, params=None):
        return self.query(sql, params, commit=True)

    def init_db(self):
        """Initializes all database tables."""
        # Setup specific types based on DB engine
        pk_type = "SERIAL PRIMARY KEY" if self.is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        text_type = "TEXT"
        int_type = "INTEGER"
        real_type = "REAL"
        timestamp_type = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        
        # Tables creation list
        tables = [
            # 1. PHCS
            f"""
            CREATE TABLE IF NOT EXISTS phcs (
                id {pk_type},
                name {text_type} NOT NULL,
                code {text_type} UNIQUE NOT NULL,
                district {text_type} NOT NULL,
                state {text_type} NOT NULL
            );
            """,
            
            # 2. USERS
            f"""
            CREATE TABLE IF NOT EXISTS users (
                id {pk_type},
                username {text_type} UNIQUE NOT NULL,
                password_hash {text_type} NOT NULL,
                full_name {text_type} NOT NULL,
                role {text_type} NOT NULL, -- 'Supervisor', 'Medical Officer', 'Data Entry Operator'
                phc_id {int_type} NOT NULL,
                FOREIGN KEY (phc_id) REFERENCES phcs(id) ON DELETE CASCADE
            );
            """,
            
            # 3. MEDICINES
            f"""
            CREATE TABLE IF NOT EXISTS medicines (
                id {pk_type},
                name {text_type} UNIQUE NOT NULL,
                category {text_type} NOT NULL, -- e.g. Antibiotics, Analgesics, Antidiabetics
                manufacturer {text_type} NOT NULL,
                dosage_form {text_type} NOT NULL -- e.g. Tablet, Syrup, Injection
            );
            """,
            
            # 4. INVENTORY
            f"""
            CREATE TABLE IF NOT EXISTS inventory (
                id {pk_type},
                phc_id {int_type} NOT NULL,
                medicine_id {int_type} NOT NULL,
                batch_number {text_type} NOT NULL,
                current_stock {int_type} NOT NULL DEFAULT 0,
                min_threshold_stock {int_type} NOT NULL DEFAULT 100,
                expiry_date {text_type} NOT NULL, -- YYYY-MM-DD
                daily_avg_consumption {real_type} NOT NULL DEFAULT 0.0,
                last_updated {timestamp_type},
                FOREIGN KEY (phc_id) REFERENCES phcs(id) ON DELETE CASCADE,
                FOREIGN KEY (medicine_id) REFERENCES medicines(id) ON DELETE CASCADE,
                UNIQUE (phc_id, medicine_id, batch_number)
            );
            """,
            
            # 5. INVENTORY_HISTORY
            f"""
            CREATE TABLE IF NOT EXISTS inventory_history (
                id {pk_type},
                inventory_id {int_type} NOT NULL,
                change_type {text_type} NOT NULL, -- ADD, DISPENSE, STOCK_TAKE, DELETE, EDIT
                quantity_changed {int_type} NOT NULL,
                updated_by {int_type} NOT NULL,
                notes {text_type},
                timestamp {timestamp_type},
                FOREIGN KEY (inventory_id) REFERENCES inventory(id) ON DELETE CASCADE,
                FOREIGN KEY (updated_by) REFERENCES users(id)
            );
            """,
            
            # 6. MEDICINE_REQUESTS
            f"""
            CREATE TABLE IF NOT EXISTS medicine_requests (
                id {pk_type},
                phc_id {int_type} NOT NULL,
                medicine_name {text_type} NOT NULL,
                required_quantity {int_type} NOT NULL,
                reason {text_type},
                priority_level {text_type} NOT NULL, -- Low, Medium, High, Critical
                status {text_type} NOT NULL, -- Submitted, Under Review, Approved, Dispatched, Delivered
                requested_by {int_type} NOT NULL,
                district {text_type} NOT NULL,
                created_at {timestamp_type},
                updated_at {timestamp_type},
                FOREIGN KEY (phc_id) REFERENCES phcs(id) ON DELETE CASCADE,
                FOREIGN KEY (requested_by) REFERENCES users(id)
            );
            """,
            
            # 7. SHORTAGE_ALERTS
            f"""
            CREATE TABLE IF NOT EXISTS shortage_alerts (
                id {pk_type},
                phc_id {int_type} NOT NULL,
                inventory_id {int_type} NOT NULL,
                alert_level {text_type} NOT NULL, -- Green, Yellow, Red
                status_message {text_type} NOT NULL,
                days_remaining {real_type} NOT NULL,
                created_at {timestamp_type},
                resolved_at {text_type}, -- Nullable, ISO timestamp or text
                FOREIGN KEY (phc_id) REFERENCES phcs(id) ON DELETE CASCADE,
                FOREIGN KEY (inventory_id) REFERENCES inventory(id) ON DELETE CASCADE
            );
            """,
            
            # 8. DISEASE_TRENDS
            f"""
            CREATE TABLE IF NOT EXISTS disease_trends (
                id {pk_type},
                phc_id {int_type} NOT NULL,
                date {text_type} NOT NULL, -- YYYY-MM-DD
                disease_category {text_type} NOT NULL, -- e.g. Malaria, Dengue, COVID-19, Diarrhea
                cases_reported {int_type} NOT NULL,
                FOREIGN KEY (phc_id) REFERENCES phcs(id) ON DELETE CASCADE
            );
            """,
            
            # 9. PATIENT_STATISTICS
            f"""
            CREATE TABLE IF NOT EXISTS patient_statistics (
                id {pk_type},
                phc_id {int_type} NOT NULL,
                date {text_type} NOT NULL, -- YYYY-MM-DD
                opd_count {int_type} NOT NULL DEFAULT 0,
                male_count {int_type} NOT NULL DEFAULT 0,
                female_count {int_type} NOT NULL DEFAULT 0,
                child_count {int_type} NOT NULL DEFAULT 0,
                FOREIGN KEY (phc_id) REFERENCES phcs(id) ON DELETE CASCADE
            );
            """,
            
            # 10. AI_SUBMISSIONS
            f"""
            CREATE TABLE IF NOT EXISTS ai_submissions (
                id {pk_type},
                phc_id {int_type} NOT NULL,
                submission_timestamp {timestamp_type},
                payload {text_type} NOT NULL, -- JSON string
                status {text_type} NOT NULL, -- Success, Failed
                response_message {text_type},
                FOREIGN KEY (phc_id) REFERENCES phcs(id) ON DELETE CASCADE
            );
            """,
            
            # 11. REPORTS
            f"""
            CREATE TABLE IF NOT EXISTS reports (
                id {pk_type},
                phc_id {int_type} NOT NULL,
                report_type {text_type} NOT NULL, -- Daily, Weekly, Monthly, Shortage, Consumption
                generated_at {timestamp_type},
                period_start {text_type} NOT NULL,
                period_end {text_type} NOT NULL,
                summary_data {text_type} NOT NULL, -- JSON string
                created_by {int_type} NOT NULL,
                FOREIGN KEY (phc_id) REFERENCES phcs(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            """
        ]
        
        # Execute each table creation statement
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            for statement in tables:
                cursor.execute(statement)
            conn.commit()
            print("Database initialized successfully.")
            self.sync_phcs_from_supabase()
        except Exception as e:
            conn.rollback()
            print(f"Error initializing database: {e}")
            raise e
        finally:
            cursor.close()
            conn.close()

    def seed_phc_data(self, phc_id, district, target_counts, medicines, supervisor_id, today):
        """
        Seeds unique inventory, alerts, requests, patient statistics, and disease trends
        for a single PHC based on a target tuple (num_available, num_low, num_critical, num_pending).
        """
        import random
        from datetime import datetime, timedelta
        
        num_available, num_low, num_critical, num_pending = target_counts
        
        # Select a random sample of num_available medicines
        selected_meds = random.sample(medicines, num_available)
        
        critical_meds = selected_meds[0:num_critical]
        low_stock_meds = selected_meds[num_critical:num_critical + num_low]
        safe_meds = selected_meds[num_critical + num_low:]
        
        # 1. Insert Inventory & Shortage Alerts
        for med in selected_meds:
            med_id = med['id']
            med_name = med['name']
            
            # Generate random batch number
            batch = f"B-{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=3))}{random.randint(1000, 9999)}"
            expiry = (today + timedelta(days=random.randint(25, 480))).strftime('%Y-%m-%d')
            
            # Determine stock, threshold, daily_avg to guarantee target alert levels
            if med in critical_meds:
                min_threshold = random.choice([200, 300, 400])
                current_stock = random.randint(5, int(min_threshold * 0.15))
                daily_avg = max(0.1, round(random.uniform(5.0, 15.0), 1))
            elif med in low_stock_meds:
                min_threshold = random.choice([300, 400, 500])
                current_stock = random.randint(int(min_threshold * 0.3), int(min_threshold * 0.7))
                daily_avg = max(0.1, round(current_stock / random.uniform(12.0, 25.0), 1))
            else:
                min_threshold = random.choice([100, 200, 300])
                current_stock = random.randint(min_threshold + 50, min_threshold + 1000)
                daily_avg = max(0.1, round(current_stock / random.uniform(35.0, 80.0), 1))
                
            # Insert into inventory
            self.execute(
                """INSERT INTO inventory 
                   (phc_id, medicine_id, batch_number, current_stock, min_threshold_stock, expiry_date, daily_avg_consumption, last_updated) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s);""",
                (phc_id, med_id, batch, current_stock, min_threshold, expiry, daily_avg, today)
            )
            
            # Retrieve inserted inventory item's id
            inv_item = self.query(
                "SELECT id FROM inventory WHERE phc_id = %s AND medicine_id = %s AND batch_number = %s",
                (phc_id, med_id, batch), fetch_one=True
            )
            inv_id = inv_item['id']
            
            # Log initial stock take
            self.execute(
                """INSERT INTO inventory_history (inventory_id, change_type, quantity_changed, updated_by, notes, timestamp)
                   VALUES (%s, %s, %s, %s, %s, %s);""",
                (inv_id, "STOCK_TAKE", current_stock, supervisor_id, "Initial seed stock take.", today)
            )
            
            # Insert alert
            if daily_avg > 0:
                days_remaining = current_stock / daily_avg
            else:
                days_remaining = 999.0
                
            alert_level = None
            status_message = ""
            
            if med in critical_meds:
                alert_level = "Red"
                status_message = f"Critical Shortage: {med_name} has only {days_remaining:.1f} days of stock remaining ({current_stock} units)."
            elif med in low_stock_meds:
                alert_level = "Yellow"
                status_message = f"Low Stock Warning: {med_name} has {days_remaining:.1f} days of stock remaining ({current_stock} units)."
                
            if alert_level:
                self.execute(
                    """INSERT INTO shortage_alerts (phc_id, inventory_id, alert_level, status_message, days_remaining, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s);""",
                    (phc_id, inv_id, alert_level, status_message, days_remaining, today)
                )
                
        # 2. Insert Pending Requests
        request_statuses = ["Submitted", "Under Review", "Approved", "Dispatched"]
        priorities = ["Low", "Medium", "High", "Critical"]
        reasons = ["Regular buffer stock refill", "Outpatient influx", "Local infection surge", "Seasonal preventive safety stock"]
        
        for _ in range(num_pending):
            req_med = random.choice(selected_meds)
            req_med_name = req_med['name']
            qty = random.randint(2, 12) * 100
            priority = random.choice(priorities)
            status = random.choice(request_statuses)
            reason = random.choice(reasons)
            
            self.execute(
                """INSERT INTO medicine_requests 
                   (phc_id, medicine_name, required_quantity, reason, priority_level, status, requested_by, district, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);""",
                (phc_id, req_med_name, qty, reason, priority, status, supervisor_id, district, today, today)
            )
            
        # 3. Patient Statistics (Past 30 days) with unique volume multipliers
        phc_volume = random.uniform(0.5, 2.8)
        for i in range(30):
            log_date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            day_noise = random.uniform(0.75, 1.25)
            opd = max(10, int(random.randint(45, 95) * phc_volume * day_noise))
            male = max(2, int(opd * random.uniform(0.35, 0.45)))
            female = max(2, int(opd * random.uniform(0.35, 0.45)))
            child = max(0, opd - male - female)
            
            self.execute(
                """INSERT INTO patient_statistics (phc_id, date, opd_count, male_count, female_count, child_count)
                   VALUES (%s, %s, %s, %s, %s, %s);""",
                (phc_id, log_date, opd, male, female, child)
            )
            
        # 4. Disease Trends (Past 6 months)
        for month_offset in range(6):
            date_str = (today - timedelta(days=month_offset * 30)).replace(day=1).strftime('%Y-%m-%d')
            
            malaria = max(0, int(random.randint(2, 28) * phc_volume * random.uniform(0.7, 1.3)))
            diarrhea = max(0, int(random.randint(8, 45) * phc_volume * random.uniform(0.7, 1.3)))
            respiratory = max(0, int(random.randint(15, 68) * phc_volume * random.uniform(0.7, 1.3)))
            chronic = max(0, int(random.randint(20, 50) * phc_volume * random.uniform(0.7, 1.3)))
            
            self.execute("INSERT INTO disease_trends (phc_id, date, disease_category, cases_reported) VALUES (%s, %s, %s, %s);",
                       (phc_id, date_str, "Vector-borne (Malaria/Dengue)", malaria))
            self.execute("INSERT INTO disease_trends (phc_id, date, disease_category, cases_reported) VALUES (%s, %s, %s, %s);",
                       (phc_id, date_str, "Water-borne (Diarrhea/Cholera)", diarrhea))
            self.execute("INSERT INTO disease_trends (phc_id, date, disease_category, cases_reported) VALUES (%s, %s, %s, %s);",
                       (phc_id, date_str, "Respiratory Infections", respiratory))
            self.execute("INSERT INTO disease_trends (phc_id, date, disease_category, cases_reported) VALUES (%s, %s, %s, %s);",
                       (phc_id, date_str, "Chronic Diseases", chronic))

db = Database()

if __name__ == '__main__':
    db.init_db()
