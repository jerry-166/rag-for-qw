"""下载 NFCorpus 数据集（HuggingFace BeIR/nfcorpus + BeIR/nfcorpus-qrels）
到 d:\\workspace\\rag-for-qw\\work\\c-round2\\nfcorpus\\
"""
import os, sys, urllib.request, urllib.error
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DST = r'd:\workspace\rag-for-qw\work\c-round2\nfcorpus'
os.makedirs(DST, exist_ok=True)

FILES = [
    ('corpus.parquet',
     'https://huggingface.co/datasets/BeIR/nfcorpus/resolve/main/corpus/corpus-00000-of-00001.parquet'),
    ('queries.parquet',
     'https://huggingface.co/datasets/BeIR/nfcorpus/resolve/main/queries/queries-00000-of-00001.parquet'),
    ('qrels.test.tsv',
     'https://huggingface.co/datasets/BeIR/nfcorpus-qrels/resolve/main/test.tsv'),
    ('qrels.dev.tsv',
     'https://huggingface.co/datasets/BeIR/nfcorpus-qrels/resolve/main/dev.tsv'),
]

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) rag-eval/1.0'}

def download(url, dst):
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        print(f'[skip] {os.path.basename(dst)} ({os.path.getsize(dst)/1024:.1f} KB)')
        return True
    print(f'[get] {url}')
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        with open(dst, 'wb') as f:
            f.write(data)
        print(f'  saved {len(data)/1024:.1f} KB -> {dst}')
        return True
    except urllib.error.HTTPError as e:
        print(f'  HTTP {e.code}: {e.reason}')
        return False
    except Exception as e:
        print(f'  ERR: {e}')
        return False

ok = True
for name, url in FILES:
    if not download(url, os.path.join(DST, name)):
        ok = False

print('\n=== done ===')
print(f'dir: {DST}')
for n in os.listdir(DST):
    p = os.path.join(DST, n)
    print(f'  {n}: {os.path.getsize(p)/1024:.1f} KB')
