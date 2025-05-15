from fastapi import FastAPI, HTTPException
from db import get_telegram_id_by_robot

app = FastAPI()


@app.get("/api/get_user")
async def get_user(robot_id: str):
    telegram_id = get_telegram_id_by_robot(robot_id)
    if not telegram_id:
        raise HTTPException(status_code=404, detail="Робоплатформа не знайдена")
    return {"telegram_id": telegram_id}
