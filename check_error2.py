import requests

job_id = '1778650422162'
r = requests.get(f'http://localhost:5000/api/job_status?job_id={job_id}')
if r.status_code == 200:
    status = r.json()
    print("="*60)
    print("FULL JOB LOG (Last 3000 chars):")
    print("="*60)
    log = status.get('log', '')
    print(log[-3000:] if len(log) > 3000 else log)
    print("="*60)
    print(f"Error: {status.get('error')}")
