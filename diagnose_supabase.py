import urllib.request
import urllib.error
import json
import ssl

def diagnose():
    url = "https://fhzicqsekyccqknjwmuc.supabase.co/rest/v1/phcs?select=*"
    headers = {
        "apikey": "sb_publishable_OLXix_wLaKB7g1CoXF8FNg_Ygj8GjiX",
        "Authorization": "Bearer sb_publishable_OLXix_wLaKB7g1CoXF8FNg_Ygj8GjiX"
    }
    
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    print(f"Requesting URL: {url}")
    print(f"Headers: {json.dumps(headers, indent=2)}")
    
    try:
        with urllib.request.urlopen(req, context=ctx) as response:
            status = response.getcode()
            headers_dict = dict(response.info())
            body = response.read().decode('utf-8')
            
            print("\n--- DIAGNOSTIC RESULTS ---")
            print(f"HTTP Status Code: {status}")
            print("\nResponse Headers:")
            for k, v in headers_dict.items():
                print(f"  {k}: {v}")
                
            print("\nResponse Body:")
            print(body)
            
            # Parse body
            parsed = json.loads(body)
            if isinstance(parsed, list):
                print(f"\nParsed Array Length: {len(parsed)}")
                if len(parsed) > 0:
                    print("Row Keys:", list(parsed[0].keys()))
            else:
                print("\nResponse is not a list!")
                
    except urllib.error.HTTPError as e:
        print("\n--- HTTP ERROR ENCOUNTERED ---")
        print(f"Code: {e.code}")
        print(f"Reason: {e.reason}")
        print(f"Headers: {e.headers}")
        try:
            print(f"Body: {e.read().decode('utf-8')}")
        except Exception:
            pass
    except Exception as e:
        print(f"\n--- GENERAL ERROR ENCOUNTERED ---: {e}")

if __name__ == '__main__':
    diagnose()
