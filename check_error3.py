import requests

job_id = '1778650512574'
r = requests.get(f'http://localhost:5000/api/job_status?job_id={job_id}')
if r.status_code == 200:
    status = r.json()
    print("="*60)
    print("FULL JOB LOG:")
    print("="*60)
    print(status.get('log', ''))
    print("="*60)
    print(f"Error: {status.get('error')}")
