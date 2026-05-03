import os
import json
from pathlib import Path

EXPORT_DIR = Path("exports")
EXPORT_DIR.mkdir(exist_ok=True)

def export(kind):
    file = EXPORT_DIR / f"netoracle-{kind}.json"

    data = {
        "type": kind,
        "status": "exported"
    }

    file.write_text(json.dumps(data))

    provider = os.getenv("CLOUD_PROVIDER", "local")

    if provider == "aws":
        print("Simulating AWS upload...")
    elif provider == "supabase":
        print("Simulating Supabase upload...")
    else:
        print("Local export only")

    return str(file)


if __name__ == "__main__":
    print(export("audit"))
    print(export("benchmark"))
