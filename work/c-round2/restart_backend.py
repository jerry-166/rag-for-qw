"""重启 backend：杀旧进程 + 启动新进程"""
import subprocess, time, os, signal

# 杀占用 8003 端口的进程
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('127.0.0.1', 8003))
sock.close()

if result == 0:
    # 端口被占用，找 PID 并杀
    r = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
    for line in r.stdout.split('\n'):
        if ':8003' in line and 'LISTENING' in line:
            pid = int(line.strip().split()[-1])
            print(f'killing backend PID {pid}')
            subprocess.run(['taskkill', '/PID', str(pid), '/F', '/T'],
                         capture_output=True)
            break
    time.sleep(3)

# 启动新 backend
print('starting new backend --workers 4...')
p = subprocess.Popen(
    ['d:\\workspace\\rag-for-qw\\backend\\.venv\\Scripts\\python.exe',
     '-m', 'uvicorn', 'app:app', '--host', '0.0.0.0',
     '--port', '8003', '--workers', '4'],
    cwd='d:\\workspace\\rag-for-qw\\backend',
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NO_WINDOW
)
print(f'backend started PID {p.pid}')

# 等待 ready
import requests
for i in range(10):
    time.sleep(5)
    try:
        r = requests.post('http://localhost:8003/api/auth/login',
            data={'username':'loadtester','password':'Loadtest#123'}, timeout=15)
        if r.status_code == 200:
            print(f'backend ready (attempt {i+1})')
            break
    except:
        print(f'attempt {i+1}: not ready yet')
else:
    print('backend failed to start')
