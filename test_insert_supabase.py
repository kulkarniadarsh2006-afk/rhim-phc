import urllib.request
import json

def test_insert():
    url = "https://fhzicqsekyccqknjwmuc.supabase.co/rest/v1/phcs"
    headers = {
        "apikey": "sb_publishable_OLXix_wLaKB7g1CoXF8FNg_Ygj8GjiX",
        "Authorization": "Bearer sb_publishable_OLXix_wLaKB7g1CoXF8FNg_Ygj8GjiX",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    payload = {
        "name": "Kanakapura PHC",
        "code": "PHC-KAN-001",
        "district": "Ramanagara",
        "state": "Karnataka"
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode('utf-8'), 
        headers=headers, 
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            data = response.read()
            items = json.loads(data.decode('utf-8'))
            print("Successfully inserted a PHC into Supabase!")
            print(items)
    except Exception as e:
        print(f"Error inserting: {e}")

if __name__ == '__main__':
    test_insert()
