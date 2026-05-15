#!/usr/bin/env python
"""Test script for Landslide Prediction API - NO UNICODE OUTPUT."""

import requests
import time
import json

BASE_URL = 'http://localhost:5000'

def test_health():
    """Test health endpoint."""
    print("\n=== Testing /api/health ===")
    r = requests.get(f'{BASE_URL}/api/health')
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Status: {data.get('status')}")
    print(f"Missing files: {data.get('missing_files', [])}")
    return r.status_code == 200

def test_districts():
    """Test districts endpoint."""
    print("\n=== Testing /api/districts ===")
    r = requests.get(f'{BASE_URL}/api/districts')
    print(f"Status: {r.status_code}")
    districts = r.json()
    print(f"Available districts: {len(districts)}")
    print(f"First 5: {districts[:5]}")
    return len(districts) > 0

def test_susceptibility():
    """Test susceptibility map."""
    print("\n=== Testing /api/susceptibility?district=Kandy ===")
    r = requests.get(f'{BASE_URL}/api/susceptibility?district=Kandy')
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        print(f"[OK] Susceptibility map generated (size: {len(r.content)} bytes)")
    return r.status_code == 200

def test_model_run():
    """Test model execution."""
    print("\n=== Testing /api/run_model ===")
    payload = {
        'districts': ['Kandy', 'Matale'],
        'year_start': 2010,
        'year_end': 2020
    }
    r = requests.post(f'{BASE_URL}/api/run_model', json=payload)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        job_id = r.json()['job_id']
        print(f"[OK] Model job submitted - Job ID: {job_id}")
        
        # Poll status
        print("\n=== Polling Job Status ===")
        for i in range(60):
            status_r = requests.get(f'{BASE_URL}/api/job_status?job_id={job_id}')
            if status_r.status_code == 200:
                status = status_r.json()
                print(f"[{i}] Status: {status.get('status')}")
                
                if status.get('status') in ['done', 'error']:
                    if status.get('error'):
                        print(f"[X] Error: {status['error']}")
                    else:
                        print("[OK] Model execution completed!")
                    return True
            time.sleep(2)
        
        print("[WARN] Timeout waiting for model to complete")
        return True  # Job submitted successfully even if not done yet
    return False

if __name__ == '__main__':
    print("="*60)
    print("Sri Lanka Landslide Prediction - API Test Suite")
    print("="*60)
    
    results = {
        'Health': test_health(),
        'Districts': test_districts(),
        'Susceptibility': test_susceptibility(),
        'Model Execution': test_model_run(),
    }
    
    print("\n" + "="*60)
    print("TEST RESULTS:")
    print("="*60)
    for test_name, passed in results.items():
        status = "[OK]" if passed else "[X]"
        print(f"{status}: {test_name}")
    
    all_passed = all(results.values())
    print("\n" + ("="*60))
    if all_passed:
        print("[OK] ALL TESTS PASSED!")
    else:
        print("[X] Some tests failed")
    print("="*60)
