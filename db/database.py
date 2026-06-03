from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import os
import json
from dotenv import load_dotenv

# Load the variables from the .env file
load_dotenv()

# Update with your MongoDB URI
MONGO_DETAILS = os.getenv("MONGO_URL")
LOCAL_DB_PATH = os.path.join(os.path.dirname(__file__), "local_db.json")

USE_MONGO = bool(MONGO_DETAILS)

if not USE_MONGO:
    print("⚠️ MONGO_URL not found in environment variables; falling back to local JSON DB.")
    # Ensure local db file exists
    if not os.path.exists(LOCAL_DB_PATH):
        with open(LOCAL_DB_PATH, 'w', encoding='utf-8') as f:
            json.dump({"rooms": [], "messages": [], "bot_stats": []}, f, ensure_ascii=False, indent=2)
    
    def _read_local_db():
        """Read JSON database; return default structure if empty or corrupt."""
        try:
            with open(LOCAL_DB_PATH, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    # Empty file — reset to default structure
                    default_db = {"rooms": [], "messages": [], "bot_stats": []}
                    _write_local_db(default_db)
                    return default_db
                return json.loads(content)
        except json.JSONDecodeError:
            # Corrupt JSON — reset to default structure
            default_db = {"rooms": [], "messages": [], "bot_stats": []}
            _write_local_db(default_db)
            return default_db
        except Exception as e:
            print(f"❌ Failed to read local database: {e}")
            return {"rooms": [], "messages": [], "bot_stats": []}

    def _write_local_db(data):
        """Write JSON database; ensure parent directory exists."""
        try:
            os.makedirs(os.path.dirname(LOCAL_DB_PATH), exist_ok=True)
            with open(LOCAL_DB_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ Failed to write local database: {e}")

else:
    client = AsyncIOMotorClient(MONGO_DETAILS)
    database = client.chat_db
    # Collections
    rooms_collection = database.get_collection("rooms")
    messages_collection = database.get_collection("messages")
    # NEW: Collection to track how many times each persona is "sensed"
    stats_collection = database.get_collection("bot_stats")

# --- Database Logic ---

async def create_room_in_db(room_id: str):
    """Creates a room if it doesn't exist."""
    if USE_MONGO:
        await rooms_collection.update_one(
            {"room_id": room_id},
            {"$setOnInsert": {"room_id": room_id, "created_at": datetime.now()}},
            upsert=True
        )
    else:
        data = _read_local_db()
        rooms = data.get("rooms", [])
        if not any(r.get("room_id") == room_id for r in rooms):
            rooms.append({"room_id": room_id, "created_at": datetime.now().isoformat()})
            data["rooms"] = rooms
            _write_local_db(data)

async def save_message(room_id: str, sender: str, text: str, *, note: str = None):
    """
    Saves a message. Optional note is stored for transcript/export (not shown in live chat).
    """
    message = {
        "room_id": room_id,
        "sender": sender,
        "text": text,
        "timestamp": datetime.now().isoformat(),
    }
    if note:
        message["note"] = note

    if USE_MONGO:
        doc = {
            "room_id": room_id,
            "sender": sender,
            "text": text,
            "timestamp": datetime.now(),
        }
        if note:
            doc["note"] = note
        await messages_collection.insert_one(doc)
    else:
        data = _read_local_db()
        messages = data.get("messages", [])
        messages.append(message)
        data["messages"] = messages
        _write_local_db(data)

async def get_room_history(room_id: str, limit: int = 50):
    """Retrieves history and ensures datetime objects are JSON-serializable."""
    if USE_MONGO:
        cursor = messages_collection.find({"room_id": room_id}).sort("timestamp", 1).limit(limit)
        messages = await cursor.to_list(length=limit)

        for msg in messages:
            msg["_id"] = str(msg["_id"])
            if isinstance(msg["timestamp"], datetime):
                msg["timestamp"] = msg["timestamp"].isoformat()
        return messages
    else:
        data = _read_local_db()
        messages = [m for m in data.get("messages", []) if m.get("room_id") == room_id]
        messages = sorted(messages, key=lambda m: m.get("timestamp", ""))[:limit]
        return messages

async def get_all_rooms():
    """Retrieves all available rooms."""
    if USE_MONGO:
        cursor = rooms_collection.find()
        rooms = await cursor.to_list(length=100)
        for r in rooms:
            r["_id"] = str(r["_id"])
            if isinstance(r.get("created_at"), datetime):
                r["created_at"] = r["created_at"].isoformat()
        return rooms
    else:
        data = _read_local_db()
        return data.get("rooms", [])

# ==========================================
# NEW: BOT SENSING ANALYTICS
# ==========================================

async def increment_bot_call(bot_name: str):
    """
    Increments a counter every time a bot 'senses' its name.
    Useful for the 'Active Personas' count on the Dashboard.
    """
    if USE_MONGO:
        await stats_collection.update_one(
            {"bot_name": bot_name},
            {"$inc": {"call_count": 1}, "$set": {"last_called": datetime.now()}},
            upsert=True
        )
    else:
        data = _read_local_db()
        stats = data.get("bot_stats", [])
        found = False
        for stat in stats:
            if stat.get("bot_name") == bot_name:
                stat["call_count"] = stat.get("call_count", 0) + 1
                stat["last_called"] = datetime.now().isoformat()
                found = True
                break
        if not found:
            stats.append({"bot_name": bot_name, "call_count": 1, "last_called": datetime.now().isoformat()})
        data["bot_stats"] = stats
        _write_local_db(data)

async def get_bot_leaderboard():
    """Returns list of bots and how many times they have been triggered."""
    if USE_MONGO:
        cursor = stats_collection.find().sort("call_count", -1)
        stats = await cursor.to_list(length=20)
        for s in stats:
            s["_id"] = str(s["_id"])
            if isinstance(s.get("last_called"), datetime):
                s["last_called"] = s["last_called"].isoformat()
        return stats
    else:
        data = _read_local_db()
        stats = sorted(data.get("bot_stats", []), key=lambda item: item.get("call_count", 0), reverse=True)
        for s in stats:
            # keep ISO string as-is
            pass
        return stats

async def delete_room_data(room_id: str):
    """Complete cleanup of a room and its messages from the DB."""
    if USE_MONGO:
        await rooms_collection.delete_one({"room_id": room_id})
        await messages_collection.delete_many({"room_id": room_id})
    else:
        data = _read_local_db()
        data["rooms"] = [r for r in data.get("rooms", []) if r.get("room_id") != room_id]
        data["messages"] = [m for m in data.get("messages", []) if m.get("room_id") != room_id]
        _write_local_db(data)
    print(f"🗑️ DB: All data for room {room_id} deleted.")


async def wipe_all_chat_history() -> int:
    """Delete every room and message (local JSON or Mongo). Returns message count removed."""
    if USE_MONGO:
        msg_result = await messages_collection.delete_many({})
        await rooms_collection.delete_many({})
        n = int(msg_result.deleted_count)
        print(f"🗑️ DB: Wiped all Mongo chat history ({n} messages).")
        return n
    data = _read_local_db()
    n = len(data.get("messages", []))
    _write_local_db({"rooms": [], "messages": [], "bot_stats": data.get("bot_stats", [])})
    print(f"🗑️ DB: Wiped local chat history ({n} messages, all rooms).")
    return n