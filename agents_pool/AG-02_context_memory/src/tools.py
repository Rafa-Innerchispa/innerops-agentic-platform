import pymongo

def get_tools():
    return ["save_log"]

def save_log(log_data):
    """Guarda el historial técnico en MongoDB global."""
    try:
        client = pymongo.MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=2000)
        db = client["inneros_global"]
        col = db["execution_logs"]
        res = col.insert_one(log_data)
        return {"status": "success", "id": str(res.inserted_id)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
