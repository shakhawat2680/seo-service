from fastapi import FastAPI, Depends
from analyzer import analyze_seo
from auth import verify_api_key

app = FastAPI(title="AutoSEO Service")

@app.get("/")
def home():
    return {"status": "SEO Engine Running"}

@app.post("/analyze")
def analyze(payload: dict, tenant=Depends(verify_api_key)):
    return analyze_seo(payload)
