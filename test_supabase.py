import urllib.request
import json

def test():
    url = "https://fhzicqsekyccqknjwmuc.supabase.co/rest/v1/phcs?select=*"
    headers = {
        "apikey": "sb_publishable_OLXix_wLaKB7g1CoXF8FNg_Ygj8GjiX",
        "Authorization": "Bearer sb_publishable_OLXix_wLaKB7g1CoXF8FNg_Ygj8GjiX"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            data = response.read()
            items = json.loads(data.decode('utf-8'))
            print("Successfully connected to Supabase!")
            print(f"Number of PHCs found: {len(items)}")
            if len(items) > 0:
                print("First item keys and values:")
                for k, v in items[0].items():
                    print(f"  {k}: {v}")
            else:
                print("phcs table is empty.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    test()
