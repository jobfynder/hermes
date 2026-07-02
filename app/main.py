from fastapi import FastAPI

app = FastAPI(
    title="Hermes",
    version="0.1.0"
)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "Hermes",
        "version": "0.1.0"
    }