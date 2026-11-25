# -*- coding: utf-8 -*-
"""P1 新状态码契约。

生产 kb.py 现有状态：pass / inconclusive / miss / not_built。
P1 拆分两个"拒答"语义，供生产接线时映射（接线本身延后，待与并发会话协调）：

  not_found_within_scope  问题被路由到明确域，但该域在库内零语料
                          （如 LOL/DOTA/原神）。结构性缺料，不是检索失败。
                          → 生产映射 miss（reason 注明域外零语料）
  insufficient_evidence   域内有语料、检索有命中，但逐事实可答性核查全不过
                          （词命中≠回答问题，如 Q09 视频指纹规则冒充 ROM SHA1）。
                          → 生产映射 inconclusive（reason 注明可答性全否）

两者都绝不 pass。hits 保留并附可答性标注，供人工复核。
"""
PASS = "pass"
INCONCLUSIVE = "inconclusive"
MISS = "miss"
NOT_FOUND = "not_found_within_scope"
INSUFFICIENT = "insufficient_evidence"

PROD_MAP = {NOT_FOUND: MISS, INSUFFICIENT: INCONCLUSIVE}
REFUSE_OK = {MISS, INCONCLUSIVE, NOT_FOUND, INSUFFICIENT}