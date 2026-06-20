import sys
from database import db

def test_database():
    print("Testing database integrity...")
    try:
        # Check users count
        users = db.query("SELECT COUNT(*) as count FROM users", fetch_one=True)
        print(f"- Seeded users count: {users['count']}")
        assert users['count'] == 3, "Expected 3 users."
        
        # Check medicines count
        medicines = db.query("SELECT COUNT(*) as count FROM medicines", fetch_one=True)
        print(f"- Seeded medicines count: {medicines['count']}")
        assert medicines['count'] >= 10, "Expected at least 10 medicines."
        
        # Check inventory items count
        inventory = db.query("SELECT COUNT(*) as count FROM inventory", fetch_one=True)
        print(f"- Seeded inventory batches: {inventory['count']}")
        assert inventory['count'] >= 10, "Expected at least 10 inventory items."
        
        # Check active alerts
        alerts = db.query("SELECT COUNT(*) as count FROM shortage_alerts WHERE resolved_at IS NULL", fetch_one=True)
        print(f"- Active shortage alerts: {alerts['count']}")
        assert alerts['count'] > 0, "Expected at least one active alert."
        
        # Check patient logs
        opd = db.query("SELECT COUNT(*) as count FROM patient_statistics", fetch_one=True)
        print(f"- Seeded daily OPD logs: {opd['count']}")
        assert opd['count'] >= 30, "Expected 30 daily patient logs."
        
        print("\nSUCCESS: Database structure, relations, and seed data verified.")
        sys.exit(0)
    except Exception as e:
        print(f"\nFAILURE: Verification failed. Details: {e}")
        sys.exit(1)

if __name__ == '__main__':
    test_database()
