from fastapi.testclient import TestClient
from app.main import app
import json

client = TestClient(app)
resp = client.post('/api/demo/run', json={'slice_id': 'slice_1', 'node_id': 'gnb_1', 'fault_type': 'congestion'})
print("DEMO RESPONSE DATA:")
print(json.dumps(resp.json().get('data', {}).get('remediation', {}), indent=2))

audit = client.get('/api/audit').json()
data = audit.get('data', [])
if data:
    last = data[-1]
    print("\nLAST AUDIT ENTRY:")
    print(json.dumps(last, indent=2))
else:
    print("\nAUDIT LOG IS EMPTY")
