#!/usr/bin/env python3
"""
Test script for Harbor API endpoints
Run after starting the server with: uvicorn app.main:app --reload
"""

import requests
import json
from pathlib import Path

BASE_URL = "http://localhost:8000"


def test_health():
    """Test health endpoint"""
    print("\n=== Testing Health Endpoint ===")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    assert response.status_code == 200
    print("✅ Health check passed")


def test_cashflow_analyze():
    """Test cashflow analysis with sample CSV"""
    print("\n=== Testing CashFlow Analysis ===")
    
    csv_path = Path(__file__).parent / "sample_pos_data.csv"
    
    with open(csv_path, "rb") as f:
        files = {"csv_file": ("sample.csv", f, "text/csv")}
        data = {
            "rent": 3000,
            "payroll": 5000,
            "other": 1000,
            "cash_on_hand": 15000,
            "business_name": "Test Cafe"
        }
        
        response = requests.post(
            f"{BASE_URL}/cashflow/analyze",
            files=files,
            data=data
        )
    
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"Analysis ID: {result['analysis_id']}")
        print(f"Risk State: {result['metrics']['risk_state']}")
        print(f"Confidence: {result['metrics']['confidence']:.2%}")
        print(f"Avg Daily Revenue: ${result['metrics']['avg_daily_revenue']:.2f}")
        print(f"30-day Trend: {result['metrics']['trend_30d']:.1f}%")
        print("\nExplanation Bullets:")
        for bullet in result['explanation']['bullets']:
            print(f"  - {bullet}")
        print("✅ CashFlow analysis passed")
        return result['analysis_id']
    else:
        print(f"Error: {response.text}")
        raise Exception("CashFlow analysis failed")


def test_rentguard_impact(analysis_id):
    """Test rent impact simulation"""
    print("\n=== Testing RentGuard Impact ===")
    
    payload = {
        "analysis_id": analysis_id,
        "increase_pct": 15.0,
        "effective_date": "2025-02-01"
    }
    
    response = requests.post(
        f"{BASE_URL}/rentguard/impact",
        json=payload
    )
    
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"Scenario ID: {result['scenario_id']}")
        print(f"Current Rent: ${result['metrics']['current_rent']:.2f}")
        print(f"New Rent: ${result['metrics']['new_rent']:.2f}")
        print(f"Delta: ${result['metrics']['delta_monthly']:.2f} ({result['metrics']['delta_pct']:.1f}%)")
        print(f"Risk State Change: {result['metrics']['current_risk_state']} → {result['metrics']['new_risk_state']}")
        print(f"\nSummary: {result['explanation']['summary']}")
        print("✅ RentGuard impact passed")
    else:
        print(f"Error: {response.text}")
        raise Exception("RentGuard impact failed")


def test_list_analyses():
    """Test listing analyses"""
    print("\n=== Testing List Analyses ===")
    
    response = requests.get(f"{BASE_URL}/cashflow/analyses?limit=5")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        analyses = response.json()
        print(f"Found {len(analyses)} analyses")
        for analysis in analyses:
            print(f"  - ID {analysis['id']}: {analysis['business_name']} ({analysis['risk_state']})")
        print("✅ List analyses passed")
    else:
        print(f"Error: {response.text}")


def test_touristpulse():
    """Test tourist pulse endpoint"""
    print("\n=== Testing TouristPulse ===")
    
    response = requests.get(
        f"{BASE_URL}/touristpulse/outlook",
        params={"location": "Santa Cruz", "days": 3}
    )
    
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"Location: {result['location']}")
        print(f"Outlook days: {len(result['outlook'])}")
        print("✅ TouristPulse passed (placeholder)")
    else:
        print(f"Error: {response.text}")


def test_shopline():
    """Test shopline endpoints"""
    print("\n=== Testing Shopline ===")
    
    # Search
    search_payload = {
        "query": "coffee",
        "category": "cafe"
    }
    
    response = requests.post(
        f"{BASE_URL}/shopline/search",
        json=search_payload
    )
    
    print(f"Search Status: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"Found {result['total']} results")
        print("✅ Shopline search passed (placeholder)")


def main():
    """Run all tests"""
    print("=" * 60)
    print("Harbor API Test Suite")
    print("=" * 60)
    
    try:
        # Test health
        test_health()
        
        # Test cashflow analysis
        analysis_id = test_cashflow_analyze()
        
        # Test rent impact
        test_rentguard_impact(analysis_id)
        
        # Test list analyses
        test_list_analyses()
        
        # Test placeholder endpoints
        test_touristpulse()
        test_shopline()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ TESTS FAILED: {e}")
        print("=" * 60)
        raise


if __name__ == "__main__":
    main()
