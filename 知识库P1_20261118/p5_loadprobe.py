# -*- coding: utf-8 -*-
import faulthandler, sys, time
faulthandler.dump_traceback_later(70, repeat=True, exit=False, file=sys.stderr)
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
import torch
print("cuda", torch.cuda.is_available(), flush=True)
from sentence_transformers import SentenceTransformer, CrossEncoder
t0 = time.time()
m = SentenceTransformer("BAAI/bge-m3", device="cuda",
                        revision="5617a9f61b028005a4858fdac845db406aefb181",
                        local_files_only=True, model_kwargs={"low_cpu_mem_usage": True})
print("embedder loaded", round(time.time() - t0, 2), flush=True)
t0 = time.time()
v = m.encode("测试热血足球", normalize_embeddings=True)
torch.cuda.synchronize()
print("encode OK", v.shape, round(time.time() - t0, 2), flush=True)
t0 = time.time()
r = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda",
                 revision="953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
                 max_length=1024, local_files_only=True,
                 model_kwargs={"low_cpu_mem_usage": True})
print("ranker loaded", round(time.time() - t0, 2), flush=True)
t0 = time.time()
s = r.predict([("测试", "热血足球必杀技")])
print("predict OK", s, round(time.time() - t0, 2), flush=True)