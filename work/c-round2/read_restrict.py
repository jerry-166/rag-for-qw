"""读 model-speed-restrict 文件，过滤免费模型速率限制"""
raw = open(r'd:\workspace\rag-for-qw\others\model-speed-restrict', 'rb').read()
for enc in ['utf-8', 'gbk', 'utf-16']:
    try:
        txt = raw.decode(enc)
        print(f'=== decoded with {enc} ===')
        for line in txt.splitlines():
            line = line.strip()
            if not line:
                continue
            # 过滤用户列的免费模型
            keywords = ['GLM-4-FlashX-250414', 'GLM-4.7-Flash', 'GLM-4.5-Flash',
                        'GLM-4-Flash-250414', 'GLM-4-FlashX', 'GLM-4-Flash',
                        'GLM-4-Air', 'GLM-4-AirX', 'GLM-4-Air-250414',
                        'GLM-4.7-FlashX', 'qwen']
            for kw in keywords:
                if kw in line:
                    print(f'  {line}')
                    break
        break
    except Exception:
        continue
