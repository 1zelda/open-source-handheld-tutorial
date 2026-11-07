from __future__ import annotations

import ctypes
import json
import os
import subprocess
from pathlib import Path

from . import db, recipes
from .gates import TAIL, run_gate
from .models import JobState, Status, count_by_status
from .packaging import PackageError, build_package


class EngineError(RuntimeError):
    pass


class JobBusyError(EngineError):
    pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def _lock(job_dir: Path, job_id: str) -> Path:
    job_dir.mkdir(parents=True, exist_ok=True)
    lock_path = job_dir / "run.lock"
    if lock_path.exists():
        try:
            data = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        pid = int(data.get("pid", 0) or 0)
        if pid and pid != os.getpid() and _pid_alive(pid):
            raise JobBusyError(f"任务正在被进程 {pid} 执行，拒绝重复启动")
        lock_path.unlink(missing_ok=True)
    lock_path.write_text(json.dumps({"pid": os.getpid(), "job_id": job_id,
                                     "started_at": db.now()}), encoding="utf-8")
    return lock_path


def create_job(factory, game_id: str, device_id: str, recipe_id: str,
               input_path: str | None = None) -> dict:
    recipe = recipes.load(factory, recipe_id)
    with factory.connect() as conn:
        game = db.get_game(conn, game_id)
        if game is None:
            raise EngineError(f"游戏不存在：{game_id}")
        device = db.get_device(conn, device_id)
        if device is None:
            raise EngineError(f"设备不存在：{device_id}")
        source = Path(input_path).resolve() if input_path else Path(game["root_path"])
        job_id = db.new_id("job_")
        workdir = factory.job_dir(job_id)
        for sub in ("work", "logs", "evidence", "dist"):
            (workdir / sub).mkdir(parents=True, exist_ok=True)
        ts = db.now()
        conn.execute(
            "INSERT INTO jobs(id, game_id, device_id, recipe_id, input_path, status, workdir, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (job_id, game_id, device_id, recipe_id, str(source), JobState.NEW.value,
             str(workdir), ts, ts),
        )
        for order, stage in enumerate(recipe["stages"], start=1):
            conn.execute(
                "INSERT INTO stages(job_id, stage_id, order_no, status) VALUES (?,?,?,?)",
                (job_id, stage["id"], order, Status.PENDING.value),
            )
        db.event(conn, job_id, "job.created", f"接单：{game['name']} → {device['name']} / {recipe_id}")
    return {"id": job_id, "workdir": str(workdir), "input_path": str(source)}


def _insert_gate(conn, job_id: str, stage_id: str, gate_id: str, status: str,
                 required: bool, detail: dict, evidence_path: str | None) -> None:
    conn.execute(
        "INSERT INTO gate_results(job_id, stage_id, gate_id, status, required, detail, "
        "evidence_path, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (job_id, stage_id, gate_id, status, int(required), db.dump_json(detail),
         evidence_path, db.now()),
    )


def _preflight(factory, conn, job: dict, recipe: dict, device: dict) -> list[dict]:
    job_id = job["id"]
    conn.execute("DELETE FROM gate_results WHERE job_id = ? AND stage_id = 'preflight'", (job_id,))
    results = []

    family_ok = device["family"] in recipe["device_families"]
    status = Status.PASS.value if family_ok else Status.BLOCKED.value
    detail = {"device_family": device["family"], "recipe_families": recipe["device_families"]}
    if not family_ok:
        detail["reason"] = "设备平台不在该配方支持的平台列表内"
    _insert_gate(conn, job_id, "preflight", "device_family", status, True, detail, None)
    results.append({"status": status, "required": True})

    needs = set(recipe.get("requires", {}).get("capabilities", []))
    have = set(device.get("capabilities", []))
    missing = sorted(needs - have)
    status = Status.PASS.value if not missing else Status.BLOCKED.value
    detail = {"required": sorted(needs), "missing": missing}
    if missing:
        detail["reason"] = "设备缺少配方要求的能力"
    _insert_gate(conn, job_id, "preflight", "device_capabilities", status, True, detail, None)
    results.append({"status": status, "required": True})

    source = Path(job["input_path"])
    status = Status.PASS.value if source.exists() else Status.BLOCKED.value
    detail = {"path": str(source)}
    if not source.exists():
        detail["reason"] = "游戏文件路径不存在，请先接入文件"
    _insert_gate(conn, job_id, "preflight", "input_present", status, True, detail, None)
    results.append({"status": status, "required": True})

    if recipe.get("requires", {}).get("verified_device"):
        ok = bool(device.get("verified"))
        status = Status.PASS.value if ok else Status.BLOCKED.value
        detail = {"verified": ok, "reason": "" if ok else "设备尚未完成接线与登记验证"}
        _insert_gate(conn, job_id, "preflight", "device_verified", status, True, detail, None)
        results.append({"status": status, "required": True})

    return results


def _run_step(factory, conn, job: dict, stage: dict, step: dict, ctx: dict,
              stage_id: str) -> tuple[str, dict, str | None]:
    step_type = step["type"]
    log_dir = Path(ctx["job_dir"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    if step_type == "command":
        command = [str(part) for part in step["command"]]
        cwd = Path(step.get("cwd") or ctx["work_dir"])
        cwd.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in step.get("env", {}).items()})
        env["PORTFACTORY_JOB"] = job["id"]
        timeout = int(step.get("timeout", 1800))
        log_path = log_dir / f"{stage_id}_{step['id']}.log"
        try:
            proc = subprocess.run(
                command, cwd=str(cwd), env=env, timeout=timeout,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
        except FileNotFoundError as exc:
            log_path.write_text(f"$ {' '.join(command)}\n{exc}\n", encoding="utf-8")
            return Status.BLOCKED.value, {"reason": f"命令不可用：{command[0]}",
                                          "error": str(exc)}, str(log_path)
        except subprocess.TimeoutExpired as exc:
            output = exc.output if isinstance(exc.output, str) else ""
            log_path.write_text(f"$ {' '.join(command)}\nTIMEOUT {timeout}s\n{output}",
                                encoding="utf-8")
            return Status.FAIL.value, {"reason": f"超时 {timeout}s",
                                       "output_tail": output[-TAIL:]}, str(log_path)
        output = proc.stdout or ""
        log_path.write_text(f"$ {' '.join(command)}\n\n{output}", encoding="utf-8")
        detail = {"command": command, "exit": proc.returncode, "output_tail": output[-TAIL:]}
        if proc.returncode != int(step.get("expected_exit", 0)):
            return Status.FAIL.value, detail, str(log_path)
        return Status.PASS.value, detail, str(log_path)

    if step_type == "package":
        output = Path(step["output"])
        try:
            built = build_package(output, step.get("files", []), job["id"], job["recipe_id"])
        except (PackageError, OSError) as exc:
            return Status.FAIL.value, {"reason": str(exc)}, None
        conn.execute("DELETE FROM artifacts WHERE job_id = ? AND path = ?",
                     (job["id"], str(output)))
        db.add_artifact(conn, job["id"], output, step.get("kind", "package"),
                        built["size"], built["sha256"])
        return Status.PASS.value, {
            "path": str(output), "size": built["size"], "sha256": built["sha256"],
            "files": built["manifest"]["files"],
        }, str(output)

    return Status.FAIL.value, {"reason": f"未知步骤类型：{step_type}"}, None


def _stage_from_results(records: list[dict]) -> str:
    required = [r for r in records if r["required"]]
    if not required:
        return Status.FAIL.value
    counts = count_by_status(required)
    if counts[Status.FAIL.value]:
        return Status.FAIL.value
    if counts[Status.BLOCKED.value]:
        return Status.BLOCKED.value
    if counts[Status.NOT_RUN.value] or counts[Status.PENDING.value] or counts[Status.RUNNING.value]:
        return Status.NOT_RUN.value
    return Status.PASS.value


def _job_state(recipe: dict, stage_rows: list[dict]) -> str:
    statuses = [row["status"] for row in stage_rows]
    if any(s == Status.FAIL.value for s in statuses):
        return JobState.FAILED.value
    if any(s == Status.BLOCKED.value for s in statuses):
        return JobState.BLOCKED.value
    if any(s not in (Status.PASS.value,) for s in statuses):
        return JobState.INCOMPLETE.value
    release_stage = recipe.get("release_stage")
    if release_stage and any(row["stage_id"] == release_stage and row["status"] == Status.PASS.value
                             for row in stage_rows):
        return JobState.RELEASED.value
    return JobState.VERIFIED.value


def run_job(factory, job_id: str, force_stage: str | None = None) -> dict:
    with factory.connect() as conn:
        job = db.get_job(conn, job_id)
        if job is None:
            raise EngineError(f"任务不存在：{job_id}")
        recipe = recipes.load(factory, job["recipe_id"])
        device = db.get_device(conn, job["device_id"])
        if device is None:
            raise EngineError(f"设备不存在：{job['device_id']}")
        game = db.get_game(conn, job["game_id"]) if job["game_id"] else None

        workdir = Path(job["workdir"])
        lock_path = _lock(workdir, job_id)
        try:
            conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?",
                         (JobState.RUNNING.value, db.now(), job_id))
            db.event(conn, job_id, "job.run", "开始执行")
            conn.commit()

            pre = _preflight(factory, conn, job, recipe, device)
            conn.commit()
            pre_counts = count_by_status(pre)
            if pre_counts[Status.FAIL.value]:
                conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?",
                             (JobState.FAILED.value, db.now(), job_id))
                db.event(conn, job_id, "preflight.fail", "预检失败")
                conn.commit()
                return {"id": job_id, "status": JobState.FAILED.value,
                        "preflight": pre_counts}
            if pre_counts[Status.BLOCKED.value]:
                conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?",
                             (JobState.BLOCKED.value, db.now(), job_id))
                db.event(conn, job_id, "preflight.blocked", "预检阻塞")
                conn.commit()
                return {"id": job_id, "status": JobState.BLOCKED.value,
                        "preflight": pre_counts}

            input_path = Path(job["input_path"])
            ctx = {
                "job_id": job_id,
                "job_dir": str(workdir),
                "work_dir": str(workdir / "work"),
                "evidence_dir": str(workdir / "evidence"),
                "dist_dir": str(workdir / "dist"),
                "input": str(input_path),
                "input_dir": str(input_path if input_path.is_dir() else input_path.parent),
                "recipe_dir": str(Path(recipe["_source"]).resolve().parent),
                "root": str(factory.root),
                "recipe_id": job["recipe_id"],
                "device": device,
                "game": game or {},
            }

            stage_rows = db.job_stages(conn, job_id)
            stage_ids = {row["stage_id"] for row in stage_rows}
            if force_stage is not None and force_stage not in stage_ids:
                raise EngineError(f"阶段不存在：{force_stage}")
            for row in stage_rows:
                stage_id = row["stage_id"]
                stage = next(s for s in recipe["stages"] if s["id"] == stage_id)
                if force_stage is not None:
                    if row["order_no"] < next(
                            r["order_no"] for r in stage_rows if r["stage_id"] == force_stage):
                        if row["status"] == Status.PASS.value:
                            continue
                elif row["status"] == Status.PASS.value:
                    continue

                conn.execute("DELETE FROM gate_results WHERE job_id=? AND stage_id=?",
                             (job_id, stage_id))
                conn.execute("UPDATE stages SET status=?, started_at=?, finished_at=NULL, "
                             "detail=NULL WHERE job_id=? AND stage_id=?",
                             (Status.RUNNING.value, db.now(), job_id, stage_id))
                conn.commit()
                db.event(conn, job_id, "stage.start", f"阶段 {stage_id} 开始")

                step_failure = None
                for step in stage.get("steps", []):
                    step_cfg = recipes.expand(step, ctx)
                    status, detail, evidence = _run_step(
                        factory, conn, job, stage, step_cfg, ctx, stage_id)
                    conn.commit()
                    if status != Status.PASS.value:
                        step_failure = (step["id"], status, detail, evidence)
                        break

                if step_failure:
                    step_id, status, detail, evidence = step_failure
                    _insert_gate(conn, job_id, stage_id, f"step:{step_id}", status,
                                 True, detail, evidence)
                    conn.commit()
                    records = [{"status": status, "required": True}]
                else:
                    ctx["stage_id"] = stage_id
                    prior = [dict(r) for r in conn.execute(
                        "SELECT stage_id, gate_id, status, required, detail, evidence_path "
                        "FROM gate_results WHERE job_id=? AND stage_id<>?", (job_id, stage_id)
                    ).fetchall()]
                    ctx["prior_results"] = prior
                    for gate in stage.get("gates", []):
                        gate_cfg = recipes.expand(gate, ctx)
                        outcome = run_gate(gate_cfg, ctx)
                        _insert_gate(conn, job_id, stage_id, gate_cfg["id"], outcome.status,
                                     bool(gate_cfg.get("required", True)),
                                     outcome.detail, outcome.evidence_path)
                        conn.commit()
                    records = [dict(r) for r in conn.execute(
                        "SELECT status, required FROM gate_results WHERE job_id=? AND stage_id=?",
                        (job_id, stage_id)).fetchall()]

                stage_status = _stage_from_results(records)
                conn.execute("UPDATE stages SET status=?, finished_at=?, detail=? "
                             "WHERE job_id=? AND stage_id=?",
                             (stage_status, db.now(),
                              db.dump_json({"counts": count_by_status(records)}),
                              job_id, stage_id))
                db.event(conn, job_id, "stage.end", f"阶段 {stage_id} -> {stage_status}")
                conn.commit()
                if stage_status != Status.PASS.value:
                    break

            stage_rows = db.job_stages(conn, job_id)
            final = _job_state(recipe, stage_rows)
            conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?",
                         (final, db.now(), job_id))
            db.event(conn, job_id, "job.end", f"任务状态 -> {final}")
            conn.commit()
            return {"id": job_id, "status": final}
        finally:
            try:
                data = json.loads(lock_path.read_text(encoding="utf-8"))
                if int(data.get("pid", 0)) == os.getpid():
                    lock_path.unlink(missing_ok=True)
            except (OSError, json.JSONDecodeError):
                pass


def job_summary(conn, job_id: str) -> dict:
    job = db.get_job(conn, job_id)
    if job is None:
        raise EngineError(f"任务不存在：{job_id}")
    stages = db.job_stages(conn, job_id)
    gates = db.job_gates(conn, job_id)
    required = [g for g in gates if g["required"]]
    return {
        "job": job,
        "game": db.get_game(conn, job["game_id"]) if job["game_id"] else None,
        "device": db.get_device(conn, job["device_id"]),
        "stages": stages,
        "gates": gates,
        "artifacts": db.job_artifacts(conn, job_id),
        "counts_all": count_by_status(gates),
        "counts_required": count_by_status(required),
    }
