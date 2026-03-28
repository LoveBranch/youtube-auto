"""FastAPI 메인 앱."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.routes import generate, status, download, analyze, remix, channel, make_from_clips

app = FastAPI(title="YouTube Auto API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate.router, prefix="/api", tags=["generate"])
app.include_router(status.router, prefix="/api", tags=["status"])
app.include_router(download.router, prefix="/api", tags=["download"])
app.include_router(analyze.router, prefix="/api", tags=["analyze"])
app.include_router(remix.router, prefix="/api", tags=["remix"])
app.include_router(channel.router, prefix="/api", tags=["channel"])
app.include_router(make_from_clips.router, prefix="/api", tags=["make-from-clips"])



@app.get("/")
async def root():
    return {"service": "YouTube Auto API", "status": "running"}
