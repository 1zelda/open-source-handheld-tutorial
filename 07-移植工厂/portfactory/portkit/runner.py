from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from ..research import ResearchError, run_lock, write_json
from . import builders, cache, gates, portmaster, profiles
from .spec import PortSpec

DEFAULT_TIMEOUT = 3600


class RunError(RuntimeError):
    pass


def _bash() -> str:
    for candidate in (os.environ.get("PORTFACTORY_BASH"), "D:/Git/bin/bash.exe",
                      "C:/Program Files/Git/bin/bash.exe"):
        if candidate and Path(candidate).is_file():
            return candidate
    return "bash"


@dataclass
class StageResult:
    id: str
    status: str
    seconds: float = 0.0
    detail: dict = field(default_factory=dict)


class PortRunner:
    def __init__(self, spec: PortSpec, work_root: Path, force: bool = False,
                 dry_run: bool = False, handoff_path: Path | None = None,
                 repair_patches: list[Path] | None = None):
        self.spec = spec
        self.work_root = (Path(work_root) / spec.id).resolve()
        self.force = force
        self.dry_run = dry_run
        self.handoff_path = handoff_path
        self.handoff = None
        self.repair_patches = [Path(p).resolve() for p in (repair_patches or [])]
        for patch in self.repair_patches:
            if not patch.is_file():
                raise RunError(f"修复补丁不存在：{patch}")
        self.state_path = self.work_root / "state.json"
        self.state = self._load_state()
        self.current: dict[str, StageResult] = {}
        self.profile = None

    def _load_state(self) -> dict:
        if self.state_path.is_file():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(state, dict) and isinstance(state.get("targets"), dict):
                    return state
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        return {"spec": str(self.spec.path), "targets": {}}

    def _save_state(self) -> None:
        self.work_root.mkdir(parents=True, exist_ok=True)
        write_json(self.state_path, self.state)

    def _entry(self, target: str, stage: str) -> dict:
        return self.state["targets"].get(target, {}).get("stages", {}).get(stage, {})

    def _mark(self, target: str, stage: StageResult, key: str | None,
              outputs: list[dict], paths: dict) -> None:
        entry = self.state["targets"].setdefault(target, {"stages": {}})
        entry["stages"][stage.id] = {
            "status": stage.status, "seconds": round(stage.seconds, 1),
            "detail": stage.detail, "input_key": key, "outputs": outputs,
            "paths": {k: str(v) for k, v in paths.items()},
        }
        if stage.status in ("running", "blocked", "fail") and not (stage.id in ("admit", "prepare") and stage.status == "running"):
            order = ["admit", "prepare", "fetch", "build", "package", "verify"]
            for name in order[order.index(stage.id) + 1:]:
                if name in entry["stages"]:
                    entry["stages"][name]["status"] = "not_run"
        self._save_state()

    def _passed(self, target: str, stage: str, key: str | None) -> bool:
        entry = self._entry(target, stage)
        return (key is not None and entry.get("status") == "pass"
                and entry.get("input_key") == key
                and cache.unchanged(entry.get("outputs", [])))

    def _key(self, stage: "_Stage") -> str | None:
        base = self.spec.path.parent if self.spec.path else Path.cwd()
        target = stage.target
        cfg = target["build"]
        dependencies = {"runner": cache.stamp(Path(__file__)),
                        "cache": cache.stamp(Path(cache.__file__))}
        if stage.id == "fetch":
            source = dict(self.spec.source)
            if self.handoff:
                from .. import handoff
                current = handoff.load(self.handoff_path, require_buildable=True)
                if current["id"] != self.handoff["id"]:
                    raise cache.CacheError("交接清单在任务执行期间发生变化")
                source["handoff"] = self.handoff["id"]
            elif source.get("local"):
                local = Path(source["local"])
                local = local if local.is_absolute() else base / local
                if self.work_root.is_relative_to(local.resolve()):
                    raise cache.CacheError("工作目录不能位于源码输入目录内")
                if not (local / ".git").exists():
                    source["local_content"] = cache.stamp(local)
            dependencies.update(source=source, data=self.spec.data,
                                patches=[cache.stamp(p) for p in stage._patches()])
        elif stage.id == "build":
            identity = self.current["prepare"].detail["identity"]
            assets = []
            for entry in cfg.get("assets", []):
                path = Path(str(entry["src"]).replace("${data}", str(stage.paths["data"])))
                assets.append(cache.stamp(path if path.is_absolute() else base / path))
            dependencies.update(build=cfg, profile=identity,
                                fetched=[cache.stamp(Path(r["path"])) for r in
                                         self._entry(stage.target_name, "fetch")["outputs"]],
                                inputs=[cache.stamp(base / p) for p in cfg.get("cache_inputs", [])],
                                assets=assets, builders=cache.stamp(Path(builders.__file__)),
                                profiles=cache.stamp(Path(profiles.__file__)))
        elif stage.id == "package":
            pkg = target.get("package", {})
            inputs = [cache.stamp(self.artifact(target, stage.paths))]
            for entry in pkg.get("files", []):
                path = Path(str(entry["src"]).replace("${artifact}", str(self.artifact(target, stage.paths)))
                            .replace("${data}", str(stage.paths["data"])))
                inputs.append(cache.stamp(path if path.is_absolute() else base / path))
            for rel in pkg.get("license_files", []) + ([pkg["screenshot"]] if pkg.get("screenshot") else []):
                inputs.append(cache.stamp(base / rel))
            dependencies.update(package=pkg, inputs=inputs,
                                portmaster=cache.stamp(Path(portmaster.__file__)))
        else:
            return None
        return cache.digest(dependencies)

    def _outputs(self, stage: "_Stage") -> list[dict]:
        if stage.id == "fetch":
            return [cache.stamp(stage.paths[k]) for k in ("src", "data")]
        if stage.id == "build":
            return [cache.stamp(self.artifact(stage.target, stage.paths)),
                    cache.stamp(stage.paths["src"])]
        if stage.id == "package":
            return [cache.stamp(Path(self.current["package"].detail["path"]))]
        return []

    def fresh_paths(self, target: str, paths: dict, names: tuple[str, ...]) -> None:
        root = self.work_root / target / "attempts" / uuid4().hex
        for name in names:
            paths[name] = root / name
            paths[name].mkdir(parents=True, exist_ok=True)

    def run(self, target_name: str) -> dict:
        self.work_root.mkdir(parents=True, exist_ok=True)
        try:
            with run_lock(self.work_root):
                self.state = self._load_state()
                return self._run(target_name)
        except ResearchError as exc:
            raise RunError(str(exc)) from exc

    def _run(self, target_name: str) -> dict:
        run_id = "port_" + uuid4().hex
        target = self.spec.target(target_name)
        paths = self._paths(target_name)
        if self.dry_run:
            self.fresh_paths(target_name, paths, ("src", "build", "stage", "dist", "logs", "data"))
        paths["logs"].mkdir(parents=True, exist_ok=True)
        self.current = {}
        results: list[StageResult] = []
        for stage in self._stages(target_name, target, paths):
            started = time.time()
            key = None
            outputs = []
            try:
                key = None if self.dry_run else self._key(stage)
                reusable = key is not None
                if stage.id == "build" and not self.dry_run:
                    reusable = bool(target["build"].get("cache_inputs")) and self.current["prepare"].detail["identity"]["complete"]
                if reusable and not self.force and not self.dry_run and self._passed(target_name, stage.id, key):
                    entry = self._entry(target_name, stage.id)
                    paths.update({k: Path(v) for k, v in entry["paths"].items()})
                    result = StageResult(stage.id, "pass", 0, {**entry["detail"], "cached": True})
                    self.current[stage.id] = result
                    results.append(result)
                    continue
                if not self.dry_run:
                    self._mark(target_name, StageResult(stage.id, "running"), key, [], paths)
                status, detail = stage.run()
                result = StageResult(stage.id, status, time.time() - started, detail)
                self.current[stage.id] = result
                if status == "pass" and not self.dry_run:
                    if key is not None and self._key(stage) != key:
                        raise cache.CacheError("执行期间输入发生变化，本次结果不能复用")
                    outputs = self._outputs(stage)
                    if stage.id == "build" and not reusable:
                        detail["cache_disabled"] = "未完整识别工具或未声明 build.cache_inputs，构建不复用"
            except (cache.CacheError, OSError, ValueError, subprocess.SubprocessError) as exc:
                result = StageResult(stage.id, "blocked", time.time() - started, {"reason": str(exc)})
                self.current[stage.id] = result
            results.append(result)
            if not self.dry_run:
                self._mark(target_name, result, key, outputs, paths)
            if result.status != "pass":
                break
        report = _report(self, target_name, results)
        suffix = "-plan" if self.dry_run else ""
        report_path = self.work_root / f"report-{target_name}{suffix}.md"
        report_path.write_text(report, encoding="utf-8")
        result = {"run_id": run_id, "target": target_name,
                  "status": results[-1].status if results else "not_run",
                  "handoff_id": self.handoff["id"] if self.handoff else None,
                  "repair_patches": [cache.stamp(p) for p in self.repair_patches],
                  "spec_sha256": cache.digest(self.spec.raw),
                  "stages": [r.__dict__ for r in results], "report": report,
                  "whole_game_behavior": "not_run", "device_test": "not_run", "release_allowed": False}
        if not self.dry_run:
            result["record"] = str(self.work_root / f"{run_id}.json")
            write_json(Path(result["record"]), result)
            state = self.state["targets"][target_name]
            build = self.current.get("build")
            identity = build.detail.get("artifact_identity") if build and build.status == "pass" else None
            runtime = state.get("runtime")
            if runtime and (result["status"] != "pass" or not identity
                            or runtime.get("artifact_sha256") != identity.get("sha256")):
                state.pop("runtime", None)
            state.update(run_id=run_id, status=result["status"], record=result["record"])
            self._save_state()
        return result

    def _paths(self, target: str) -> dict[str, Path]:
        return {
            "src": self.work_root / target / "src",
            "build": self.work_root / target / "build",
            "stage": self.work_root / target / "stage",
            "dist": self.work_root / target / "dist",
            "logs": self.work_root / target / "logs",
            "data": self.work_root / target / "data",
        }

    def _stages(self, target_name: str, target: dict, paths: dict) -> list["_Stage"]:
        return [
            _Admit(self, target_name, target, paths),
            _Prepare(self, target_name, target, paths),
            _Fetch(self, target_name, target, paths),
            _Build(self, target_name, target, paths),
            _Package(self, target_name, target, paths),
            _Verify(self, target_name, target, paths),
        ]

    # ---------------------------------------------------------------- 工具
    def exec(self, cmd: str, cwd: Path, env: dict[str, str], log: Path,
             timeout: int | None = None, shell: str | None = None) -> tuple[int, str]:
        log.parent.mkdir(parents=True, exist_ok=True)
        if self.dry_run:
            log.write_text(f"[dry-run] {cmd}\n", encoding="utf-8")
            return 0, ""
        started = time.time()
        with open(log, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(f"\n$ {cmd}\n")
            fh.flush()
            try:
                proc = subprocess.run([shell or _bash(), "-lc", cmd], cwd=str(cwd), env=env,
                                      stdout=fh, stderr=subprocess.STDOUT,
                                      timeout=timeout or DEFAULT_TIMEOUT)
                code = proc.returncode
            except subprocess.TimeoutExpired:
                fh.write(f"TIMEOUT {timeout}s\n")
                code = -9
            except FileNotFoundError as exc:
                fh.write(f"{exc}\n")
                code = -1
            fh.write(f"[exit {code} after {time.time() - started:.1f}s]\n")
        return code, _tail(log)

    def artifact(self, target: dict, paths: dict) -> Path:
        return builders.artifact_path(target, paths["build"], paths["src"])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_zip(blob: Path, dest: Path, lowercase: bool = False,
                 strip_root: bool = False) -> None:
    """解压并挡住 ../ 越界条目；lowercase 用在引擎按小写文件名找数据的场合；
    strip_root 去掉压缩包里唯一的那层顶层目录（很多数据包会套一层同名文件夹）。"""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(blob) as zf:
        members = [i for i in zf.infolist() if not i.is_dir()]
        prefix = ""
        if strip_root and members:
            tops = {i.filename.replace("\\", "/").split("/", 1)[0] for i in members}
            if len(tops) == 1 and all("/" in i.filename.replace("\\", "/") for i in members):
                prefix = tops.pop() + "/"
        for info in members:
            name = info.filename.replace("\\", "/")
            if prefix:
                name = name[len(prefix):]
            if lowercase:
                name = name.lower()
            out = (dest / name).resolve()
            if not out.is_relative_to(root):
                raise OSError(f"压缩包条目越界：{info.filename}")
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as fh:
                shutil.copyfileobj(src, fh)


def _tail(path: Path, limit: int = 3000) -> str:
    try:
        data = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return data[-limit:]


class _Stage:
    id = "stage"

    def __init__(self, runner: PortRunner, target_name: str, target: dict, paths: dict):
        self.runner = runner
        self.spec = runner.spec
        self.target_name = target_name
        self.target = target
        self.paths = paths

    def run(self) -> tuple[str, dict]:
        raise NotImplementedError


class _Admit(_Stage):
    id = "admit"

    def run(self) -> tuple[str, dict]:
        self.runner.handoff = None
        if self.runner.handoff_path:
            from .. import handoff
            manifest = handoff.load(self.runner.handoff_path, require_buildable=True)
            if not self.spec.path or _sha256_file(self.spec.path) != manifest["spec"]["sha256"]:
                return "blocked", {"reason": "交接清单与本次 spec 不匹配"}
            if self.runner.work_root.is_relative_to(Path(manifest["project"]["root"]).resolve()):
                return "blocked", {"reason": "工作目录不能位于交接工程内部"}
            self.runner.handoff = manifest
            return "pass", {"handoff_id": manifest["id"], "kind": manifest["kind"]}
        return "pass", {"source": "spec", "spec_sha256": cache.digest(self.spec.raw)}


class _Prepare(_Stage):
    id = "prepare"

    def run(self) -> tuple[str, dict]:
        target = self.target
        deps = target.get("deps") or []
        if isinstance(deps, dict):
            deps = [{"id": k} for k in deps]
        needs_sdl2 = not deps or any(d.get("id", "").startswith("sdl2") for d in deps)
        try:
            profile = profiles.materialize(target["profile"], self.runner.work_root / "_cache",
                                           needs_sdl2=needs_sdl2)
        except profiles.ProfileError as exc:
            return "blocked", {"reason": str(exc)}
        detail = {"profile": profiles.describe(profile), "notes": profile.notes}
        system = (target.get("build") or {}).get("system")
        tools = []
        if system == "cmake":
            tools = [profile.cmake, profile.ninja]
        elif system == "meson":
            tools = ["meson", "ninja"]
        elif system in ("gnumake", "autotools"):
            tools = [profile.vars.get("make") or builders.make_program()]
        self.runner.profile = profile
        if not self.runner.dry_run:
            for tool in tools:
                found = profiles.probe(profile.bin_dir, tool, shell=profile.shell,
                                       env=profile.child_env(os.environ)) if profile.shell \
                    else profiles.probe(profile.bin_dir, tool)
                if found is None:
                    return "blocked", {**detail, "reason": f"缺少工具 {tool}"}
                detail.setdefault("tools", {})[tool] = found
            detail["identity"] = cache.tool_identity(profile, target, profile.shell or _bash())
        return "pass", detail


class _Fetch(_Stage):
    id = "fetch"

    def _patches(self) -> list[Path]:
        """源码补丁对全部目标生效；目标自己的补丁只给该目标（例如 mingw 的链接方言）；
        修复补丁排最后，来自 repair 闭环的受控提交。"""
        base = self.spec.path.parent if self.spec.path else Path(".")
        items = [base / p for p in self.spec.source.get("patches", [])]
        items += [base / p for p in (self.target.get("build") or {}).get("patches", [])]
        items += list(self.runner.repair_patches)
        return [p.resolve() for p in items]

    def _apply(self, patch_path: Path, log: Path, env: dict) -> tuple[str, str, dict]:
        src = self.paths["src"]
        if not patch_path.is_file():
            return "fail", "", {"reason": f"补丁不存在：{patch_path}"}
        label = patch_path.name
        try:
            label = patch_path.relative_to(self.spec.path.parent).as_posix() \
                if self.spec.path else label
        except ValueError:
            label = f"repair/{patch_path.name}"
        # 快照若位于别的仓库里（例如宿主目录本身是 git 仓库），git 会把补丁路径按
        # 外层仓库根解释并静默跳过；把仓库发现限制在快照之内。
        penv = {**env, "GIT_CEILING_DIRECTORIES": str(src.parent)}
        code, out = self.runner.exec(
            f'git -C "{src.as_posix()}" apply --check "{patch_path.as_posix()}"', src, penv, log)
        if code != 0:
            # 已经打过就跳过，但把结论写清楚
            code2, _ = self.runner.exec(
                f'git -C "{src.as_posix()}" apply --reverse --check "{patch_path.as_posix()}"',
                src, penv, log)
            if code2 == 0:
                return "pass", label, {"patch": label, "state": "already_applied"}
            return "fail", out, {"reason": f"补丁打不上：{label}", "tail": out}
        code, out = self.runner.exec(
            f'git -C "{src.as_posix()}" apply "{patch_path.as_posix()}"', src, penv, log)
        if code != 0:
            return "fail", out, {"reason": f"git apply 失败：{label}", "tail": out}
        return "pass", label, {"patch": label, "state": "applied"}

    def run(self) -> tuple[str, dict]:
        spec = self.spec
        if self.runner.dry_run:
            return "pass", {"dry_run": True, "source": spec.source}
        self.runner.fresh_paths(self.target_name, self.paths, ("src", "data"))
        src = self.paths["src"]
        source = spec.source
        if self.runner.handoff:
            from .. import handoff
            cache.copy_source(Path(self.runner.handoff["project"]["root"]), src)
            handoff.check_project(self.runner.handoff, src)
            source = {}
        log = self.paths["logs"] / "fetch.log"
        env = dict(os.environ)
        local = source.get("local")
        clone_from = source.get("repo")
        mirror_env = source.get("mirror_env")
        mirror = os.environ.get(mirror_env) if mirror_env else None
        if mirror:
            clone_from = mirror

        if local:
            local = Path(local)
            if not local.is_absolute():
                local = (self.spec.path.parent if self.spec.path else Path.cwd()) / local
            if not local.exists():
                return "blocked", {"reason": f"source.local 不存在：{local}"}
            if (local / ".git").exists():
                clone_from = local.as_posix()
            else:
                cache.copy_source(local, src)
                clone_from = None

        if clone_from and not (src / ".git").is_dir():
            clone = (f'git clone --no-checkout "{clone_from}" "{src.as_posix()}"')
            code, out = self.runner.exec(clone, self.runner.work_root, env, log)
            if code != 0:
                return "blocked", {"reason": "git clone 失败", "tail": out}
        if (src / ".git").is_dir():
            commit = str(source.get("commit", "")).lower()
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                return "fail", {"reason": "工作副本是 git 仓库但 spec 没钉完整 commit"}
            code, out = self.runner.exec(
                f'git -C "{src.as_posix()}" checkout --detach {commit}', src, env, log)
            if code != 0:
                return "blocked", {"reason": f"checkout {commit} 失败", "tail": out}
            head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"],
                                  env=env, capture_output=True, text=True, timeout=30)
            if head.returncode or head.stdout.strip().lower() != commit:
                return "fail", {"reason": "检出 commit 与 spec 不一致", "head": head.stdout[-200:]}

        patch_results = []
        for rel in self._patches():
            status, out, detail = self._apply(rel, log, env)
            if status != "pass":
                return status, detail
            patch_results.append(detail)
        status, download_detail = self._downloads(log, env)
        if status != "pass":
            return status, download_detail
        return "pass", {"patches": patch_results, **download_detail,
                        "repair_patches": [cache.stamp(p) for p in self.runner.repair_patches]}

    def _downloads(self, log: Path, env: dict) -> tuple[str, dict]:
        """自由分发数据：按 spec 里的 URL 下载、按 sha256 校验、解到 <target>/data。"""
        items = self.spec.data.get("downloads") or []
        if self.spec.data.get("policy") != "free-download" or not items:
            return "pass", {"downloads": []}
        cache = self.runner.work_root / "_cache" / "downloads"
        results = []
        for item in items:
            url = item["url"]
            name = item.get("name") or url.rstrip("/").rsplit("/", 1)[-1] or "download.bin"
            blob = cache / name
            want = item["sha256"].lower()
            if self.runner.dry_run:
                results.append({"url": url, "name": name, "planned": True})
                continue
            if blob.is_file() and _sha256_file(blob) == want:
                state = "cached"
            else:
                cache.mkdir(parents=True, exist_ok=True)
                code, out = self.runner.exec(
                    f'curl -fL --retry 3 --connect-timeout 30 -o "{blob.as_posix()}" "{url}"',
                    cache, env, log)
                if code != 0 or not blob.is_file():
                    return "blocked", {"reason": f"下载失败：{url}", "tail": out}
                got = _sha256_file(blob)
                if got != want:
                    blob.unlink(missing_ok=True)
                    return "fail", {"reason": f"{name} 的 sha256 不符，已删掉可疑文件",
                                    "want": want, "got": got}
                state = "downloaded"
            into = self.paths["data"] / item.get("into", "")
            if item.get("format", "zip") == "zip":
                try:
                    _extract_zip(blob, into, lowercase=bool(item.get("lowercase")),
                                 strip_root=bool(item.get("strip_root")))
                except (OSError, zipfile.BadZipFile) as exc:
                    return "fail", {"reason": f"解包失败 {name}：{exc}"}
            else:
                into.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(blob, into)
            results.append({"url": url, "name": name, "sha256": want, "state": state,
                            "into": into.as_posix()})
        return "pass", {"downloads": results}



class _Build(_Stage):
    id = "build"

    def run(self) -> tuple[str, dict]:
        target = self.target
        profile = self.runner.profile
        if not self.runner.dry_run:
            source = self.paths["src"]
            self.runner.fresh_paths(self.target_name, self.paths, ("src", "build"))
            cache.copy_source(source, self.paths["src"])
            if (source / ".git").is_dir():
                shutil.copytree(source / ".git", self.paths["src"] / ".git")
        base = self.spec.path.parent if self.spec.path else Path(".")
        for entry in target["build"].get("assets") or []:
            src_text = str(entry["src"]).replace("${data}", self.paths["data"].as_posix())
            src_path = Path(src_text)
            if not src_path.is_absolute():
                src_path = base / src_path
            if not src_path.exists():
                if self.runner.dry_run:
                    continue
                return "fail", {"reason": f"build.assets 源不存在：{src_path}"}
            if not self.runner.dry_run:
                portmaster.copy_member(src_path, self.paths["src"] / entry["dst"])
        try:
            plan = builders.plan(target, profile, self.paths["src"], self.paths["build"])
        except ValueError as exc:
            return "fail", {"reason": str(exc)}
        env = profile.child_env(os.environ)
        timeout = int(target.get("timeout", DEFAULT_TIMEOUT))
        logs = []
        for i, command in enumerate(plan, start=1):
            log = self.paths["logs"] / f"build_{i}_{command.label.replace(' ', '_')}.log"
            code, out = self.runner.exec(command.cmd, command.cwd,
                                         {**env, **command.env}, log, timeout,
                                         shell=profile.shell)
            logs.append({"step": command.label, "exit": code, "log": str(log)})
            if code != 0:
                return "fail", {"reason": f"{command.label} 退出码 {code}", "tail": out,
                                "steps": logs}
        artifact = self.runner.artifact(target, self.paths)
        if not self.runner.dry_run and not artifact.is_file():
            return "fail", {"reason": f"没有产出 {artifact}", "steps": logs}
        return "pass", {"artifact": str(artifact), "steps": logs,
                        "artifact_identity": cache.stamp(artifact) if not self.runner.dry_run else None,
                        "planned": [{"label": c.label, "cmd": c.cmd} for c in plan]}


class _Package(_Stage):
    id = "package"

    def run(self) -> tuple[str, dict]:
        spec = self.spec
        pkg = self.target.get("package") or {}
        platform = pkg.get("platform", "portmaster")
        artifact = self.runner.artifact(self.target, self.paths)
        if not self.runner.dry_run and not artifact.is_file():
            return "blocked", {"reason": f"产物不存在：{artifact}"}
        if platform not in ("portmaster", "nro-zip"):
            return "fail", {"reason": f"未知打包平台 {platform}"}
        if not self.runner.dry_run:
            self.runner.fresh_paths(self.target_name, self.paths, ("stage", "dist"))
        staging = self.paths["stage"]
        base = self.spec.path.parent if self.spec.path else Path(".")
        if platform == "nro-zip":
            # Switch 交付就是个 zip：.nro + 许可 + 安装说明（数据已打进 romfs，不另带）
            if self.runner.dry_run:
                return "pass", {"dry_run": True, "staging": str(staging)}
            nro_name = pkg.get("nro_name") or artifact.name
            portmaster.copy_member(artifact, staging / nro_name)
            for rel in pkg.get("license_files", []):
                portmaster.copy_member(base / rel, staging / "licenses" / Path(rel).name)
            readme = pkg.get("readme_text")
            if readme:
                (staging / "README.txt").write_text(readme, encoding="utf-8", newline="\n")
            out = self.paths["dist"] / pkg.get("zip_name", f"{spec.id}.zip")
            return "pass", portmaster.build_zip(staging, out)
        (staging / pkg["port_dir"] / "licenses").mkdir(parents=True, exist_ok=True)

        files = pkg.get("files") or [{"src": str(artifact), "dst": f"{pkg['port_dir']}/game"}]
        missing = []
        for entry in files:
            src = str(entry["src"]).replace("${artifact}", artifact.as_posix())
            src = src.replace("${data}", self.paths["data"].as_posix())
            src_path = Path(src)
            if not src_path.is_absolute():
                src_path = base / src_path
            if not src_path.exists():
                if self.runner.dry_run:
                    missing.append(str(src_path))
                    continue
                return "fail", {"reason": f"待打包文件不存在：{src_path}"}
            portmaster.copy_member(src_path, staging / entry["dst"])

        cfg = dict(pkg)
        cfg["port_dir"] = pkg["port_dir"]
        launcher = portmaster.stage_launcher(staging, cfg)
        items = pkg.get("items") or [launcher.name, pkg["port_dir"]]
        port_json = portmaster.render_port_json(
            {"zip_name": pkg.get("zip_name", f"{spec.title}.zip"), "attr": pkg["attr"]}, items)
        (staging / pkg["port_dir"] / "port.json").write_text(
            json.dumps(port_json, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        entries = pkg.get("gameinfo") or [{"script": launcher.name, "name": spec.title}]
        (staging / pkg["port_dir"] / "gameinfo.xml").write_text(
            portmaster.render_gameinfo(cfg, entries), encoding="utf-8")

        for name in pkg.get("license_files", []):
            portmaster.copy_member(base / name, staging / pkg["port_dir"] / "licenses" / Path(name).name)
        if pkg.get("screenshot"):
            shot = base / pkg["screenshot"]
            if shot.is_file():
                portmaster.copy_member(shot, staging / pkg["port_dir"] / "screenshot.png")
            elif not self.runner.dry_run:
                return "fail", {"reason": f"截图不存在：{shot}"}

        out = self.paths["dist"] / pkg.get("zip_name", f"{spec.id}.zip")
        if self.runner.dry_run:
            return "pass", {"dry_run": True, "staging": str(staging), "missing": missing}
        built = portmaster.build_zip(staging, out)
        return "pass", built


class _Verify(_Stage):
    id = "verify"

    def run(self) -> tuple[str, dict]:
        package = self.runner.current["package"].detail
        artifact = self.runner.current["build"].detail
        if not self.runner.dry_run:
            expected = {k: package[k] for k in ("path", "size", "sha256")}
            if not cache.unchanged([expected, artifact["artifact_identity"]]):
                return "fail", {"reason": "本次构建或打包产物已变化，拒绝验证其他文件"}
        ctx = {
            "spec": self.spec,
            "target": self.target,
            "artifact": artifact["artifact"],
            "package": package.get("path", ""),
        }
        results = {}
        problems = []
        for gate_id in self.target["gates"]:
            handler = gates.GATES.get(gate_id)
            if handler is None:
                results[gate_id] = {"status": "fail", "detail": {"reason": "未知闸门"}}
                problems.append(gate_id)
                continue
            if self.runner.dry_run:
                results[gate_id] = {"status": "skipped(dry-run)"}
                continue
            try:
                outcome = handler(ctx)
            except Exception as exc:  # 闸门崩了不许当通过
                outcome = gates.Result("fail", {"reason": f"{type(exc).__name__}: {exc}"})
            results[gate_id] = {"status": outcome.status, "detail": outcome.detail}
            if outcome.status != "pass":
                problems.append(gate_id)
        if not self.runner.dry_run and not cache.unchanged([expected, artifact["artifact_identity"]]):
            return "fail", {"reason": "验收期间产物发生变化", "gates": results}
        return ("fail" if problems else "pass"), {"gates": results, "failed": problems}


def _report(self: PortRunner, target_name: str, results: list[StageResult]) -> str:
    lines = [f"# {self.spec.title} → {target_name}", "",
             f"- spec：`{self.spec.path}`",
             f"- 家族：{self.spec.family} / 数据政策：{self.spec.data.get('policy')}",
             f"- 工作目录：`{self.work_root}`",
             "- 整游戏行为：未测试；真机：未测试；发布资格：禁止", "",
             "| 阶段 | 状态 | 用时 | 说明 |", "|---|---|---:|---|"]
    for r in results:
        detail = r.detail
        note = detail.get("reason") or detail.get("artifact") or detail.get("path") or ""
        if detail.get("cached"):
            note = "内容核验后复用 " + str(note)
        elif detail.get("cache_disabled"):
            note = detail["cache_disabled"]
        if isinstance(note, str) and len(note) > 80:
            note = "…" + note[-79:]
        lines.append(f"| {r.id} | {r.status} | {r.seconds:.1f}s | {note} |")
    verify = next((r for r in results if r.id == "verify" and r.detail.get("gates")), None)
    if verify:
        lines += ["", "| 闸门 | 状态 |", "|---|---|"]
        for gate_id, outcome in verify.detail["gates"].items():
            lines.append(f"| {gate_id} | {outcome['status']} |")
    lines.append("")
    return "\n".join(lines)
