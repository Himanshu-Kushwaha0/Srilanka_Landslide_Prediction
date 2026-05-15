import requests

# Test health endpoint
r = requests.get('http://localhost:5000/api/health')
print(f"Health Status: {r.status_code}")
print(f"Response: {r.json()}")

# Test districts
r = requests.get('http://localhost:5000/api/districts')
print(f"\nDistricts Status: {r.status_code}")
print(f"Count: {len(r.json())}")
print(f"Sample: {r.json()[:3] if r.json() else 'None'}")
