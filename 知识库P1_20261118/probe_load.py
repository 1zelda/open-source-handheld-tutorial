# -*- coding: utf-8 -*-
import time, sys
t0 = time.time()
def mark(s):
    print(f"[{time.time()-t0:6.1f}s] {s}", flush=True)
mark("start")
import torch
mark(f"torch {torch.__version__}")
mark(f"cuda_available={torch.cuda.is_available()}")
import transformers
mark(f"transformers {transformers.__version__}")
import sentence_transformers
mark(f"sentence_transformers {sentence_transformers.__version__}")
from sentence_transformers import SentenceTransformer
mark("SentenceTransformer class imported")
m = SentenceTransformer("BAAI/bge-m3", device="cuda",
                        revision="5617a9f61b028005a4858fdac845db406aefb181",
                        local_files_only=True)
mark("model loaded")
v = m.encode(["测试"], normalize_embeddings=True)
mark(f"encode ok shape={v.shape}")