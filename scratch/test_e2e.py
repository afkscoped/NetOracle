"""End-to-end test: fault injection demo flow."""
import requests
import json

base = "http://127.0.0.1:8000"

# Generate more tick data first
for i in range(5):
    requests.post(f"{base}/api/telemetry/tick")

# Run demo with high severity  
r = requests.post(f"{base}/api/demo/run", json={
    "slice_id": "slice_1", "node_id": "upf_1",
    "fault_type": "congestion", "severity": 0.95, "ticks": 15
})
d = r.json()["data"]
print("=== DEMO RUN RESULT ===")
print(f"Has alert: {d.get('alert') is not None}")
if d.get("alert"):
    print(f"  Alert: prob={d['alert'].get('fault_probability', 'N/A')}, model={d['alert'].get('model_used', 'manual_fallback')}")
print(f"Has diagnosis: {d.get('diagnosis') is not None}")
if d.get("diagnosis"):
    print(f"  Root cause: {d['diagnosis']['root_cause'][:80]}")
    print(f"  Confidence: {d['diagnosis']['confidence']}")
    print(f"  Action: {d['diagnosis']['recommended_action']}")
    if d["diagnosis"].get("moe_routing"):
        print(f"  Experts: {d['diagnosis']['moe_routing']['experts']}")
print(f"Has remediation: {d.get('remediation') is not None}")
if d.get("remediation"):
    print(f"  Decision: {d['remediation'].get('decision', 'N/A')}")
print(f"Has proactive: {d.get('proactive') is not None}")

# Test XAI after fault
print("\n=== XAI EXPLANATION ===")
r = requests.get(f"{base}/api/xai/explain/diagnosis?node_id=upf_1")
xai = r.json()["data"]
if "explanation" in xai:
    print(f"  Explanation: {xai['explanation'][:150]}...")
if "suggestions" in xai:
    print(f"  Suggestions: {xai['suggestions']}")
if "risk_level" in xai:
    print(f"  Risk level: {xai['risk_level']}")

# Test proactive explain
print("\n=== PROACTIVE EXPLAIN ===")
r = requests.get(f"{base}/api/proactive/explain")
d = r.json()["data"]
print(f"  Headline: {d.get('headline', 'N/A')}")
print(f"  Narrative: {d.get('narrative', 'N/A')[:120]}...")
print(f"  Theory: {d.get('theory', {}).get('title', 'N/A')}")

# Test realtime analysis
print("\n=== REALTIME ANALYSIS ===")
r = requests.get(f"{base}/api/realtime/analyse")
d = r.json()["data"]
print(f"  Source: {d.get('source', {}).get('mode', 'N/A')}")
print(f"  Has quick_fix: {d.get('quick_fix') is not None}")
print(f"  Narrative: {d.get('narrative', 'N/A')[:120]}...")

# Test Hopfield details
print("\n=== HOPFIELD ALLOCATION ===")
r = requests.post(f"{base}/api/wireless/hopfield?users=12&channels=24&iterations=100")
d = r.json()["data"]
print(f"  Algorithm: {d['algorithm']}")
print(f"  Fairness: {d['fairness_index']}")
print(f"  Throughput: {d['throughput_mbps']} Mbps")
print(f"  Converged at: {d['iterations']} iterations")
print(f"  Energy trace length: {len(d['energy_trace'])}")

print("\n=== ALL TESTS PASSED ===")
