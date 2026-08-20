# Stage 1 · 圈 3（文档 01 的 01-C：BM25 分词缓存落 PG）记录

日期：2026-08-20 ｜ 分支：feature/stage-1-perf-startup

## 改动

- `backend/services/database.py`
  - `create_tables` 兼容迁移：`document_chunk` 新增 `tokenized TEXT` 列 + `SET COMPRESSION lz4`（PG<14 降级 warning，本机 PG 17.6 已生效 `attcompression='l'`）
  - 新增 `set_chunk_tokenized_batch(mapping)`（executemany 批量 UPDATE）与 `get_tokenized_by_ids(ids)`（一次 IN 查询，空串特判 `[]`，三态语义按设计 §3.2）
  - `add_document_chunk` 的 `ON CONFLICT DO UPDATE` 增加 `tokenized = NULL`（写路径自动置脏）
- `backend/services/bm25_client.py`
  - 新增 `_get_tokenized_batch(corpus)`：优先 PG 缓存 → 未命中批量 jieba 分词回写；埋审计事件 `bm25.cache.tokenize_batch`（detail: total/cache_hit/cache_miss/elapsed_ms）
  - `_get_or_build_model` 的逐条 jieba 循环替换为批量调用
  - **空白 token 可逆编码**（设计外发现，见下）：`_encode_tokens` / `_decode_tokens`，语料与查询统一用编码形态（读路径不解码，BM25 对 token 双射重命名不变 → 打分严格等价）

## 设计外的关键发现：jieba 纯空白 token

jieba `cut_for_search` 在中英混排间产出纯空白 token（`' '`、`'\n\t'` 等，实测 1408/1418 chunk 含有）：
1. TEXT 空格 join/split 对其有损 → 必须编码；
2. **不能过滤**：空白 token 是高频 token，进入 BM25 doc_freq/idf 统计（过滤后 top 结果从 5 条变 0 条，实测回归）；
3. **不能合并为单一哨兵**：不同空白串在旧实现中是不同 token，各有 idf（合并后 1038/1046 chunk 分数偏差）；
4. 解法：`'␣' + 码点hex`（如 `' '` → `␣20`）可逆编码，语料与查询两侧统一编码，全量分数逐项一致（np.allclose 通过）。

## 验证数据（work/stage-1/verify.log）

| 项 | 结果 |
|---|---|
| import app | PASS |
| 往返一致性（5 中英样本 + client 命中/未命中路径 + 空串三态 + upsert 置脏） | PASS |
| 严格打分等价：5 query × 1046 chunk 全量分数 vs 旧路径 | PASS（np.allclose） |
| 表体积 | tokenized 实存 1,192,260B / content 730,208B = **1.633 倍**（超出设计预期 0.8–1.2，见下）；表 2,473,984B → 4,423,680B（含代码类语料） |
| 建桶性能（1046 chunk 桶） | 冷（jieba 全量）1390ms vs 热（缓存）94ms ≈ **14.7x**；首次搜索 API 41ms |
| 关键词检索 API（重启后 `/api/elasticsearch/search`） | HTTP 200，无回归 |
| 审计 | `bm25.cache.tokenize_batch` 入队（脚本环境降级 audit_fallback.log，事件内容正确） |

### 存储比率 1.633 > 预期 0.8–1.2 的原因（如实记录）

1. 本库语料大量为**代码类文本**（C++/Markdown），token 较短且空白 token 极多（61k+ 个），可逆编码 `␣XX` 比原空白 token 膨胀 3 字节/个；
2. LZ4 TOAST 压缩对短行代码文本压缩率有限；
3. 设计 §7.2 的 0.8–1.2 假设基于自然语言语料。若需收敛，可改用 pglz（压缩率更高、解压略慢）或接受 1.6 倍（总量 +1.9MB/1418 chunk，绝对量可接受）。**此项按硬约束如实上报，未硬凑数字，待用户裁决。**

## 遗留/后续

- ES 客户端路径未涉及（SEARCH_BACKEND=bm25 默认）；
- 启动时 `load_from_database` 保持只读原文，建桶按需走缓存（设计 B/LRU 部分属后续圈）；
- 测试期间注册了 `test_circle3` 用户（无文档，可留可删）；
- requirements.txt 无需改动（LZ4 是 PG 侧能力，无 Python 依赖）。
