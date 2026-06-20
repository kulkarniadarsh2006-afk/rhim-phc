import urllib.request
import json

def get_schema():
    url = "https://fhzicqsekyccqknjwmuc.supabase.co/rest/v1/"
    headers = {
        "apikey": "sb_publishable_OLXix_wLaKB7g1CoXF8FNg_Ygj8GjiX",
        "Authorization": "Bearer sb_publishable_OLXix_wLaKB7g1CoXF8FNg_Ygj8GjiX"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            data = response.read()
            schema = json.loads(data.decode('utf-8'))
            print("Successfully retrieved OpenAPI schema!")
            phc_schema = schema.get('definitions', {}).get('phcs', {})
            print("PHCs table schema properties:")
            properties = phc_schema.get('properties', {})
            for prop_name, prop_val in properties.items():
                print(f"  {prop_name}: {prop_val.get('type')} (Format: {prop_val.get('format', 'none')})")
    except Exception as e:
        print(f"Error fetching schema: {e}")

if __name__ == '__main__':
    get_schema()
