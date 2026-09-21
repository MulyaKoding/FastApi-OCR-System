from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from bson import ObjectId
from database import users_collection
from models import UserModel
from ocr_utils import extract_ktp_with_groq

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/users")
async def create_user(user: UserModel):
    result = await users_collection.insert_one(user.model_dump(exclude={"id"}))
    return {"id": str(result.inserted_id)}

@app.get("/users")
async def get_users():
    users = []
    async for u in users_collection.find():
        u["_id"] = str(u["_id"])
        users.append(u)
    return users

@app.get("/users/{user_id}")
async def get_user(user_id: str):
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["_id"] = str(user["_id"])
    return user

@app.post("/ktp/scan")
async def scan_ktp(file: UploadFile = File(...)):
    image_bytes = await file.read()
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]

    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Format file tidak didukung. Gunakan JPG, PNG, atau WEBP.")

    if len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Ukuran file terlalu besar. Maksimal 5MB.")

    try:
        data = extract_ktp_with_groq(image_bytes, file.content_type)
        return data
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Terjadi kesalahan saat memproses KTP")