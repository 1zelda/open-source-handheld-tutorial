"""接单：把 `port route` 的判定直接接到 spec 草稿上。

只有能被重建的源码工程（B-source / B-recomp）才生成草稿；数据、二进制、制品、模拟器、
压缩包等路线一律如实拒收，不造一份填了也跑不动的假 spec。生成的草稿仍是待填状态，
不构成任何可构建、可玩或可发布的承诺。
"""
from __future__ import annotations

from pathlib import Path

from . import cache, draft as draft_mod, route, spec

AUTO_ROUTES = {"B-source": "source-port", "B-recomp": "recomp"}


class OnboardError(ValueError):
    pass


def _refuse(decision: dict, extra: list[str]) -> dict:
    reasons = extra + list(decision["blockers"])
    if not reasons:
        reasons = ["没有识别出可重建的源码工程。"]
    return {
        "refused": True,
        "route": decision["route"],
        "title": decision["title"],
        "confidence": decision["confidence"],
        "reasons": reasons,
        "cautions": decision["cautions"],
        "next_steps": decision["next_steps"],
        "created": {},
        "warnings": [],
        "decision": decision,
    }


def create(path: str | Path, spec_id: str, title: str | None = None,
           out_dir: str | Path = "specs", force: bool = False) -> dict:
    spec.check_id(spec_id)
    decision = route.scan(path)
    route_id = decision["route"]

    if route_id not in AUTO_ROUTES:
        return _refuse(decision, [
            f"路线 {route_id} 不是可重建的源码工程，port new 不会为它生成 spec。"])
    if decision["scanned"]["kind"] != "dir":
        return _refuse(decision, ["port new 需要源码目录；单个源文件不是可构建工程。"])

    root = Path(decision["scanned"]["path"])
    out = Path(out_dir)
    spec_out = out / f"{spec_id}.draft.json"
    decision_out = out / f"{spec_id}.route.json"
    filled = (out / f"{spec_id}.json").as_posix()
    if not force:
        for existing in (spec_out, decision_out):
            if existing.exists():
                raise OnboardError(f"已存在 {existing.resolve()}；确认覆盖请加 --force")

    out.mkdir(parents=True, exist_ok=True)
    decision_out.write_text(route.to_json(decision), encoding="utf-8")
    draft_spec = draft_mod.draft(root, spec_id, title, family=AUTO_ROUTES[route_id])
    draft_spec["_draft"]["route"] = {
        "id": route_id,
        "confidence": decision["confidence"],
        "decision": str(decision_out.resolve()),
        "decision_sha256": cache.stamp(decision_out)["sha256"],
    }
    draft_mod.write(draft_spec, spec_out)

    return {
        "refused": False,
        "route": route_id,
        "title": decision["title"],
        "confidence": decision["confidence"],
        "reasons": [],
        "cautions": decision["cautions"],
        "created": {"spec": str(spec_out.resolve()),
                    "decision": str(decision_out.resolve())},
        "warnings": list(draft_spec["_draft"]["warnings"]) + decision["cautions"],
        "next_steps": [
            f"填 `{spec_out.as_posix()}` 里的 TODO（commit、构建参数、数据政策、打包信息），"
            f"删掉 `_draft` 后另存为 `{filled}`",
            f"py -3 工厂.py port plan {filled} --target handheld",
            f"py -3 工厂.py port build {filled} --target handheld --work F:/_scratch/portkit",
            f"py -3 工厂.py port status {filled} --target handheld --work F:/_scratch/portkit",
        ],
        "decision": decision,
    }


def render(result: dict) -> str:
    decision = result["decision"]
    scanned = decision["scanned"]
    lines = [f"# 接单：{result['route']} {result['title']}", "",
             f"- 输入：`{scanned['path']}`（{scanned['files']} 个文件）",
             f"- 置信度：{decision['confidence']}", ""]
    if result["refused"]:
        lines += ["**未生成 spec。**", "", "原因："]
        lines += [f"- {item}" for item in result["reasons"]]
        if result["cautions"]:
            lines += ["", "补充："]
            lines += [f"- {item}" for item in result["cautions"]]
    else:
        lines += [f"- 草稿：`{result['created']['spec']}`",
                  f"- 路线判定：`{result['created']['decision']}`（哈希已写进草稿）", "",
                  "待处理："]
        lines += [f"- {item}" for item in result["warnings"]]
    lines += ["", "下一步："]
    for index, step in enumerate(result["next_steps"], 1):
        shown = f"`{step}`" if step.startswith("py -3 ") else step
        lines.append(f"{index}. {shown}")
    lines.append("")
    if result["refused"]:
        lines.append("本次没接：这条路需要先解决上面的阻断。判定可以单独复查："
                     "`py -3 工厂.py port route <同一路径>`。")
    else:
        lines.append("草稿只表示“看起来可以按这条路走”，不代表能编译、能玩或能发布。")
    lines.append("")
    return "\n".join(lines)
