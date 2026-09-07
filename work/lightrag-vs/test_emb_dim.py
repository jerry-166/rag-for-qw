"""测 langchain OpenAIEmbeddings + check_embedding_ctx_length=False（DashScope 兼容）。"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from langchain_openai import OpenAIEmbeddings
key = os.getenv('DASHSCOPE_API_KEY')

print('=== dimensions=1536 + check_embedding_ctx_length=False ===')
try:
    e = OpenAIEmbeddings(model='text-embedding-v4', api_key=key,
        base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        dimensions=1536, check_embedding_ctx_length=False)
    v = e.embed_query('测试向量数据库')
    print('embed_query OK, len:', len(v))
except Exception as ex:
    print('embed_query ERR:', str(ex)[:280])
    sys.exit(1)

print('\n=== embed_documents 批量 ===')
try:
    vs = e.embed_documents(['测试一', '测试二'])
    print('OK, count:', len(vs), 'len:', len(vs[0]))
except Exception as ex:
    print('ERR:', str(ex)[:280])
