import sys
from werkzeug.security import check_password_hash
from database import db

def check_login(username, password):
    print(f"Testing login for username: '{username}'...")
    
    # 1. Check if user exists in the local database
    try:
        user = db.query(
            "SELECT u.*, p.name as phc_name, p.district as phc_district FROM users u JOIN phcs p ON u.phc_id = p.id WHERE u.username = %s",
            (username,), fetch_one=True
        )
        print(f"Query Result: {user}")
        
        if not user:
            print("  FAIL: User not found in database or JOIN with phcs failed.")
            # Let's check if the user exists without the JOIN
            plain_user = db.query("SELECT * FROM users WHERE username = %s", (username,), fetch_one=True)
            print(f"  Plain User (no JOIN): {plain_user}")
            if plain_user:
                phc_exists = db.query("SELECT * FROM phcs WHERE id = %s", (plain_user['phc_id'],), fetch_one=True)
                print(f"  PHC check for ID {plain_user['phc_id']}: {phc_exists}")
            return
            
        # 2. Check password hash
        pw_check = check_password_hash(user['password_hash'], password)
        print(f"Password Check Result: {pw_check}")
        
        if pw_check:
            print("  SUCCESS: Credentials are valid!")
        else:
            print("  FAIL: Password hash does not match.")
            
    except Exception as e:
        print(f"  ERROR during query: {e}")

if __name__ == '__main__':
    check_login("supervisor", "password123")
