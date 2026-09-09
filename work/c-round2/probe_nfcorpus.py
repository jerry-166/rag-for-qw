"""探 BeIR/nfcorpus 在 HuggingFace 上的可访问性 + 列文件
+ 探 backend venv 是否有 datasets/beir 库"""
import sys, urllib.request, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 1. HF API 列 BeIR/nfcorpus 仓库文件
url = 'https://huggingface.co/api/datasets/BeIR/nfcorpus'
print('=== BeIR/nfcorpus HF API ===')
try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    r = urllib.request.urlopen(req, timeout=15)
    j = json.loads(r.read().decode('utf-8'))
    siblings = j.get('siblings', [])
    print(f'files ({len(siblings)}):')
    for s in siblings[:30]:
        print(f'  {s.get("rfilename")}')
except Exception as e:
    print(f'ERR: {e}')

# 2. BeIR/nfcorpus-qrels
url2 = 'https://huggingface.co/api/datasets/BeIR/nfcorpus-qrels'
print('\n=== BeIR/nfcorpus-qrels HF API ===')
try:
    req = urllib.request.Request(url2, headers={'User-Agent': 'Mozilla/5.0'})
    r = urllib.request.urlopen(req, timeout=15)
    j = json.loads(r.read().decode('utf-8'))
    siblings = j.get('siblings', [])
    print(f'files ({len(siblings)}):')
    for s in siblings[:30]:
        print(f'  {s.get("rfilename")}')
except Exception as e:
    print(f'ERR: {e}')

# 3. backend venv 库探
print('\n=== backend venv 库探 ===')
try:
    import datasets
    print(f'datasets: {datasets.__version__}')
except ImportError as e:
    print(f'datasets NOT installed: {e}')
try:
    import beir
    print(f'beir: {getattr(beir, "__version__", "unknown")}')
except ImportError as e:
    print(f'beir NOT installed: {e}')
