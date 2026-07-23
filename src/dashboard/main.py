from fastapi import FastAPI

from .routes import router

app = FastAPI(title="Media Dashboard")
app.include_router(router)
