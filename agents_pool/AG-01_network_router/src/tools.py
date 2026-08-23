import socket

def get_tools():
    return ["scan_ports"]

def scan_ports(start_port=8096):
    """Busca el primer puerto TCP libre a partir del puerto provisto."""
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            result = s.connect_ex(('127.0.0.1', port))
            if result != 0: # Puerto libre
                return {"status": "success", "free_port": port}
        port += 1
    return {"status": "error", "message": "No free ports found"}
