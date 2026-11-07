from __future__ import annotations

from enum import Enum


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"
    NA = "not_applicable"


ALL_STATUSES = tuple(s.value for s in Status)

STATUS_LABELS = {
    "pending": "待执行",
    "running": "执行中",
    "pass": "通过",
    "fail": "失败",
    "blocked": "阻塞",
    "not_run": "未测试",
    "not_applicable": "不适用",
}

SATISFIED = {Status.PASS.value, Status.NA.value}
TERMINAL = {Status.PASS.value, Status.FAIL.value, Status.BLOCKED.value, Status.NA.value}


class JobState(str, Enum):
    NEW = "new"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    VERIFIED = "verified"
    RELEASED = "released"


JOB_STATE_LABELS = {
    "new": "已接单",
    "running": "执行中",
    "blocked": "阻塞",
    "failed": "失败",
    "incomplete": "未完成",
    "verified": "已验证（未发布）",
    "released": "已发布",
}


def status_label(value: str) -> str:
    return STATUS_LABELS.get(value, value)


def job_state_label(value: str) -> str:
    return JOB_STATE_LABELS.get(value, value)


def count_by_status(results: list[dict]) -> dict[str, int]:
    """Count every status explicitly; never infer one status by subtraction."""
    counts = {s: 0 for s in ALL_STATUSES}
    for item in results:
        value = item["status"] if isinstance(item, dict) else item.status
        if value not in counts:
            raise ValueError(f"unknown status: {value!r}")
        counts[value] += 1
    return counts
