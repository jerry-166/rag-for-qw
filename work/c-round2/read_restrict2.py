"""读 model-speed-restrict 文件，显示模型名 + 并发数"""
raw = open(r'd:\workspace\rag-for-qw\others\model-speed-restrict', 'rb').read()
txt = raw.decode('utf-8', errors='replace')
lines = txt.splitlines()

# 找模型名行 + 下一行是数字
keywords = ['GLM-4-FlashX-250414', 'GLM-4.7-Flash', 'GLM-4.5-Flash',
            'GLM-4-Flash-250414', 'GLM-4-FlashX', 'GLM-4-Flash',
            'GLM-4-Air', 'GLM-4-AirX', 'GLM-4-Air-250414',
            'GLM-4.7-FlashX']

for i, line in enumerate(lines):
    line = line.strip()
    for kw in keywords:
        if kw == line or (kw in line and len(line) < 40):
            # 下一行是数字
            next_line = lines[i+1].strip() if i+1 < len(lines) else '?'
            print(f'{line:30s} → 并发限制: {next_line}')
            break
