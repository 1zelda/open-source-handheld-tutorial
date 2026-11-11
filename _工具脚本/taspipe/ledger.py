# -*- coding: utf-8 -*-
"""M8：台账（Ledger）—— 依赖/复用/重试/失败分类/续跑 的元数据层。

落实方案 §4.4 台账规则：
  * 登记只记元数据，不顺手触发下载或编码（register 不跑任何生产）；
  * 成功必须对应实际存在、可校验的产物（complete 校验 uri 存在 + sha256 匹配）；
  * 新尝试保留旧证据，不覆盖失败历史（entries 追加式，fail 后重跑是新 attempt）；
  * 复用按阶段计算指纹（reusable 比对 fingerprint + 产物校验 + verdict!=fail）；
  * 已通过条目直接计数（summary 逐条数 done，不用总数减失败倒推）。
"""
import json
import os
import time

from .schema import (SCHEMA_VERSION, Stage, JobStatus, FailureCode, Verdict,
                     sha256_file, asset, _enum)


def fingerprint(files=(), params=None):
    """阶段指纹 = 输入文件内容哈希 + 规范化参数。输入或参数变 => 指纹变 => 不复用。"""
    import hashlib
    h = hashlib.sha256()
    for p in sorted(str(x) for x in files):
        h.update(os.path.basename(p).encode())
        h.update(sha256_file(p).encode())
    h.update(json.dumps(params or {}, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def _verify_artifacts(refs):
    """产物必须实际存在且 sha256/大小与登记一致；任一不符 => 不可复用。"""
    for r in refs or []:
        uri = r.get("uri", "")
        path = uri.replace("/", os.sep) if os.sep != "/" else uri
        if not os.path.isfile(uri) and not os.path.isfile(path):
            return False, f"产物缺失: {uri}"
        real = uri if os.path.isfile(uri) else path
        if sha256_file(real) != r.get("sha256"):
            return False, f"产物指纹不符: {uri}"
        if os.path.getsize(real) != r.get("byte_size"):
            return False, f"产物大小不符: {uri}"
    return True, ""


class Ledger:
    def __init__(self, path):
        self.path = str(path)
        self.entries = []
        if os.path.isfile(self.path):
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.entries = d.get("entries", [])

    def _save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"schema_version": SCHEMA_VERSION, "entries": self.entries},
                      f, ensure_ascii=False, indent=1)

    def _latest(self, stage, key):
        stage = _enum(stage, Stage, "ledger.stage").value
        for e in reversed(self.entries):
            if e["stage"] == stage and e["idempotency_key"] == key:
                return e
        return None

    def attempt_no(self, stage, key):
        e = self._latest(stage, key)
        return (e["attempt"] + 1) if e else 1

    def register(self, stage, key, fp, deps=()):
        """只登记元数据（pending），不触发任何生产。返回 job_id。"""
        stage = _enum(stage, Stage, "ledger.stage").value
        n = self.attempt_no(stage, key)
        job_id = f"{stage}:{key}:a{n}"
        self.entries.append({
            "job_id": job_id, "stage": stage, "idempotency_key": key,
            "fingerprint": fp, "attempt": n, "status": JobStatus.PENDING.value,
            "dependency_ids": list(deps), "artifact_refs": [],
            "verification_verdict": None, "failure_code": None,
            "ts": time.time(),
        })
        self._save()
        return job_id

    def _entry(self, job_id):
        for e in self.entries:
            if e["job_id"] == job_id:
                return e
        raise KeyError(job_id)

    def complete(self, job_id, artifacts, verdict):
        """标记 done 前校验产物真实存在且指纹一致；verdict 如实记录（inconclusive 不算 fail）。"""
        e = self._entry(job_id)
        refs = []
        for a in artifacts:
            if isinstance(a, dict):
                refs.append(a)
            elif os.path.isfile(str(a)):
                refs.append(asset(str(a)))
            else:   # 缺失产物：登记一个校验必拒的引用，交给 _verify_artifacts 判 fail
                refs.append({"uri": str(a).replace("\\", "/"), "sha256": None, "byte_size": None})
        ok, why = _verify_artifacts(refs)
        if not ok:
            return self.fail(job_id, FailureCode.SCHEMA_INVALID, why)
        e.update(status=JobStatus.DONE.value, artifact_refs=refs,
                 verification_verdict=_enum(verdict, Verdict, "ledger.verdict").value,
                 done_ts=time.time())
        self._save()
        return job_id

    def fail(self, job_id, code, reason=""):
        """保留失败现场：只改本 attempt 状态，历史 entries 不动。"""
        e = self._entry(job_id)
        e.update(status=JobStatus.FAILED.value,
                 failure_code=_enum(code, FailureCode, "ledger.failure_code").value,
                 reason=reason, failed_ts=time.time())
        self._save()
        return job_id

    def reusable(self, stage, key, fp):
        """可复用 = 最新 attempt 为 done + 指纹一致 + 产物校验通过 + verdict!=fail。"""
        e = self._latest(stage, key)
        if not e or e["status"] != JobStatus.DONE.value:
            return None
        if e["fingerprint"] != fp:
            return None
        if e.get("verification_verdict") == Verdict.FAIL.value:
            return None
        ok, _ = _verify_artifacts(e["artifact_refs"])
        return e if ok else None

    def summary(self):
        """逐条直接计数最新 attempt 的状态（不用总数减失败倒推）。"""
        latest = {}
        for e in self.entries:
            latest[(e["stage"], e["idempotency_key"])] = e
        counts = {s.value: 0 for s in JobStatus}
        for e in latest.values():
            counts[e["status"]] += 1
        return {"stages": len(latest), "attempts": len(self.entries), **counts}