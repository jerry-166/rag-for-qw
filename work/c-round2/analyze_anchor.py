"""分析锚点提取质量：LLM 提取的实体名 vs PG entity 表的匹配率"""
import os, sys, json, requests, psycopg2
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
os.chdir(os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

B = 'http://localhost:8003'
THIS = os.path.dirname(os.path.abspath(__file__))

# 不需要 backend login，直接调智谱 API + PG

# 加载 testset
with open(os.path.join(THIS, '..', '..', 'backend', 'evaluation', 'testsets', 'crud_rag_300.json'), encoding='utf-8') as f:
    ts = json.load(f)
samples = ts.get('samples', [])[:20]  # 取 20 个

PG_DSN = 'host=localhost port=5432 dbname=rag_system user=postgres password=1234'

# 查 PG entity 表里有哪些 entity name
def get_all_entity_names(kb_id=65):
    c = psycopg2.connect(PG_DSN)
    cur = c.cursor()
    cur.execute("SELECT name FROM entity WHERE kb_id=%s", (kb_id,))
    names = set(r[0] for r in cur.fetchall())
    cur.close(); c.close()
    return names

pg_names = get_all_entity_names()
print(f'PG entity names: {len(pg_names)} 个')

# 手动调 LLM 提取锚点（复用 _ANCHOR_EXTRACT_TEMPLATE）
import openai
from services.enhancers.entity import ENTITY_TEMPLATE

ZHIPU_KEY = os.getenv('ZHIPU_API_KEY', '')
LLM_BASE = 'https://open.bigmodel.cn/api/paas/v4/'
LLM_MODEL = 'glm-4-flash-250414'

ANCHOR_TEMPLATE = (
    "从下面问题中提取出作为检索锚点的实体（人物/组织/概念/技术/产品等）。\n"
    "每个实体给一句话客观描述，不超过30字，不要发挥，只描述实体本身的客观属性。\n"
    "实体数量控制在1~5个，宁缺毋滥；若问题无明确实体，返回空数组。\n"
    "请严格按照以下JSON格式返回结果：\n"
    '{{"entities":[{{"name":"实体名","type":"类型","description":"一句话描述"}}]}}\n'
    "问题：{query}"
)

client = openai.OpenAI(api_key=ZHIPU_KEY, base_url=LLM_BASE)

def extract_anchors(query):
    prompt = ANCHOR_TEMPLATE.format(query=query)
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL, messages=[{'role':'user','content':prompt}],
            temperature=0, max_tokens=300)
        raw = resp.choices[0].message.content.strip()
        # 清理 markdown
        if raw.startswith('```'):
            raw = raw.split('\n',1)[1].rsplit('```',1)[0].strip()
        parsed = json.loads(raw)
        return [e.get('name','') for e in parsed.get('entities',[]) if e.get('name')]
    except Exception as e:
        return []

# 测 20 个 query
print(f'\n{"query":<50} {"LLM anchors":>30} {"PG match":>10}')
print('-' * 95)

total_anchors = 0
total_matched = 0

for s in samples:
    q = s['question'][:48]
    anchors = extract_anchors(s['question'])
    
    # 检查哪些 anchor 在 PG 里有
    matched = [a for a in anchors if a in pg_names]
    unmatched = [a for a in anchors if a not in pg_names]
    
    total_anchors += len(anchors)
    total_matched += len(matched)
    
    match_str = f'{len(matched)}/{len(anchors)}' if anchors else '0/0'
    anchor_str = ', '.join(anchors[:3])[:28]
    unmatch_str = f' (miss: {", ".join(unmatched[:2])})' if unmatched else ''
    
    print(f'{q:<50} {anchor_str:>30} {match_str:>10}{unmatch_str}')

print(f'\n汇总: LLM 提取 {total_anchors} 个锚点, PG 匹配 {total_matched} 个, 匹配率 {total_matched/total_anchors*100:.1f}%')
