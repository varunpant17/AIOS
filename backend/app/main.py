from fastapi import FastAPI
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine,Base
from app.routers.api import api_router
# from app.models.user import User

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
)


@app.on_event("startup")
async def test_database_connection():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    print("Database connected successfully!")


    print("Database tables created successfully!")


@app.get("/")
async def root():
    return {"message": "AI Enterprise Operating System API"}


app.include_router(api_router)