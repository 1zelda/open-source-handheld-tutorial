from __future__ import annotations

import html
import json
from pathlib import Path

from . import db, engine
from .models import ALL_STATUSES, STATUS_LABELS, job_state_label, status_label

CONCLUSION = {
    "new": "已接单，尚未执行。",
    "running": "任务正在执行。",
    "blocked": "任务被阻塞，不能当作成品交付。",
    "failed": "任务失败，需要修复后重跑。",
    "incomplete": "任务未完成，仍有阶段没有执行。",
    "verified": "必需闸门已通过，但配方没有发布阶段，不能称作正式发布。",
    "released": "所有必需闸门通过，发布闸门已放行。",
}


def _detail(row: dict) -> dict:
    try:
        value = json.loads(row.get("detail") or "{}")
        return value if isinstance(value, dict) else {"value": value}
    except json.JSONDecodeError:
        return {"raw": row.get("detail")}


def _human_size(size: int | None) -> str:
    if size is None:
        return "-"
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _next_actions(summary: dict) -> list[str]:
    actions = []
    for gate in summary["gates"]:
        if gate["status"] not in ("blocked", "fail"):
            continue
        detail = _detail(gate)
        reason = detail.get("reason") or detail.get("checks") or detail.get("counts") or ""
        actions.append(f"{gate['stage_id']} / {gate['gate_id']}：{reason}")
        if gate["stage_id"] == "preflight":
            if gate["gate_id"] == "device_family":
                actions.append("→ 更换与设备平台匹配的配方，或为该平台登记新的配方。")
            elif gate["gate_id"] == "device_capabilities":
                actions.append("→ 补充设备能力登记，或补齐该平台缺失的运行环境。")
            elif gate["gate_id"] == "input_present":
                actions.append("→ 重新登记游戏文件路径。")
    if any(row["status"] in ("pending", "not_run") for row in summary["stages"]):
        actions.append("→ 存在未执行阶段；修复上面的阻塞后重新运行。")
    if summary["job"]["status"] == "released":
        actions = ["→ 任务已放行；成品与验收记录见下方产物区。"]
    return actions


def build_markdown(summary: dict, events: list[dict] | None = None) -> str:
    job = summary["job"]
    game = summary["game"]
    device = summary["device"]
    lines = [
        f"# 移植任务报告 · {job['id']}",
        "",
        f"- 游戏：{game['name'] if game else '未登记'}"
        f"（{game['root_path'] if game else '-'}）",
        f"- 目标设备：{device['name'] if device else job['device_id']}"
        f"（{device['family'] if device else '-'}）",
        f"- 配方：{job['recipe_id']}",
        f"- 接入路径：{job['input_path']}",
        f"- 任务状态：**{job_state_label(job['status'])}**（`{job['status']}`）",
        f"- 执行时间：{job['created_at']} → {job['updated_at']}（UTC）",
        "",
        "## 结论",
        "",
        CONCLUSION.get(job["status"], job["status"]),
        "",
    ]
    actions = _next_actions(summary)
    if actions:
        lines += ["### 下一步", ""] + [f"- {a}" for a in actions] + [""]

    lines += ["## 闸门计数（逐项计数，不以未命中倒推）", ""]
    for key, counts in (("全部闸门", summary["counts_all"]),
                        ("必需闸门", summary["counts_required"])):
        parts = [f"{STATUS_LABELS[s]} {counts[s]}" for s in ALL_STATUSES]
        lines.append(f"- {key}：" + " / ".join(parts))
    lines.append("")

    lines += ["## 阶段", "", "| 顺序 | 阶段 | 状态 | 开始（UTC） | 结束（UTC） |",
              "|---|---|---|---|---|"]
    for row in summary["stages"]:
        lines.append(
            f"| {row['order_no']} | {row['stage_id']} | {status_label(row['status'])} | "
            f"{row['started_at'] or '-'} | {row['finished_at'] or '-'} |")
    lines.append("")

    stage_order = [("preflight", 0)] + [(r["stage_id"], r["order_no"]) for r in summary["stages"]]
    grouped: dict[str, list[dict]] = {}
    for gate in summary["gates"]:
        grouped.setdefault(gate["stage_id"], []).append(gate)
    lines += ["## 闸门明细", ""]
    for stage_id, _ in stage_order:
        rows = grouped.get(stage_id, [])
        if not rows:
            continue
        lines += [f"### {stage_id}", "",
                  "| 闸门 | 必需 | 状态 | 证据 | 说明 |", "|---|---|---|---|---|"]
        for gate in rows:
            detail = _detail(gate)
            reason = detail.get("reason") or detail.get("checks") or ""
            if not reason and detail.get("sha256"):
                reason = f"sha256={detail['sha256']}"
            if not reason and detail.get("counts"):
                reason = json.dumps(detail["counts"], ensure_ascii=False)
            if not reason and detail.get("file_count"):
                reason = (f"{detail['file_count']} 个文件 / "
                          f"包 sha256={str(detail.get('package_sha256', ''))[:16]}…")
            evidence = Path(gate["evidence_path"]).name if gate["evidence_path"] else "-"
            lines.append(
                f"| {gate['gate_id']} | {'是' if gate['required'] else '否'} | "
                f"{status_label(gate['status'])} | {evidence} | {str(reason)[:160]} |")
        lines.append("")

    lines += ["## 产物", ""]
    if summary["artifacts"]:
        lines += ["| 文件 | 类型 | 大小 | SHA256 |", "|---|---|---|---|"]
        for art in summary["artifacts"]:
            lines.append(f"| {Path(art['path']).name} | {art['kind']} | "
                         f"{_human_size(art['size'])} | `{art['sha256']}` |")
    else:
        lines.append("尚无产物。")
    lines.append("")

    if events:
        lines += ["## 最近事件", ""]
        for item in events:
            lines.append(f"- {item['ts']} · {item['kind']} · {item['message']}")
        lines.append("")

    lines += [
        "## 口径",
        "",
        "- “未测试”不等于“通过”；没有真机证据时不能称成品。",
        "- 只有全部必需闸门为通过（或不适用且写明理由）时，发布闸门才会放行。",
        "- 本报告由闸门实际结果生成，不包含人工宣称的通过。",
        "",
    ]
    return "\n".join(lines)


def write_report(factory, job_id: str) -> Path:
    with factory.connect() as conn:
        summary = engine.job_summary(conn, job_id)
        events = db.job_events(conn, job_id, limit=12)
    path = Path(summary["job"]["workdir"]) / "report.md"
    path.write_text(build_markdown(summary, events), encoding="utf-8")
    return path


def render_job_html(summary: dict) -> str:
    job = summary["job"]
    game = summary["game"]
    esc = html.escape
    counts = summary["counts_all"]
    count_line = " / ".join(f"{STATUS_LABELS[s]} {counts[s]}" for s in ALL_STATUSES)
    stage_rows = "".join(
        f"<tr><td>{r['order_no']}</td><td>{esc(r['stage_id'])}</td>"
        f"<td class='s-{r['status']}'>{esc(status_label(r['status']))}</td></tr>"
        for r in summary["stages"])
    gate_rows = "".join(
        f"<tr><td>{esc(g['stage_id'])}</td><td>{esc(g['gate_id'])}</td>"
        f"<td>{'是' if g['required'] else '否'}</td>"
        f"<td class='s-{g['status']}'>{esc(status_label(g['status']))}</td>"
        f"<td>{esc(str(_detail(g).get('reason', ''))[:120])}</td></tr>"
        for g in summary["gates"])
    artifact_rows = "".join(
        f"<tr><td>{esc(Path(a['path']).name)}</td><td>{_human_size(a['size'])}</td>"
        f"<td><code>{esc(a['sha256'])}</code></td></tr>"
        for a in summary["artifacts"]) or "<tr><td colspan='3'>尚无产物</td></tr>"
    return f"""<!doctype html><meta charset="utf-8">
<title>{esc(job['id'])}</title>
<style>
body{{font:14px/1.5 system-ui,Segoe UI,Microsoft YaHei;margin:32px;max-width:1100px}}
h1{{font-size:20px}} table{{border-collapse:collapse;width:100%;margin:12px 0}}
td,th{{border:1px solid #d8dee9;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f3f5f8}} code{{font-size:12px;word-break:break-all}}
.s-pass{{color:#176b3a;font-weight:600}} .s-fail{{color:#a11919;font-weight:600}}
.s-blocked{{color:#8a5a00;font-weight:600}} .s-not_run,.s-pending{{color:#666}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;background:#eef1f5}}
</style>
<h1>移植任务 {esc(job['id'])} <span class="badge">{esc(job_state_label(job['status']))}</span></h1>
<p>游戏：{esc(game['name'] if game else '未登记')}　设备：{esc(summary['device']['name'] if summary['device'] else job['device_id'])}　配方：{esc(job['recipe_id'])}</p>
<p>{esc(CONCLUSION.get(job['status'], ''))}</p>
<p>{esc(count_line)}</p>
<h2>阶段</h2><table><tr><th>#</th><th>阶段</th><th>状态</th></tr>{stage_rows}</table>
<h2>闸门</h2><table><tr><th>阶段</th><th>闸门</th><th>必需</th><th>状态</th><th>说明</th></tr>{gate_rows}</table>
<h2>产物</h2><table><tr><th>文件</th><th>大小</th><th>SHA256</th></tr>{artifact_rows}</table>
<p style="color:#555">未测试不等于通过；真机没有证据时不得称成品。</p>
"""
