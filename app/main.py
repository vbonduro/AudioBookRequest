from fastapi import FastAPI
from app.routers import root

app = FastAPI()

app.include_router(root.router)
