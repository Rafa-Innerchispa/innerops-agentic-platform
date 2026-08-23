import requests
import pymongo

def get_tools():
    return ["sync_notion_mongo"]

def sync_notion_mongo(notion_token, database_id):
    """Consulta páginas de una DB de Notion y las unifica en MongoDB."""
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    try:
        res = requests.post(url, headers=headers, timeout=15)
        if res.status_code == 200:
            pages = res.json().get("results", [])
            client = pymongo.MongoClient("mongodb://localhost:27017/")
            db = client["inneros_global"]
            col = db["notion_raw_sync"]
            col.delete_many({})
            if pages:
                col.insert_many(pages)
            return {"status": "success", "synced_count": len(pages)}
        return {"status": "error", "message": res.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}
