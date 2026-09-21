import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "master_data")

client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB_NAME]
users_collection = db["users"]