from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import db, engine, intake, recipes
from .factory import Factory
from .models import ALL_STATUSES, STATUS_LABELS, job_state_label, status_label
from .report import write_report
from .server import serve


def _factory(args) -> Factory:
    factory = Factory.discover(args.root)
    factory.init()
    return factory


def _counts_line(counts: dict) -> str:
    return " / ".join(f"{STATUS_LABELS[s]} {counts[s]}" for s in ALL_STATUSES)


def _cmd_init(args) -> int:
    factory = _factory(args)
    print(f"已初始化：{factory.root}")
    print(f"数据库：{factory.db_path}")
    return 0


def _cmd_device_add(args) -> int:
    factory = _factory(args)
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    for key in ("id", "name", "family"):
        if not data.get(key):
            raise SystemExit(f"设备档案缺少字段 {key}")
    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise SystemExit("capabilities 必须是列表")
    with factory.connect() as conn:
        conn.execute(
            "INSERT INTO devices(id, name, family, os, arch, capabilities, verified, notes, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, family=excluded.family, "
            "os=excluded.os, arch=excluded.arch, capabilities=excluded.capabilities, "
            "verified=excluded.verified, notes=excluded.notes",
            (data["id"], data["name"], data["family"], data.get("os"), data.get("arch"),
             db.dump_json(capabilities), 1 if data.get("verified") else 0,
             data.get("notes", ""), db.now()),
        )
        db.event(conn, None, "device.add", f"登记设备 {data['name']} ({data['family']})")
    print(f"设备已登记：{data['id']} / {data['name']} / {data['family']}")
    return 0


def _cmd_device_list(args) -> int:
    factory = _factory(args)
    with factory.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM devices ORDER BY id")]
    if not rows:
        print("还没有设备档案。")
        return 0
    print(f"{'编号':<22} {'名称':<22} {'平台族':<20} {'架构':<10} 已接线验证")
    for row in rows:
        print(f"{row['id']:<22} {row['name']:<22} {row['family']:<20} "
              f"{row['arch'] or '-':<10} {'是' if row['verified'] else '否'}")
    return 0


def _cmd_intake(args) -> int:
    factory = _factory(args)
    record = intake.record_game(factory, args.path, args.name, args.hash)
    print(intake.format_summary(record))
    print()
    print(f"登记编号：{record['id']}（后续用 --game {record['id']} 接单）")
    return 0


def _cmd_recipe_list(args) -> int:
    factory = _factory(args)
    found = recipes.discover(factory)
    if not found:
        print("还没有配方。")
        return 0
    for recipe in found.values():
        stages = " → ".join(stage["id"] for stage in recipe["stages"])
        print(f"{recipe['id']:<36} {recipe['title']}")
        print(f"  平台族：{', '.join(recipe['device_families'])}")
        print(f"  阶段：{stages}")
    return 0


def _cmd_job_new(args) -> int:
    factory = _factory(args)
    created = engine.create_job(factory, args.game, args.device, args.recipe, args.input)
    print(f"任务已创建：{created['id']}")
    print(f"接入路径：{created['input_path']}")
    print(f"下一步：py -3 -m portfactory job run {created['id']}")
    return 0


def _cmd_job_run(args) -> int:
    factory = _factory(args)
    result = engine.run_job(factory, args.job, args.from_stage)
    with factory.connect() as conn:
        summary = engine.job_summary(conn, args.job)
    report_path = write_report(factory, args.job)
    print(f"任务 {args.job} → {job_state_label(summary['job']['status'])}")
    print(f"闸门：{_counts_line(summary['counts_all'])}")
    print(f"必需：{_counts_line(summary['counts_required'])}")
    for stage in summary["stages"]:
        print(f"  {stage['order_no']}. {stage['stage_id']:<18} {status_label(stage['status'])}")
    print(f"报告：{report_path}")
    return 0 if summary["job"]["status"] in ("released", "verified") else 2


def _cmd_job_status(args) -> int:
    factory = _factory(args)
    with factory.connect() as conn:
        summary = engine.job_summary(conn, args.job)
        events = db.job_events(conn, args.job, limit=8)
    job = summary["job"]
    print(f"任务：{job['id']}")
    print(f"游戏：{summary['game']['name'] if summary['game'] else '-'}")
    print(f"设备：{summary['device']['name'] if summary['device'] else job['device_id']}")
    print(f"状态：{job_state_label(job['status'])}（{job['status']}）")
    print(f"闸门：{_counts_line(summary['counts_all'])}")
    print(f"必需：{_counts_line(summary['counts_required'])}")
    print("阶段：")
    for stage in summary["stages"]:
        print(f"  {stage['order_no']}. {stage['stage_id']:<18} {status_label(stage['status'])}")
    blocked = [g for g in summary["gates"] if g["status"] in ("blocked", "fail")]
    if blocked:
        print("需要处理：")
        for gate in blocked:
            try:
                detail = json.loads(gate["detail"] or "{}")
            except json.JSONDecodeError:
                detail = {}
            print(f"  - {gate['stage_id']} / {gate['gate_id']}: "
                  f"{detail.get('reason', gate['status'])}")
    if summary["artifacts"]:
        print("产物：")
        for art in summary["artifacts"]:
            print(f"  - {art['path']}  {art['size']} B  sha256={art['sha256']}")
    if events:
        print("最近事件：")
        for item in events:
            print(f"  {item['ts']}  {item['kind']}  {item['message']}")
    return 0


def _cmd_job_report(args) -> int:
    factory = _factory(args)
    path = write_report(factory, args.job)
    print(path)
    return 0


def _cmd_job_attest_template(args) -> int:
    factory = _factory(args)
    with factory.connect() as conn:
        job = db.get_job(conn, args.job)
    if job is None:
        raise SystemExit(f"任务不存在：{args.job}")
    recipe = recipes.load(factory, job["recipe_id"])
    checks = []
    for stage in recipe["stages"]:
        for gate in stage.get("gates", []):
            if gate["type"] == "manual_attestation":
                for cid in gate.get("required_checks", []):
                    checks.append({"id": cid, "result": "", "evidence": f"{cid}.jpg"})
    evidence_dir = Path(job["workdir"]) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    template = {
        "job_id": args.job,
        "tester": "",
        "device": "",
        "date": "",
        "checks": checks or [{"id": "example", "result": "", "evidence": "example.jpg"}],
    }
    path = evidence_dir / "device_test.template.json"
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"验收模板：{path}")
    print("把证据文件放进同目录，填好 tester/device/date 后执行 job attest。")
    return 0


def _copy_evidence(source: Path, base: Path, target_dir: Path) -> str:
    source = source.resolve()
    if not source.is_file():
        raise SystemExit(f"证据文件不存在：{source}")
    try:
        rel = source.relative_to(base.resolve())
    except ValueError:
        raise SystemExit(f"证据文件必须在验收记录同目录内：{source}")
    if ".." in rel.parts:
        raise SystemExit(f"证据路径越界：{rel}")
    target = target_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if source != target.resolve():
        shutil.copy2(source, target)
    return str(rel).replace("\\", "/")


def _cmd_job_attest(args) -> int:
    factory = _factory(args)
    with factory.connect() as conn:
        job = db.get_job(conn, args.job)
    if job is None:
        raise SystemExit(f"任务不存在：{args.job}")
    source = Path(args.file).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("job_id") != args.job:
        raise SystemExit("验收记录的 job_id 与任务不一致")
    evidence_dir = Path(job["workdir"]) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for check in data.get("checks", []):
        rel = check.get("evidence")
        if rel:
            _copy_evidence(source.parent / rel, source.parent, evidence_dir)
    target = evidence_dir / "device_test.json"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    with factory.connect() as conn:
        db.event(conn, args.job, "evidence.attested", f"真机验收记录：{target}")
    print(f"验收记录已接入：{target}")
    if args.run:
        return _cmd_job_run(argparse.Namespace(root=args.root, job=args.job,
                                               from_stage=None))
    print(f"下一步：py -3 -m portfactory job run {args.job}")
    return 0


def _cmd_serve(args) -> int:
    factory = _factory(args)
    serve(factory, args.host, args.port)
    return 0


def _cmd_research(args) -> int:
    from . import research
    factory = _factory(args)
    try:
        action = args.research_command
        if action == "new":
            run = research.create_run(factory, Path(args.path), args.target, Path(args.work_root),
                                      args.max_requests, args.max_context_bytes, args.max_seconds,
                                      args.max_attempts, args.max_modules)
            result = research.status(factory, run["id"])
        elif action == "analyze":
            result = research.analyze(factory, args.run_id)
        elif action == "work":
            if args.provider == "local" and (not args.endpoint or not args.model):
                raise research.ResearchError("local 模式必须指定 --endpoint 和 --model；只接受本机 IP 地址")
            result = research.work(factory, args.run_id, Path(args.compiler), args.provider, args.endpoint, args.model)
            if args.provider == "local":
                while result["run"]["status"] not in ("budget_exhausted", "provider_failed", "failed", "blocked", "module_batch_verified", "needs_research"):
                    result = research.work(factory, args.run_id, Path(args.compiler), args.provider, args.endpoint, args.model)
        elif action == "submit":
            result = research.submit(factory, args.run_id, Path(args.response))
        elif action == "report":
            print(research.report(factory, args.run_id))
            return 0
        else:
            result = research.status(factory, args.run_id)
        run = result["run"]
        print(f"研发任务：{run['id']} → {run['status']} / 目标 {run['target']}")
        print("模块状态：" + " / ".join(f"{key}={value}" for key, value in result["counts"].items()))
        budget = result["budget"]
        print(f"预算：请求 {budget['requests_charged']}/{budget['requests_limit']}；"
              f"上下文字节预留 {budget['context_bytes_reserved']}/{budget['context_bytes_limit']}；"
              f"worker 活跃秒 {budget['active_seconds']:.2f}/{budget['active_seconds_limit']}")
        for request in result["requests"]:
            if request["status"] == "waiting_ai":
                print(f"AI 待办：{request['request_path']}")
                print(f"请求 SHA256：{request['request_sha256']}")
        print("仅函数级研发；完整游戏行为与真机测试均未执行，不发布游戏成品。")
        print(f"报告：{research.report(factory, run['id'])}")
        return 2 if run["status"] in ("failed", "blocked", "provider_failed", "budget_exhausted", "needs_research") else 0
    except (research.ResearchError, OSError, ValueError) as exc:
        print(f"研发停止：{exc}", file=sys.stderr)
        return 2


def _cmd_port(args) -> int:
    from .handoff import HandoffError
    from .portkit import RunError, SpecError
    try:
        return _run_port(args)
    except (HandoffError, RunError, SpecError, OSError, ValueError) as exc:
        print(f"移植任务停止：{exc}", file=sys.stderr)
        return 2


def _run_port(args) -> int:
    from . import handoff, portkit
    from .portkit import draft as draft_mod

    action = args.port_command
    if action == "new":
        from .portkit import onboard
        result = onboard.create(args.path, args.id, args.title, Path(args.out_dir),
                                force=args.force)
        print(onboard.render(result))
        return 2 if result["refused"] else 0
    if action == "route":
        from .portkit import route
        result = route.scan(args.path)
        payload = route.to_json(result)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload, encoding="utf-8")
        if args.json:
            print(payload, end="")
        else:
            print(route.render(result))
            if args.out:
                print(f"判定记录：{Path(args.out).resolve()}")
        return 0 if result["route"] != "unrouted" else 2
    if action == "handoff":
        manifest = handoff.create(Path(args.project), Path(args.spec), kind=args.kind,
                                  producer=args.producer, source_platform=args.source_platform,
                                  unresolved=args.unresolved)
        handoff.write(Path(args.out), manifest)
        print(f"交接清单：{Path(args.out).resolve()}\n身份：{manifest['id']}\n类型：{manifest['kind']}")
        print("工程类型是声明；尚未证明可编译、整游戏可玩或可发布。")
        return 0
    if action == "check-handoff":
        manifest = handoff.load(Path(args.manifest), require_buildable=args.for_build)
        print(f"交接完整性通过：{manifest['id']} / {manifest['kind']}")
        return 0
    if action == "draft":
        spec = draft_mod.draft(args.path, args.id, args.title)
        out = draft_mod.write(spec, Path(args.out) if args.out
                              else Path("specs") / f"{args.id}.draft.json")
        print(f"草稿：{out}")
        for warning in spec["_draft"]["warnings"]:
            print(f"  待处理：{warning}")
        print("填完 TODO 字段、删掉 _draft 之后再用 port build。")
        return 0

    if action == "list":
        root = Path(args.dir)
        if not root.is_dir():
            print(f"没有目录：{root}")
            return 2
        sidecars = []
        for path in sorted(root.glob("*.json")):
            if path.name.endswith((".draft.json", ".route.json")):
                sidecars.append(path.name)
                continue
            try:
                spec = portkit.load_spec(path)
            except portkit.SpecError as exc:
                print(f"{path.name:<28} 无效：{exc}")
                continue
            targets = ", ".join(spec.targets)
            print(f"{spec.id:<16} {spec.title:<34} {spec.family:<14} 目标 {targets}")
        if sidecars:
            print(f"（跳过 {len(sidecars)} 个待填草稿与判定记录：{', '.join(sidecars)}）")
        return 0

    if action == "plan":
        spec = portkit.load_spec(args.spec)
        runner = portkit.PortRunner(spec, Path(args.work), dry_run=True,
                                    handoff_path=Path(args.handoff) if args.handoff else None)
        result = runner.run(args.target)
        print(result["report"])
        for stage in result["stages"]:
            for step in stage["detail"].get("planned", []):
                print(f"[{stage['id']}] {step['label']}：{step['cmd']}")
        return 0 if result["status"] == "pass" else 2

    if action == "build":
        spec = portkit.load_spec(args.spec)
        runner = portkit.PortRunner(spec, Path(args.work), force=args.force,
                                    dry_run=args.dry_run,
                                    handoff_path=Path(args.handoff) if args.handoff else None,
                                    repair_patches=[Path(p) for p in args.repair_patch])
        result = runner.run(args.target)
        print(result["report"])
        for stage in result["stages"]:
            if stage["status"] != "pass":
                print(f"停在阶段 {stage['id']}：{stage['detail'].get('reason', '')}",
                      file=sys.stderr)
                return 2
        return 0

    if action == "repair-request":
        return _repair_request(args)
    if action == "repair-submit":
        return _repair_submit(args)
    if action == "run":
        from .portkit import runtime
        spec = portkit.load_spec(args.spec)
        session = runtime.SessionRunner(spec, args.target, Path(args.work),
                                        Path(args.plan), dry_run=args.dry_run)
        result = session.run()
        print(result["report"])
        if result["status"] == "planned":
            return 0
        if result["status"] != "pass":
            print(f"运行证据未通过：{result.get('reason', '')}", file=sys.stderr)
            return 2
        print("运行证据已记录；这只证明主机进程跑到了检查点，不代表整游戏可玩或真机通过。")
        return 0
    if action == "status":
        from .portkit import ladder
        spec = portkit.load_spec(args.spec)
        result = ladder.assess(spec, args.target, Path(args.work))
        text = ladder.render(result)
        print(text)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            print(f"评估报告：{out.resolve()}")
        if args.require:
            required = args.require.upper()
            if required not in ladder.ORDER:
                print(f"未知等级：{args.require}（可选 {', '.join(ladder.ORDER)}）",
                      file=sys.stderr)
                return 2
            current = ladder.ORDER.index(result["level"]) if result["level"] else -1
            if current < ladder.ORDER.index(required):
                print(f"未达到要求等级 {required}", file=sys.stderr)
                return 2
        return 0

    raise SystemExit(f"未知 port 子命令：{action}")


def _repair_request(args) -> int:
    from . import portkit
    from .portkit import repair

    spec = portkit.load_spec(args.spec)
    runner = portkit.PortRunner(spec, Path(args.work),
                                handoff_path=Path(args.handoff) if args.handoff else None,
                                repair_patches=[Path(p) for p in args.repair_patch])
    history = repair.load_history(runner.work_root)
    result = runner.run(args.target)
    if result["status"] == "pass":
        print("这次构建已经通过，不需要修复请求。")
        return 0
    used = repair.attempts_used(history, result["spec_sha256"], args.target)
    if used >= args.budget:
        print(f"修复预算已用完（{used}/{args.budget}），停止生成请求。", file=sys.stderr)
        return 2
    request = repair.build_request(runner, result, includes=args.include, budget=args.budget)
    request["attempt"] = used + 1
    json_path, md_path = repair.save_request(runner.work_root, request)
    print(result["report"])
    print(f"构建失败，修复请求已生成：\n  {json_path}\n  {md_path}")
    print(f"第 {request['attempt']}/{args.budget} 次尝试；提示词在 md 开头，可直接交给 AI。")
    return 2


def _repair_submit(args) -> int:
    import shutil
    from . import portkit
    from .portkit import cache, repair
    from .research import run_lock

    request = repair.load_request(Path(args.request))
    spec = portkit.load_spec(Path(request["spec"]["path"]))
    if cache.digest(spec.raw) != request["spec"]["sha256"]:
        raise repair.RepairError("spec 在生成请求之后变了；请重新生成修复请求")
    try:
        text = Path(args.patch).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise repair.RepairError(f"补丁必须是 UTF-8 文本：{exc}") from exc
    project = Path(request["source_root"]) if request.get("source_root") else None
    info = repair.parse_patch(text, project_root=project,
                              spec_path=Path(request["spec"]["path"]))

    patch_path = Path(request["work"]).resolve() / spec.id / "repair" / "incoming" / f"{info.sha256[:12]}.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    if patch_path.is_file() and patch_path.read_bytes() != text.encode("utf-8"):
        raise repair.RepairError(f"同名补丁内容不同：{patch_path}")
    patch_path.write_bytes(text.encode("utf-8"))

    runner = portkit.PortRunner(spec, Path(request["work"]),
                                handoff_path=Path(request["handoff"]) if request.get("handoff") else None,
                                repair_patches=[patch_path])
    lock_dir = runner.work_root / "repair"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with run_lock(lock_dir):
        history = repair.load_history(runner.work_root)
        repair.check_budget(history, request, info)
        print(f"提交第 {request['attempt']}/{request['budget']} 次修复："
              f"{len(info.files)} 个文件，+{info.added}/-{info.removed}")
        result = runner.run(request["target"])
        target = spec.target(request["target"])
        problem = repair.acceptance_problem(result, target)
        entry = repair.record_attempt(history, request, producer=args.producer,
                                      note=args.note, patch=info, patch_path=patch_path,
                                      result=result,
                                      outcome="rejected" if problem else "accepted",
                                      reason=problem)
        if problem:
            repair.save_history(runner.work_root, history)
            print(result["report"])
            print(f"拒绝：{problem}", file=sys.stderr)
            used = repair.attempts_used(history, request["spec"]["sha256"], request["target"])
            if used >= int(request["budget"]):
                print(f"修复预算已用完（{used}/{request['budget']}），停止。", file=sys.stderr)
                return 2
            runner_now = portkit.PortRunner(spec, Path(request["work"]),
                                            handoff_path=Path(request["handoff"]) if request.get("handoff") else None)
            next_request = repair.build_request(runner_now, result, budget=int(request["budget"]))
            next_request["attempt"] = used + 1
            json_path, md_path = repair.save_request(runner_now.work_root, next_request)
            print(f"下一次请求：\n  {json_path}\n  {md_path}", file=sys.stderr)
            return 2
        accepted_dir = runner.work_root / "repair" / "accepted"
        accepted_dir.mkdir(parents=True, exist_ok=True)
        accepted = accepted_dir / f"attempt-{request['attempt']:02d}-{info.sha256[:8]}.diff"
        shutil.copy2(patch_path, accepted)
        entry["accepted_patch"] = str(accepted)
        history.setdefault("accepted", []).append({"patch": str(accepted), "sha256": info.sha256,
                                                   "target": request["target"],
                                                   "stage": request["failing_stage"],
                                                   "at": entry["at"]})
        repair.save_history(runner.work_root, history)
    print(result["report"])
    build = next(s for s in result["stages"] if s["id"] == "build")
    package = next((s for s in result["stages"] if s["id"] == "package"), None)
    print(f"接受补丁：{accepted}")
    print(f"产物：{build['detail'].get('artifact')}")
    if package and package["detail"].get("path"):
        print(f"包：{package['detail']['path']} ({package['detail'].get('sha256')})")
    print("闸门全通过；仍未做整游戏行为与真机验收，发布资格保持禁止。")
    print(f"固化：把 {accepted} 加进 spec 的 targets.{request['target']}.build.patches，"
          f"或每次 build 时传 --repair-patch。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portfactory", description="开源掌机移植工厂")
    parser.add_argument("--root", default=None, help="工厂根目录（默认本目录）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="初始化工厂目录与数据库").set_defaults(func=_cmd_init)

    device = sub.add_parser("device", help="设备档案")
    device_sub = device.add_subparsers(dest="device_command", required=True)
    add = device_sub.add_parser("add", help="从 JSON 登记或更新设备")
    add.add_argument("file")
    add.set_defaults(func=_cmd_device_add)
    listing = device_sub.add_parser("list", help="列出设备")
    listing.set_defaults(func=_cmd_device_list)

    game = sub.add_parser("game", help="游戏接单")
    game_sub = game.add_subparsers(dest="game_command", required=True)
    record = game_sub.add_parser("intake", help="登记并指纹识别游戏文件")
    record.add_argument("path")
    record.add_argument("--name", default=None)
    record.add_argument("--hash", choices=["full", "quick", "none"], default="full")
    record.set_defaults(func=_cmd_intake)

    recipe = sub.add_parser("recipe", help="配方")
    recipe_sub = recipe.add_subparsers(dest="recipe_command", required=True)
    recipe_sub.add_parser("list", help="列出配方").set_defaults(func=_cmd_recipe_list)

    job = sub.add_parser("job", help="任务")
    job_sub = job.add_subparsers(dest="job_command", required=True)
    new = job_sub.add_parser("new", help="创建移植任务")
    new.add_argument("--game", required=True)
    new.add_argument("--device", required=True)
    new.add_argument("--recipe", required=True)
    new.add_argument("--input", default=None)
    new.set_defaults(func=_cmd_job_new)

    run = job_sub.add_parser("run", help="执行或续跑任务")
    run.add_argument("job")
    run.add_argument("--from-stage", default=None)
    run.set_defaults(func=_cmd_job_run)

    status = job_sub.add_parser("status", help="查看任务")
    status.add_argument("job")
    status.set_defaults(func=_cmd_job_status)

    report = job_sub.add_parser("report", help="生成 Markdown 报告")
    report.add_argument("job")
    report.set_defaults(func=_cmd_job_report)

    template = job_sub.add_parser("attest-template", help="生成真机验收模板")
    template.add_argument("job")
    template.set_defaults(func=_cmd_job_attest_template)

    attest = job_sub.add_parser("attest", help="接入真机验收记录与证据")
    attest.add_argument("job")
    attest.add_argument("file")
    attest.add_argument("--run", action="store_true")
    attest.set_defaults(func=_cmd_job_attest)

    server = sub.add_parser("serve", help="启动本地看板")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    server.set_defaults(func=_cmd_serve)

    research_parser = sub.add_parser("research", help="逆向、AI 重写与原指令行为对照（不依赖真机）")
    rd = research_parser.add_subparsers(dest="research_command", required=True)
    new_rd = rd.add_parser("new", help="只读接入单个游戏程序并冻结快照")
    new_rd.add_argument("path")
    new_rd.add_argument("--target", default="switch-homebrew")
    new_rd.add_argument("--work-root", default="F:/_scratch/portfactory_research")
    new_rd.add_argument("--max-requests", type=int, default=12)
    new_rd.add_argument("--max-context-bytes", type=int, default=240000)
    new_rd.add_argument("--max-seconds", type=float, default=600)
    new_rd.add_argument("--max-attempts", type=int, default=3)
    new_rd.add_argument("--max-modules", type=int, default=3)
    new_rd.set_defaults(func=_cmd_research)
    for name in ("analyze", "status", "report"):
        command = rd.add_parser(name)
        command.add_argument("run_id")
        command.set_defaults(func=_cmd_research)
    work = rd.add_parser("work", help="预算内执行/续跑，inbox 为本地 Qoder 代理收件箱")
    work.add_argument("run_id")
    work.add_argument("--compiler", default="F:/_scratch/zigwin/zig.exe")
    work.add_argument("--provider", choices=("inbox", "local"), default="inbox")
    work.add_argument("--endpoint", default=None)
    work.add_argument("--model", default=None)
    work.set_defaults(func=_cmd_research)
    submit = rd.add_parser("submit", help="接收哈希绑定的代理响应，不允许代理自判通过")
    submit.add_argument("run_id")
    submit.add_argument("response")
    submit.set_defaults(func=_cmd_research)

    port = sub.add_parser("port", help="通用移植流水线：一份 spec 出掌机/Switch 包")
    port_sub = port.add_subparsers(dest="port_command", required=True)
    port_draft = port_sub.add_parser("draft", help="扫描源码，生成待填的 spec 草稿")
    port_draft.add_argument("path", help="源码目录或单个源文件")
    port_draft.add_argument("--id", required=True)
    port_draft.add_argument("--title", default=None)
    port_draft.add_argument("--out", default=None)
    port_draft.set_defaults(func=_cmd_port)
    port_list = port_sub.add_parser("list", help="列出并校验 spec")
    port_list.add_argument("--dir", default="specs")
    port_list.set_defaults(func=_cmd_port)
    port_plan = port_sub.add_parser("plan", help="只解析与打印构建计划，不执行")
    port_plan.add_argument("spec")
    port_plan.add_argument("--target", default="handheld")
    port_plan.add_argument("--work", default="F:/_scratch/portkit")
    port_plan.add_argument("--handoff", help="校验并使用指定工程交接清单")
    port_plan.set_defaults(func=_cmd_port)
    port_route = port_sub.add_parser("route", help="只读扫描输入目录/文件，判定 A/B 路线与下一命令")
    port_route.add_argument("path", help="游戏目录、源码目录、程序文件或压缩包")
    port_route.add_argument("--json", action="store_true", help="输出机器可读判定")
    port_route.add_argument("--out", help="把判定 JSON 写到指定文件")
    port_route.set_defaults(func=_cmd_port)
    port_new = port_sub.add_parser("new", help="按路线判定生成待填 spec 草稿；非源码路线拒收")
    port_new.add_argument("path", help="游戏目录（源码工程）")
    port_new.add_argument("--id", required=True)
    port_new.add_argument("--title", default=None)
    port_new.add_argument("--out-dir", default="specs")
    port_new.add_argument("--force", action="store_true", help="覆盖同名草稿与判定文件")
    port_new.set_defaults(func=_cmd_port)
    port_build = port_sub.add_parser("build", help="执行 prepare→fetch→build→package→verify")
    port_build.add_argument("spec")
    port_build.add_argument("--target", default="handheld")
    port_build.add_argument("--work", default="F:/_scratch/portkit")
    port_build.add_argument("--force", action="store_true")
    port_build.add_argument("--dry-run", action="store_true")
    port_build.add_argument("--handoff", help="校验并使用指定工程交接清单")
    port_build.add_argument("--repair-patch", action="append", default=[],
                            help="额外的修复补丁（可重复）；接受后固化进 spec 或在此续用")
    port_build.set_defaults(func=_cmd_port)
    port_repair = port_sub.add_parser("repair-request", help="真实构建失败后生成自足的 AI 修复请求")
    port_repair.add_argument("spec")
    port_repair.add_argument("--target", default="handheld")
    port_repair.add_argument("--work", default="F:/_scratch/portkit")
    port_repair.add_argument("--handoff", default=None)
    port_repair.add_argument("--include", action="append", default=[],
                             help="额外附带的源码文件（相对工程根）")
    port_repair.add_argument("--repair-patch", action="append", default=[],
                             help="已有修复补丁（续跑时带上）")
    port_repair.add_argument("--budget", type=int, default=3)
    port_repair.set_defaults(func=_cmd_port)
    port_submit = port_sub.add_parser("repair-submit", help="校验补丁并真实重建，通过才接受")
    port_submit.add_argument("request")
    port_submit.add_argument("--patch", required=True)
    port_submit.add_argument("--producer", required=True)
    port_submit.add_argument("--note", default="")
    port_submit.set_defaults(func=_cmd_port)
    port_run = port_sub.add_parser("run", help="在受控条件下执行已构建产物，采集检查点证据")
    port_run.add_argument("spec")
    port_run.add_argument("--target", default="handheld")
    port_run.add_argument("--work", default="F:/_scratch/portkit")
    port_run.add_argument("--plan", required=True, help="运行计划 JSON（检查点/超时/复制项）")
    port_run.add_argument("--dry-run", action="store_true",
                          help="只校验前置条件并打印将执行的命令，不启动进程")
    port_run.set_defaults(func=_cmd_port)
    port_status = port_sub.add_parser("status", help="按已有记录评估成品资格阶梯 R0–R6")
    port_status.add_argument("spec")
    port_status.add_argument("--target", default="handheld")
    port_status.add_argument("--work", default="F:/_scratch/portkit")
    port_status.add_argument("--out", default=None, help="把评估报告写到该 Markdown 文件")
    port_status.add_argument("--require", default=None,
                             help="要求至少达到的等级（R0–R6）；未达到时退出码 2")
    port_status.set_defaults(func=_cmd_port)
    port_handoff = port_sub.add_parser("handoff", help="冻结工程文件和 spec 的交接清单")
    port_handoff.add_argument("project")
    port_handoff.add_argument("--spec", required=True)
    port_handoff.add_argument("--kind", required=True,
                              choices=["analysis_only", "module_source", "buildable_project", "aot_project"])
    port_handoff.add_argument("--producer", required=True)
    port_handoff.add_argument("--source-platform", required=True)
    port_handoff.add_argument("--unresolved", action="append", default=[])
    port_handoff.add_argument("--out", required=True)
    port_handoff.set_defaults(func=_cmd_port)
    port_check = port_sub.add_parser("check-handoff", help="复核交接清单与实际文件")
    port_check.add_argument("manifest")
    port_check.add_argument("--for-build", action="store_true")
    port_check.set_defaults(func=_cmd_port)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，中文提示会变成乱码；失败字符替换掉但不要炸掉整条命令
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
