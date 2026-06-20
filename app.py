import json
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import check_password_hash
from database import db
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# Helper decorator for checking login status
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Helper decorator for role-based access control
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash("Unauthorized access: Your role does not allow this action.", "danger")
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ----------------- Helper Functions -----------------

def run_shortage_detection(phc_id, inventory_id):
    """
    Shortage Detection Engine:
    Calculates Days Remaining = Current Stock / Daily Average Consumption.
    Generates Alerts: Red (Critical), Yellow (Low Stock), Green (Safe).
    """
    # Fetch inventory details
    inv = db.query(
        """SELECT i.current_stock, i.min_threshold_stock, i.daily_avg_consumption, m.name
           FROM inventory i
           JOIN medicines m ON i.medicine_id = m.id
           WHERE i.id = %s""",
        (inventory_id,), fetch_one=True
    )
    if not inv:
        return
        
    current = inv['current_stock']
    threshold = inv['min_threshold_stock']
    daily_avg = inv['daily_avg_consumption']
    med_name = inv['name']
    
    # Calculate days remaining
    if daily_avg > 0:
        days_remaining = current / daily_avg
    else:
        days_remaining = 999.0  # safe value representing infinite supply
        
    alert_level = "Green"
    status_message = f"Stock level for {med_name} is stable."
    
    # Critical Shortage Conditions
    if days_remaining < 10 or current < (threshold * 0.2):
        alert_level = "Red"
        status_message = f"Critical Shortage: {med_name} has only {days_remaining:.1f} days of stock remaining ({current} units, threshold is {threshold})."
    elif days_remaining < 30 or current < threshold:
        alert_level = "Yellow"
        status_message = f"Low Stock Warning: {med_name} has {days_remaining:.1f} days of stock remaining ({current} units, threshold is {threshold})."

    # Update or insert shortage alert in DB
    existing_alert = db.query(
        "SELECT id FROM shortage_alerts WHERE inventory_id = %s AND resolved_at IS NULL",
        (inventory_id,), fetch_one=True
    )
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if alert_level in ["Red", "Yellow"]:
        if existing_alert:
            # Update existing unresolved alert
            db.execute(
                """UPDATE shortage_alerts 
                   SET alert_level = %s, status_message = %s, days_remaining = %s, created_at = %s
                   WHERE id = %s""",
                (alert_level, status_message, days_remaining, now_str, existing_alert['id'])
            )
        else:
            # Insert new alert
            db.execute(
                """INSERT INTO shortage_alerts (phc_id, inventory_id, alert_level, status_message, days_remaining, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (phc_id, inventory_id, alert_level, status_message, days_remaining, now_str)
            )
    else:
        # If Green, resolve any existing alert
        if existing_alert:
            db.execute(
                "UPDATE shortage_alerts SET resolved_at = %s WHERE id = %s",
                (now_str, existing_alert['id'])
            )

# ----------------- Page Routes -----------------

@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = db.query(
            "SELECT u.*, p.name as phc_name, p.district as phc_district, p.code as phc_code FROM users u JOIN phcs p ON u.phc_id = p.id WHERE u.username = %s",
            (username,), fetch_one=True
        )
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            session['phc_id'] = user['phc_id']
            session['phc_name'] = user['phc_name']
            session['phc_district'] = user['phc_district']
            session['phc_code'] = user['phc_code']
            
            flash(f"Welcome back, {user['full_name']} ({user['role']})!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid username or password.", "danger")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been successfully logged out.", "info")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    phc_id = session['phc_id']
    
    # 1. Total Medicines Available (distinct medicines in stock > 0)
    total_meds = db.query(
        "SELECT COUNT(*) as count FROM inventory WHERE phc_id = %s AND current_stock > 0",
        (phc_id,), fetch_one=True
    )['count']
    
    # 2. Low Stock Medicines (Yellow alerts)
    low_stock = db.query(
        """SELECT COUNT(*) as count FROM shortage_alerts 
           WHERE phc_id = %s AND alert_level = 'Yellow' AND resolved_at IS NULL""",
        (phc_id,), fetch_one=True
    )['count']
    
    # 3. Critical Shortages (Red alerts)
    critical_shortages = db.query(
        """SELECT COUNT(*) as count FROM shortage_alerts 
           WHERE phc_id = %s AND alert_level = 'Red' AND resolved_at IS NULL""",
        (phc_id,), fetch_one=True
    )['count']
    
    # 4. Pending Requests
    pending_requests = db.query(
        "SELECT COUNT(*) as count FROM medicine_requests WHERE phc_id = %s AND status IN ('Submitted', 'Under Review', 'Approved')",
        (phc_id,), fetch_one=True
    )['count']
    
    # 5. Recent Alerts
    active_alerts = db.query(
        """SELECT sa.*, m.name as medicine_name 
           FROM shortage_alerts sa
           JOIN inventory i ON sa.inventory_id = i.id
           JOIN medicines m ON i.medicine_id = m.id
           WHERE sa.phc_id = %s AND sa.resolved_at IS NULL
           ORDER BY sa.alert_level DESC, sa.created_at DESC LIMIT 5""",
        (phc_id,), fetch_all=True
    )
    
    # 6. Recent Stock Updates
    recent_updates = db.query(
        """SELECT ih.*, m.name as medicine_name, u.full_name as user_name
           FROM inventory_history ih
           JOIN inventory i ON ih.inventory_id = i.id
           JOIN medicines m ON i.medicine_id = m.id
           JOIN users u ON ih.updated_by = u.id
           WHERE i.phc_id = %s
           ORDER BY ih.timestamp DESC LIMIT 5""",
        (phc_id,), fetch_all=True
    )
    
    # 7. Total PHCs in network (loaded from Supabase)
    total_phcs = db.query("SELECT COUNT(*) as count FROM phcs", fetch_one=True)['count']
    
    return render_template(
        'dashboard.html',
        total_meds=total_meds,
        low_stock=low_stock,
        critical_shortages=critical_shortages,
        pending_requests=pending_requests,
        active_alerts=active_alerts,
        recent_updates=recent_updates,
        total_phcs=total_phcs
    )

@app.route('/directory')
@login_required
def phc_directory():
    phcs_list = db.query("SELECT * FROM phcs ORDER BY name", fetch_all=True)
    return render_template('directory.html', phcs=phcs_list)

@app.route('/inventory')
@login_required
def inventory():
    phc_id = session['phc_id']
    
    # Fetch base medicines for add dropdown
    base_medicines = db.query("SELECT * FROM medicines ORDER BY name", fetch_all=True)
    
    # Fetch current inventory with shortage calculations
    inventory_list = db.query(
        """SELECT i.*, m.name, m.category, m.manufacturer, m.dosage_form,
           (CASE WHEN i.daily_avg_consumption > 0 THEN i.current_stock / i.daily_avg_consumption ELSE 999.0 END) as days_remaining
           FROM inventory i
           JOIN medicines m ON i.medicine_id = m.id
           WHERE i.phc_id = %s
           ORDER BY m.name""",
        (phc_id,), fetch_all=True
    )
    
    # Append colors based on dynamic calculation
    for item in inventory_list:
        days = item['days_remaining']
        current = item['current_stock']
        threshold = item['min_threshold_stock']
        if days < 10 or current < (threshold * 0.2):
            item['status_color'] = 'danger'  # Red
            item['status_text'] = 'Critical Shortage'
        elif days < 30 or current < threshold:
            item['status_color'] = 'warning'  # Yellow
            item['status_text'] = 'Low Stock'
        else:
            item['status_color'] = 'success'  # Green
            item['status_text'] = 'Safe'
            
    return render_template(
        'inventory.html',
        inventory=inventory_list,
        base_medicines=base_medicines
    )

@app.route('/patient-demand', methods=['GET', 'POST'])
@login_required
def patient_demand():
    phc_id = session['phc_id']
    
    if request.method == 'POST':
        # Check if daily OPD or disease trend
        form_type = request.form.get('form_type')
        date_str = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        if form_type == 'opd':
            opd = int(request.form.get('opd_count', 0))
            male = int(request.form.get('male_count', 0))
            female = int(request.form.get('female_count', 0))
            child = int(request.form.get('child_count', 0))
            
            # Check if record for this day exists
            existing = db.query(
                "SELECT id FROM patient_statistics WHERE phc_id = %s AND date = %s",
                (phc_id, date_str), fetch_one=True
            )
            if existing:
                db.execute(
                    """UPDATE patient_statistics 
                       SET opd_count = %s, male_count = %s, female_count = %s, child_count = %s
                       WHERE id = %s""",
                    (opd, male, female, child, existing['id'])
                )
            else:
                db.execute(
                    """INSERT INTO patient_statistics (phc_id, date, opd_count, male_count, female_count, child_count)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (phc_id, date_str, opd, male, female, child)
                )
            flash("Daily OPD count successfully logged.", "success")
            
        elif form_type == 'disease':
            category = request.form.get('disease_category')
            cases = int(request.form.get('cases_reported', 0))
            
            # Check if record for this day and category exists
            existing = db.query(
                "SELECT id FROM disease_trends WHERE phc_id = %s AND date = %s AND disease_category = %s",
                (phc_id, date_str, category), fetch_one=True
            )
            if existing:
                db.execute(
                    "UPDATE disease_trends SET cases_reported = %s WHERE id = %s",
                    (cases, existing['id'])
                )
            else:
                db.execute(
                    "INSERT INTO disease_trends (phc_id, date, disease_category, cases_reported) VALUES (%s, %s, %s, %s)",
                    (phc_id, date_str, category, cases)
                )
            flash("Disease trend log successfully saved.", "success")
            
        return redirect(url_for('patient_demand'))
        
    # Get last 10 logs for table
    opd_logs = db.query(
        "SELECT * FROM patient_statistics WHERE phc_id = %s ORDER BY date DESC LIMIT 10",
        (phc_id,), fetch_all=True
    )
    
    disease_logs = db.query(
        "SELECT * FROM disease_trends WHERE phc_id = %s ORDER BY date DESC, disease_category LIMIT 15",
        (phc_id,), fetch_all=True
    )
    
    return render_template(
        'patient_demand.html',
        opd_logs=opd_logs,
        disease_logs=disease_logs
    )

@app.route('/requests', methods=['GET', 'POST'])
@login_required
def requests_module():
    phc_id = session['phc_id']
    
    if request.method == 'POST':
        # Submit new request
        med_name = request.form.get('medicine_name')
        qty = int(request.form.get('required_quantity', 0))
        reason = request.form.get('reason')
        priority = request.form.get('priority_level')
        district = session['phc_district']
        user_id = session['user_id']
        now = datetime.now()
        
        db.execute(
            """INSERT INTO medicine_requests 
               (phc_id, medicine_name, required_quantity, reason, priority_level, status, requested_by, district, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (phc_id, med_name, qty, reason, priority, "Submitted", user_id, district, now, now)
        )
        flash("Medicine replenishment request submitted to warehouse.", "success")
        return redirect(url_for('requests_module'))
        
    # Fetch request log
    req_list = db.query(
        """SELECT mr.*, u.full_name as requested_by_name 
           FROM medicine_requests mr
           JOIN users u ON mr.requested_by = u.id
           WHERE mr.phc_id = %s
           ORDER BY mr.created_at DESC""",
        (phc_id,), fetch_all=True
    )
    
    # Medicines list for dropdown
    medicines = db.query("SELECT name FROM medicines ORDER BY name", fetch_all=True)
    
    return render_template(
        'requests.html',
        requests=req_list,
        medicines=medicines
    )

@app.route('/ai-sync')
@login_required
def ai_sync():
    phc_id = session['phc_id']
    
    # Fetch past submissions
    submissions = db.query(
        "SELECT * FROM ai_submissions WHERE phc_id = %s ORDER BY submission_timestamp DESC LIMIT 15",
        (phc_id,), fetch_all=True
    )
    
    # Convert JSON text to objects for frontend presentation
    for sub in submissions:
        try:
            sub['parsed_payload'] = json.loads(sub['payload'])
        except Exception:
            sub['parsed_payload'] = {}
            
    return render_template('ai_sync.html', submissions=submissions)

@app.route('/reports')
@login_required
def reports():
    phc_id = session['phc_id']
    
    # Fetch reports list
    reports_list = db.query(
        """SELECT r.*, u.full_name as author 
           FROM reports r 
           JOIN users u ON r.created_by = u.id 
           WHERE r.phc_id = %s 
           ORDER BY r.generated_at DESC""",
        (phc_id,), fetch_all=True
    )
    
    for rep in reports_list:
        try:
            rep['data'] = json.loads(rep['summary_data'])
        except Exception:
            rep['data'] = {}
            
    return render_template('reports.html', reports=reports_list)

# ----------------- Simulation Switch (For demo testing) -----------------

@app.route('/switch-role/<role>')
@login_required
def switch_role(role):
    """Convenience route to toggle credentials for testing portal roles."""
    valid_roles = {
        'Supervisor': ('supervisor', 'Dr. Anil Kumar'),
        'Medical Officer': ('officer', 'Dr. Sneha Patil'),
        'Data Entry Operator': ('operator', 'Rajesh Gowda')
    }
    
    if role in valid_roles:
        username, full_name = valid_roles[role]
        session['role'] = role
        session['username'] = username
        session['full_name'] = full_name
        flash(f"Switched simulation session to: {role} ({full_name})", "info")
    return redirect(request.referrer or url_for('dashboard'))

# ----------------- REST API Endpoints -----------------

@app.route('/api/inventory', methods=['GET'])
@login_required
def api_inventory():
    phc_id = session['phc_id']
    inv = db.query(
        """SELECT i.*, m.name, m.category, m.dosage_form, m.manufacturer 
           FROM inventory i JOIN medicines m ON i.medicine_id = m.id 
           WHERE i.phc_id = %s""",
        (phc_id,), fetch_all=True
    )
    return jsonify(inv)

@app.route('/api/inventory/add', methods=['POST'])
@login_required
@role_required('Supervisor', 'Data Entry Operator')
def api_inventory_add():
    phc_id = session['phc_id']
    user_id = session['user_id']
    
    medicine_id = request.form.get('medicine_id')
    batch = request.form.get('batch_number')
    stock = int(request.form.get('current_stock', 0))
    threshold = int(request.form.get('min_threshold_stock', 100))
    expiry = request.form.get('expiry_date')
    daily_avg = float(request.form.get('daily_avg_consumption', 0.0))
    
    now = datetime.now()
    
    try:
        # Insert or update
        db.execute(
            """INSERT INTO inventory 
               (phc_id, medicine_id, batch_number, current_stock, min_threshold_stock, expiry_date, daily_avg_consumption, last_updated)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (phc_id, medicine_id, batch, stock, threshold, expiry, daily_avg, now)
        )
        
        # Get the ID of the new item
        inserted_id = db.query(
            "SELECT id FROM inventory WHERE phc_id = %s AND medicine_id = %s AND batch_number = %s",
            (phc_id, medicine_id, batch), fetch_one=True
        )['id']
        
        # Log to inventory history
        db.execute(
            """INSERT INTO inventory_history (inventory_id, change_type, quantity_changed, updated_by, notes, timestamp)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (inserted_id, "ADD", stock, user_id, "Initial batch stocking.", now)
        )
        
        # Trigger shortage detection alert check
        run_shortage_detection(phc_id, inserted_id)
        
        flash("Medicine batch added successfully.", "success")
    except Exception as e:
        flash(f"Error adding medicine: {e}", "danger")
        
    return redirect(url_for('inventory'))

@app.route('/api/inventory/edit/<int:item_id>', methods=['POST'])
@login_required
@role_required('Supervisor', 'Data Entry Operator')
def api_inventory_edit(item_id):
    phc_id = session['phc_id']
    
    batch = request.form.get('batch_number')
    threshold = int(request.form.get('min_threshold_stock', 100))
    expiry = request.form.get('expiry_date')
    daily_avg = float(request.form.get('daily_avg_consumption', 0.0))
    
    now = datetime.now()
    
    try:
        db.execute(
            """UPDATE inventory 
               SET batch_number = %s, min_threshold_stock = %s, expiry_date = %s, daily_avg_consumption = %s, last_updated = %s
               WHERE id = %s AND phc_id = %s""",
            (batch, threshold, expiry, daily_avg, now, item_id, phc_id)
        )
        
        # Re-run shortage checking
        run_shortage_detection(phc_id, item_id)
        
        flash("Medicine details updated successfully.", "success")
    except Exception as e:
        flash(f"Error updating medicine details: {e}", "danger")
        
    return redirect(url_for('inventory'))

@app.route('/api/inventory/update_stock/<int:item_id>', methods=['POST'])
@login_required
def api_inventory_update_stock(item_id):
    phc_id = session['phc_id']
    user_id = session['user_id']
    
    change_type = request.form.get('change_type') # ADD or DISPENSE or STOCK_TAKE
    qty = int(request.form.get('quantity', 0))
    notes = request.form.get('notes', '')
    
    now = datetime.now()
    
    item = db.query("SELECT current_stock FROM inventory WHERE id = %s AND phc_id = %s", (item_id, phc_id), fetch_one=True)
    if not item:
        flash("Medicine stock batch not found.", "danger")
        return redirect(url_for('inventory'))
        
    old_stock = item['current_stock']
    
    if change_type == 'ADD':
        new_stock = old_stock + qty
        qty_changed = qty
    elif change_type == 'DISPENSE':
        if old_stock < qty:
            flash("Insufficient stock for dispensing.", "warning")
            return redirect(url_for('inventory'))
        new_stock = old_stock - qty
        qty_changed = -qty
    else:  # STOCK_TAKE (manual override)
        new_stock = qty
        qty_changed = new_stock - old_stock
        
    try:
        db.execute(
            "UPDATE inventory SET current_stock = %s, last_updated = %s WHERE id = %s",
            (new_stock, now, item_id)
        )
        
        db.execute(
            """INSERT INTO inventory_history (inventory_id, change_type, quantity_changed, updated_by, notes, timestamp)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (item_id, change_type, qty_changed, user_id, notes, now)
        )
        
        # Trigger shortage engine
        run_shortage_detection(phc_id, item_id)
        
        flash("Inventory stock level updated successfully.", "success")
    except Exception as e:
        flash(f"Error updating inventory: {e}", "danger")
        
    return redirect(url_for('inventory'))

@app.route('/api/inventory/delete/<int:item_id>', methods=['POST'])
@login_required
@role_required('Supervisor')
def api_inventory_delete(item_id):
    phc_id = session['phc_id']
    try:
        db.execute("DELETE FROM inventory WHERE id = %s AND phc_id = %s", (item_id, phc_id))
        flash("Medicine batch removed from inventory.", "info")
    except Exception as e:
        flash(f"Error deleting batch: {e}", "danger")
    return redirect(url_for('inventory'))

@app.route('/api/inventory/history/<int:item_id>', methods=['GET'])
@login_required
def api_inventory_history(item_id):
    phc_id = session['phc_id']
    history = db.query(
        """SELECT ih.*, u.full_name as user_name 
           FROM inventory_history ih 
           JOIN users u ON ih.updated_by = u.id 
           JOIN inventory i ON ih.inventory_id = i.id
           WHERE ih.inventory_id = %s AND i.phc_id = %s
           ORDER BY ih.timestamp DESC""",
        (item_id, phc_id), fetch_all=True
    )
    return jsonify(history)

# ----------------- Requests & Workflow Simulator -----------------

@app.route('/api/requests/update_status/<int:req_id>', methods=['POST'])
@login_required
@role_required('Supervisor', 'Medical Officer')
def api_update_request_status(req_id):
    """
    Simulates warehouse workflow updates locally.
    In production, this would be updated via webhooks from the central RHIM Warehouse/Logistics platform.
    """
    phc_id = session['phc_id']
    new_status = request.form.get('status') # Submitted, Under Review, Approved, Dispatched, Delivered
    now = datetime.now()
    
    # Fetch request
    req = db.query("SELECT * FROM medicine_requests WHERE id = %s AND phc_id = %s", (req_id, phc_id), fetch_one=True)
    if not req:
        return jsonify({"success": False, "error": "Request not found."}), 404
        
    try:
        db.execute(
            "UPDATE medicine_requests SET status = %s, updated_at = %s WHERE id = %s",
            (new_status, now, req_id)
        )
        
        # If status changes to 'Delivered', we automatically add these items to inventory!
        if new_status == 'Delivered':
            # Try to match existing medicine in inventory
            med_name = req['medicine_name']
            qty = req['required_quantity']
            
            med = db.query("SELECT id FROM medicines WHERE name = %s", (med_name,), fetch_one=True)
            if med:
                med_id = med['id']
                # Check if we already have this medicine in inventory
                existing_inv = db.query(
                    "SELECT id, current_stock FROM inventory WHERE phc_id = %s AND medicine_id = %s LIMIT 1",
                    (phc_id, med_id), fetch_one=True
                )
                
                if existing_inv:
                    # Update stock of existing first batch found
                    new_stock = existing_inv['current_stock'] + qty
                    db.execute(
                        "UPDATE inventory SET current_stock = %s, last_updated = %s WHERE id = %s",
                        (new_stock, now, existing_inv['id'])
                    )
                    db.execute(
                        """INSERT INTO inventory_history (inventory_id, change_type, quantity_changed, updated_by, notes, timestamp)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (existing_inv['id'], "ADD", qty, session['user_id'], f"Stock added from delivered request #{req_id}.", now)
                    )
                    run_shortage_detection(phc_id, existing_inv['id'])
                else:
                    # Create a new batch entry
                    batch = f"DEL-{req_id}"
                    expiry = (now + timedelta(days=180)).strftime('%Y-%m-%d')
                    db.execute(
                        """INSERT INTO inventory 
                           (phc_id, medicine_id, batch_number, current_stock, min_threshold_stock, expiry_date, daily_avg_consumption, last_updated)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (phc_id, med_id, batch, qty, 100, expiry, 10.0, now)
                    )
                    inserted = db.query(
                        "SELECT id FROM inventory WHERE phc_id = %s AND medicine_id = %s AND batch_number = %s",
                        (phc_id, med_id, batch), fetch_one=True
                    )
                    db.execute(
                        """INSERT INTO inventory_history (inventory_id, change_type, quantity_changed, updated_by, notes, timestamp)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (inserted['id'], "ADD", qty, session['user_id'], f"New batch created from delivered request #{req_id}.", now)
                    )
                    run_shortage_detection(phc_id, inserted['id'])
            
            flash(f"Request #{req_id} marked as Delivered. Stocks automatically updated.", "success")
        else:
            flash(f"Request #{req_id} status updated to '{new_status}'.", "info")
            
    except Exception as e:
        flash(f"Error updating request: {e}", "danger")
        
    return redirect(url_for('requests_module'))

# ----------------- Send to RHIM AI Integration -----------------

@app.route('/api/ai/sync', methods=['POST'])
@login_required
def api_ai_sync():
    """
    Submits PHC data payload to RHIM AI Platform via Supabase transport layer.
    1. Gathers current PHC inventory data.
    2. Gathers OPD statistics.
    3. Gathers disease reports.
    4. Saves sync records to Supabase.
    5. Marks the PHC as synced locally.
    6. Returns success confirmation.
    """
    phc_id = session['phc_id']
    phc_code = session.get('phc_code', 'UNKNOWN')
    phc_name = session.get('phc_name', 'Unknown PHC')
    phc_district = session.get('phc_district', 'Unknown')
    
    # 1. Gather current inventory data
    inventory_data = db.query(
        """SELECT i.batch_number, i.current_stock, i.min_threshold_stock, i.expiry_date, i.daily_avg_consumption,
           m.name, m.category, m.dosage_form
           FROM inventory i JOIN medicines m ON i.medicine_id = m.id
           WHERE i.phc_id = %s""",
        (phc_id,), fetch_all=True
    )
    
    # 2. Gather OPD patient statistics (past 30 days)
    patient_data = db.query(
        "SELECT date, opd_count, male_count, female_count, child_count FROM patient_statistics WHERE phc_id = %s ORDER BY date DESC LIMIT 30",
        (phc_id,), fetch_all=True
    )
    
    # 3. Gather disease trend reports (past 6 months)
    disease_data = db.query(
        "SELECT date, disease_category, cases_reported FROM disease_trends WHERE phc_id = %s ORDER BY date DESC",
        (phc_id,), fetch_all=True
    )
    
    # 4. Gather active shortage alerts
    alert_data = db.query(
        "SELECT alert_level, status_message, days_remaining, created_at FROM shortage_alerts WHERE phc_id = %s AND resolved_at IS NULL",
        (phc_id,), fetch_all=True
    )
    
    # Construct the full sync payload
    now = datetime.now()
    payload_dict = {
        "phc_code": phc_code,
        "phc_name": phc_name,
        "district": phc_district,
        "sync_timestamp": now.strftime('%Y-%m-%d %H:%M:%S'),
        "data": {
            "inventory": inventory_data,
            "patient_statistics": patient_data,
            "disease_trends": disease_data,
            "shortage_alerts": alert_data
        }
    }
    payload_json = json.dumps(payload_dict)
    
    tx_hash = "tx_rhim_ai_" + now.strftime('%y%m%d%H%M%S') + "_" + str(random_hex(6))
    
    try:
        # 4. Push sync data to Supabase as the transport layer
        sync_success, sync_details = db.push_sync_to_supabase(
            phc_code=phc_code,
            phc_name=phc_name,
            district=phc_district,
            inventory_data=inventory_data,
            disease_data=disease_data,
            patient_data=patient_data,
            alert_data=alert_data
        )
        
        summary = sync_details.get('summary', {})
        total_records = summary.get('total_records_synced', 0)
        sync_status = summary.get('status', 'unknown')
        
        # Build response message
        if sync_success:
            status_text = "Success"
            response_msg = f"Supabase Gateway Synced. {total_records} records transmitted. Sync ID: {tx_hash}"
        else:
            status_text = "Partial"
            sync_errors = summary.get('errors', [])
            response_msg = f"Supabase Gateway Partial Sync. {total_records} records transmitted. Errors: {'; '.join(sync_errors)}. Sync ID: {tx_hash}"
        
        # 5. Save sync record locally (mark PHC as synced)
        db.execute(
            """INSERT INTO ai_submissions (phc_id, submission_timestamp, payload, status, response_message)
               VALUES (%s, %s, %s, %s, %s)""",
            (phc_id, now, payload_json, status_text, response_msg)
        )
        
        # 6. Return success confirmation
        return jsonify({
            "success": True,
            "message": f"Data synchronized with MediReach AI via Supabase. {total_records} records pushed.",
            "transaction_hash": tx_hash,
            "timestamp": now.strftime('%H:%M:%S'),
            "supabase_sync": {
                "inventory": sync_details.get('inventory'),
                "disease_outbreaks": sync_details.get('disease_outbreaks'),
                "status": sync_status,
                "total_records": total_records
            }
        })
    except Exception as e:
        # Log the failed sync attempt locally
        try:
            db.execute(
                """INSERT INTO ai_submissions (phc_id, submission_timestamp, payload, status, response_message)
                   VALUES (%s, %s, %s, %s, %s)""",
                (phc_id, now, payload_json, "Failed", f"Sync Error: {str(e)}")
            )
        except Exception:
            pass
            
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

def random_hex(length=6):
    import random
    chars = '0123456789abcdef'
    return ''.join(random.choice(chars) for _ in range(length))

# ----------------- Reports Generation Engine -----------------

@app.route('/api/reports/generate', methods=['POST'])
@login_required
def api_reports_generate():
    phc_id = session['phc_id']
    user_id = session['user_id']
    
    report_type = request.form.get('report_type')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    
    now = datetime.now()
    
    # Gather dynamic summary statistics based on report type
    summary = {}
    
    try:
        if report_type == 'Shortage Report':
            # Fetch active alerts
            alerts = db.query(
                """SELECT sa.*, m.name 
                   FROM shortage_alerts sa
                   JOIN inventory i ON sa.inventory_id = i.id
                   JOIN medicines m ON i.medicine_id = m.id
                   WHERE sa.phc_id = %s AND sa.resolved_at IS NULL""",
                (phc_id,), fetch_all=True
            )
            summary = {
                "total_alerts": len(alerts),
                "red_alerts": sum(1 for a in alerts if a['alert_level'] == 'Red'),
                "yellow_alerts": sum(1 for a in alerts if a['alert_level'] == 'Yellow'),
                "items": [{"medicine": a['name'], "days": a['days_remaining'], "level": a['alert_level']} for a in alerts]
            }
            
        elif report_type == 'Medicine Consumption Report':
            # Fetch inventory list and daily consumptions
            consumptions = db.query(
                """SELECT m.name, i.daily_avg_consumption, i.current_stock
                   FROM inventory i JOIN medicines m ON i.medicine_id = m.id
                   WHERE i.phc_id = %s ORDER BY i.daily_avg_consumption DESC""",
                (phc_id,), fetch_all=True
            )
            summary = {
                "monitored_medicines": len(consumptions),
                "high_use_items": [c['name'] for c in consumptions if c['daily_avg_consumption'] > 20],
                "items": [{"medicine": c['name'], "daily_avg": c['daily_avg_consumption'], "stock": c['current_stock']} for c in consumptions]
            }
            
        else: # Default/Daily/Weekly/Monthly Reports
            # Fetch OPD total count, male, female, children
            opd = db.query(
                """SELECT SUM(opd_count) as total, SUM(male_count) as male, SUM(female_count) as female, SUM(child_count) as child
                   FROM patient_statistics
                   WHERE phc_id = %s AND date BETWEEN %s AND %s""",
                (phc_id, start_date, end_date), fetch_one=True
            )
            
            # Fetch disease cases sum
            diseases = db.query(
                """SELECT disease_category, SUM(cases_reported) as cases
                   FROM disease_trends
                   WHERE phc_id = %s AND date BETWEEN %s AND %s
                   GROUP BY disease_category""",
                (phc_id, start_date, end_date), fetch_all=True
            )
            
            summary = {
                "opd_total": opd['total'] or 0,
                "male_total": opd['male'] or 0,
                "female_total": opd['female'] or 0,
                "child_total": opd['child'] or 0,
                "disease_breakdown": [{"category": d['disease_category'], "cases": d['cases']} for d in diseases]
            }
            
        summary_json = json.dumps(summary)
        
        db.execute(
            """INSERT INTO reports (phc_id, report_type, generated_at, period_start, period_end, summary_data, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (phc_id, report_type, now, start_date, end_date, summary_json, user_id)
        )
        
        flash(f"{report_type} successfully generated and archived.", "success")
    except Exception as e:
        flash(f"Error generating report: {e}", "danger")
        
    return redirect(url_for('reports'))

# ----------------- Custom Template Filters -----------------

@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value)
    except Exception:
        return {}

# ----------------- Context Processor & Switcher Routes -----------------

@app.context_processor
def inject_phcs():
    phcs_list = db.query("SELECT * FROM phcs ORDER BY name", fetch_all=True)
    return dict(all_phcs=phcs_list)

@app.route('/switch-phc/<int:new_phc_id>')
@login_required
def switch_phc(new_phc_id):
    phc = db.query("SELECT * FROM phcs WHERE id = %s", (new_phc_id,), fetch_one=True)
    if not phc:
        flash("Target Health Centre not found.", "danger")
        return redirect(request.referrer or url_for('dashboard'))
        
    # Update Session details
    session['phc_id'] = phc['id']
    session['phc_name'] = phc['name']
    session['phc_district'] = phc['district']
    session['phc_code'] = phc['code']
    
    # Dynamic Seeding: If the newly selected PHC has no inventory, copy the data 
    # from the first PHC to make it fully interactive and operational instantly.
    try:
        inv_count = db.query("SELECT COUNT(*) as count FROM inventory WHERE phc_id = %s", (new_phc_id,), fetch_one=True)['count']
        if inv_count == 0:
            now = datetime.now()
            import random
            
            # Find a unique combination of metrics not currently used in the database
            used_tuples = set()
            phc_stats = db.query(
                """
                SELECT 
                    p.id,
                    (SELECT COUNT(*) FROM inventory WHERE phc_id = p.id AND current_stock > 0) as available_meds,
                    (SELECT COUNT(*) FROM shortage_alerts WHERE phc_id = p.id AND alert_level = 'Yellow' AND resolved_at IS NULL) as low_stock,
                    (SELECT COUNT(*) FROM shortage_alerts WHERE phc_id = p.id AND alert_level = 'Red' AND resolved_at IS NULL) as critical,
                    (SELECT COUNT(*) FROM medicine_requests WHERE phc_id = p.id AND status IN ('Submitted', 'Under Review', 'Approved', 'Dispatched')) as pending
                FROM phcs p
                """,
                fetch_all=True
            )
            if phc_stats:
                for s in phc_stats:
                    used_tuples.add((s['available_meds'], s['low_stock'], s['critical'], s['pending']))
            
            # Generate valid unique combinations
            combinations = []
            for a in range(12, 21):
                for l in range(1, 5):
                    for c in range(1, 5):
                        for p in range(0, 4):
                            tup = (a, l, c, p)
                            if tup not in used_tuples:
                                combinations.append(tup)
                                
            if combinations:
                target_counts = random.choice(combinations)
            else:
                target_counts = (random.randint(12, 20), random.randint(1, 4), random.randint(1, 4), random.randint(0, 3))
                
            medicines_db = db.query("SELECT * FROM medicines", fetch_all=True)
            supervisor_id = session.get('user_id') or 1
            
            db.seed_phc_data(
                phc_id=new_phc_id,
                district=phc['district'],
                target_counts=target_counts,
                medicines=medicines_db,
                supervisor_id=supervisor_id,
                today=now
            )
            print(f"Dynamically seeded randomized metrics with unique counts for new PHC ID: {new_phc_id} (Target Counts: {target_counts})")
    except Exception as e:
        print(f"Warning during dynamic seeding: {e}")
        
    flash(f"Switched context to: {phc['name']} ({phc['code']})", "success")
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/next-phc')
@login_required
def next_phc():
    current_id = session.get('phc_id')
    phcs = db.query("SELECT id FROM phcs ORDER BY name", fetch_all=True)
    if not phcs:
        return redirect(url_for('dashboard'))
        
    ids = [p['id'] for p in phcs]
    try:
        idx = ids.index(current_id)
        next_idx = (idx + 1) % len(ids)
    except ValueError:
        next_idx = 0
        
    return redirect(url_for('switch_phc', new_phc_id=ids[next_idx]))

@app.route('/prev-phc')
@login_required
def prev_phc():
    current_id = session.get('phc_id')
    phcs = db.query("SELECT id FROM phcs ORDER BY name", fetch_all=True)
    if not phcs:
        return redirect(url_for('dashboard'))
        
    ids = [p['id'] for p in phcs]
    try:
        idx = ids.index(current_id)
        prev_idx = (idx - 1) % len(ids)
    except ValueError:
        prev_idx = 0
        
    return redirect(url_for('switch_phc', new_phc_id=ids[prev_idx]))

if __name__ == '__main__':
    # Initialize DB (safety check)
    db.init_db()
    # Refresh cache from Supabase on startup
    try:
        db.sync_phcs_from_supabase()
    except Exception as e:
        print(f"Startup Supabase sync notice: {e}")
    # Start web application server
    app.run(host='127.0.0.1', port=8000, debug=True)
