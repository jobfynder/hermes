from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(
    title="Hermes",
    version="0.1.0"
)


class JobParseRequest(BaseModel):
    text: str


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "Hermes",
        "version": "0.1.0"
    }


@app.post("/v1/jobs/parse")
def parse_job(request: JobParseRequest):
    text = request.text.strip()

    return {
        "success": True,
        "data": {
            "title": "Unknown",
            "summary": text[:300],
            "skills": [],
            "location": None,
            "employment_type": None
        }
    }