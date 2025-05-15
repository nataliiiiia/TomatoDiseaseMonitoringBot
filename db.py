import os
from supabase import create_client
from dotenv import load_dotenv
from typing import List, Optional, Dict

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_user_db_id(telegram_id: str) -> Optional[str]:
    resp = supabase.table("users").select("id").eq("telegram_id", telegram_id).execute()
    return resp.data[0]["id"] if resp.data else None

def create_user_if_not_exists(telegram_id: str, username: str) -> str:
    user_id = get_user_db_id(telegram_id)
    if not user_id:
        insert = supabase.table("users") \
            .insert({"telegram_id": telegram_id, "username": username}) \
            .execute()
        user_id = insert.data[0]["id"]
    return user_id

def bind_robot_to_user(user_db_id: str, robot_id: str) -> None:
    supabase.table("robots") \
        .upsert({"robot_id": robot_id, "user_id": user_db_id}) \
        .execute()

def get_robot_id_for_user(user_db_id: str) -> Optional[str]:
    resp = supabase.table("robots").select("robot_id").eq("user_id", user_db_id).execute()
    return resp.data[0]["robot_id"] if resp.data else None

def get_telegram_id_by_robot(robot_id: str) -> Optional[str]:
    resp = supabase.table("robots").select("user_id").eq("robot_id", robot_id).execute()
    if not resp.data:
        return None
    user_db_id = resp.data[0]["user_id"]
    user = supabase.table("users").select("telegram_id").eq("id", user_db_id).execute()
    return user.data[0]["telegram_id"] if user.data else None

def get_all_plants(user_db_id: str) -> List[Dict]:
    resp = (
        supabase.table("plants")
        .select("plant_id, species, location, status, created_at")
        .eq("user_id", user_db_id)
        .eq("status", "active")
        .order("created_at", desc=False)
        .execute()
    )
    return resp.data or []

def add_plant(user_db_id: str, plant_id: str, species: str, location: str) -> None:
    supabase.table("plants").insert({
        "plant_id": plant_id,
        "user_id": user_db_id,
        "species": species,
        "location": location
    }).execute()

def delete_plant(user_db_id: str, plant_id: str) -> None:
    supabase.table("plants") \
        .delete() \
        .eq("user_id", user_db_id) \
        .eq("plant_id", plant_id) \
        .execute()

def set_qr_message_id(plant_id: str, message_id: int) -> None:
    supabase.table("plants") \
        .update({"qr_message_id": message_id}) \
        .eq("plant_id", plant_id) \
        .execute()

def get_qr_message_id(plant_id: str) -> Optional[int]:
    resp = supabase.table("plants").select("qr_message_id").eq("plant_id", plant_id).execute()
    return resp.data[0]["qr_message_id"] if resp.data and resp.data[0].get("qr_message_id") else None

def get_scan_history(plant_id: str, limit: int = 5) -> List[Dict]:
    resp = (
        supabase.table("scans")
        .select("*, plants(species, location)")
        .eq("plant_id", plant_id)
        .order("timestamp", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []

def get_scan_timestamps(user_db_id: str) -> List[str]:
    robot_id = get_robot_id_for_user(user_db_id)
    if not robot_id:
        return []
    resp = (
        supabase.table("scans")
        .select("timestamp")
        .eq("robot_id", robot_id)
        .order("timestamp", desc=True)
        .limit(10)
        .execute()
    )
    return [row["timestamp"] for row in resp.data] or []

def get_scans_by_timestamp(user_db_id: str, timestamp: str) -> List[Dict]:
    robot_id = get_robot_id_for_user(user_db_id)
    if not robot_id:
        return []
    resp = (
        supabase.table("scans")
        .select("*, plants(species, location)")
        .eq("robot_id", robot_id)
        .eq("timestamp", timestamp)
        .execute()
    )
    return resp.data or []