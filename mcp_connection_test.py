#!/usr/bin/env python3
import socket
import json

def check_connection(host="localhost", port=8000):
    """Check MCP server connection"""
    print(f"Checking {host}:{port}...\n")
    
    # TCP connection
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    if sock.connect_ex((host, port)) != 0:
        print("✗ Connection failed")
        return False
    print("✓ TCP connection OK")
    sock.close()
    
    # Test streamable-http
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    payload = json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"checker","version":"1.0"}}})
    request = f"POST /mcp HTTP/1.1\r\nHost: {host}:{port}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n{payload}"
    sock.sendall(request.encode())
    resp = sock.recv(4096).decode('utf-8', errors='ignore')
    sock.close()
    
    if "200 OK" in resp:
        data = json.loads(resp.split('\r\n\r\n')[1].split('\r\n')[0])
        print(f"✓ Transport: streamable-http")
        print(f"✓ Server: {data['result']['serverInfo']['name']} v{data['result']['serverInfo']['version']}")
        print(f"✓ Protocol: {data['result']['protocolVersion']}")
        return True
    
    return False

if __name__ == "__main__":
    check_connection()
