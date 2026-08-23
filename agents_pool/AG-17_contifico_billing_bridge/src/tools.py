import requests

def get_tools():
    return ["fetch_contifico_items"]

def fetch_contifico_items(api_key, endpoint="producto"):
    """Consulta datos oficiales del API de Contifico v2."""
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json"
    }
    url = f"https://api.contifico.com/v2/{endpoint}/"
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            return {"status": "success", "data": res.json()}
        return {"status": "error", "message": res.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}
