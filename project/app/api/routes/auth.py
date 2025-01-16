from fastapi import APIRouter, HTTPException
from app.db.helpers import execute_query
from app.utils.security import hash_password, verify_password

router = APIRouter()

@router.post("/signup")
def signup(username: str, email: str, password: str):
    query = "SELECT id FROM users WHERE email = %s"
    existing_user = execute_query(query, (email,))
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already in use")
    hashed_password = hash_password(password)
    query = "INSERT INTO users (username, email, hashed_password) VALUES (%s, %s, %s)"
    execute_query(query, (username, email, hashed_password))
    return {"message": "User created successfully"}

@router.post("/login")
def login(email: str, password: str):
    query = "SELECT id, hashed_password FROM users WHERE email = %s"
    user = execute_query(query, (email,))
    if not user or not verify_password(password, user[0]["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"message": "Login successful", "user_id": user[0]["id"]}
