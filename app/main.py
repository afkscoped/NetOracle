from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()

# 👇 THIS IS THE IMPORTANT PART
Instrumentator().instrument(app).expose(app)

@app.get("/")
def root():
    return {"message": "NetOracle running"}

# Existing routes (keep yours if you already have them)
@app.post("/api/data/upload-telemetry")
def upload():
    return {"status": "ok"}
