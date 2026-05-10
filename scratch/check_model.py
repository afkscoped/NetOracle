import requests, json
r = requests.get("http://127.0.0.1:8000/api/metrics")
d = r.json()["data"]
print(f"Model: {d['model_active']}")
print(f"AUC: {d['model_auc']}")
print(f"Hidden dim: {d.get('model_info', {}).get('hidden_dim', 'N/A')}")
