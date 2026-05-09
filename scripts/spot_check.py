import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def check_nl_query():
    print("--- Checking NL Query ---")
    payload = {"query": "Which VNFs are connected to Slice 1?"}
    r = requests.post(f"{BASE_URL}/api/nl-query", json=payload)
    print(json.dumps(r.json(), indent=2))

def check_fault_injection():
    print("\n--- Checking Fault Injection ---")
    payload = {"node_id": "gnb_1", "fault_type": "prb_congestion", "severity": 0.85}
    r = requests.post(f"{BASE_URL}/api/fault/inject", json=payload)
    print(json.dumps(r.json(), indent=2))

def check_rl_recommend():
    print("\n--- Checking RL Recommend (High Risk) ---")
    payload = {"node_id": "upf_1", "fault_type": "upf_overload", "conformal_risk_score": 0.95}
    r = requests.post(f"{BASE_URL}/api/rl/recommend", json=payload)
    print(json.dumps(r.json(), indent=2))

def check_policy():
    print("\n--- Checking RL Policy ---")
    r = requests.get(f"{BASE_URL}/api/rl/policy")
    print(json.dumps(r.json(), indent=2))

if __name__ == "__main__":
    check_nl_query()
    check_fault_injection()
    check_rl_recommend()
    check_policy()
