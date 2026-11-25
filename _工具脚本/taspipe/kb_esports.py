# -*- coding: utf-8 -*-
"""电竞结构化事实库（阶段一第2–3天）。权威规格 = 根目录 全域游戏知识库与电竞落地_实施计划_2026-11-20.md。

SQLite 主库 + 不可变原始快照 + JSON Pointer 字段级证据。
权限闸门：source_policy 五维任一 denied 拦；automated_access 非 allowed 不采。
探针隔离：ES_DIR/DB_PATH/SNAP_DIR 可 patch；闸门跑完反查真实件未被写。
"""
import hashlib
import json
import re
import sqlite3
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .schema import SchemaError

ES_DIR = Path(__file__).resolve().parent / "游戏包" / "电竞事实库"
DB_PATH = ES_DIR / "facts_v1.db"
SNAP_DIR = ES_DIR / "snapshots"
SCHEMA_SQL = ES_DIR / "schema_v3.sql"
POLICY_JSON = ES_DIR / "source_policy_v1.json"

DD_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
DD_CDN = "https://ddragon.leagueoflegends.com/cdn/{version}/data/{lang}/{kind}.json"
DD_ENTITY_TYPE = {"champion": "game_character", "item": "game_item",
                  "summoner": "game_spell"}
DD_ATTRIBUTE = {"champion": "实体身份（名称/称号/标签）",
                "item": "装备静态资料（名称/说明/标签/售价）",
                "summoner": "召唤师技能静态资料（名称/说明/冷却/范围/需求等级）"}
# zh_CN champion 的 name/title 与 en 相反；item/summoner 固定使用 name。
DD_NAME_FIELD = {"zh_CN": ("title", "name")}
PERM5 = ("automated_access", "local_retention", "commercial_use",
         "quotation", "redistribution")


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _connect(db_path=None):
    con = sqlite3.connect(db_path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _connect_readonly(db_path=None):
    """查询臂只读打开；绝不创建缺失库，也不给自动问答留写入口。"""
    p = Path(db_path or DB_PATH).resolve()
    con = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _migrate_v2_to_v3(con):
    con.execute("pragma foreign_keys=off")
    try:
        con.execute("begin immediate")
        con.execute(
            "create table entity_v3("
            "entity_id text primary key,entity_type text not null check(entity_type in "
            "('person','account','club','division','competition','game_character',"
            "'game_item','game_spell')),game_id text,canonical_name text not null)")
        con.execute("insert into entity_v3 select * from entity")
        con.execute("drop table entity")
        con.execute("alter table entity_v3 rename to entity")
        con.execute("delete from schema_meta")
        con.execute("insert into schema_meta values(?,?,?)",
                    ("v3", "2026-11-24",
                     "全域游戏知识库与电竞落地_实施计划_2026-11-20.md §2.3（静态实体类型扩展）"))
        bad = con.execute("pragma foreign_key_check").fetchall()
        if bad:
            raise SchemaError(f"v2→v3 迁移后外键异常：{len(bad)} 行")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.execute("pragma foreign_keys=on")


def init_db(db_path=None):
    """幂等建库；v2 在单事务内迁移到 v3，冻结的 v2 文件不修改。"""
    p = Path(db_path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = _connect(p)
    try:
        has = con.execute("select name from sqlite_master where type='table' "
                          "and name='schema_meta'").fetchone()
        if has:
            ver = con.execute("select schema_version from schema_meta").fetchone()[0]
            if ver == "v2":
                _migrate_v2_to_v3(con)
            elif ver != "v3":
                raise SchemaError(f"库 schema 版本 {ver} 与冻结件 v3 不符；"
                                  "v1业务ID主键缺陷须先迁移 v2，走集成负责人串行合并")
        else:
            con.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
        pol = json.loads(POLICY_JSON.read_text(encoding="utf-8"))
        for s in pol["sources"]:
            con.execute(
                "insert or ignore into source_policy(source_id,terms_url,checked_at,"
                "purpose,automated_access,local_retention,commercial_use,quotation,"
                "redistribution,authorization_ref,note) values(?,?,?,?,?,?,?,?,?,?,?)",
                (s["source_id"], s.get("terms_url"), s.get("checked_at"),
                 s.get("batch"), s["automated_access"], s["local_retention"],
                 s["commercial_use"], s["quotation"], s["redistribution"],
                 s.get("authorization_ref"), s.get("note")))
        con.commit()
        return p
    finally:
        con.close()


def _policy_gate(con, source_id):
    row = con.execute("select * from source_policy where source_id=?",
                      (source_id,)).fetchone()
    if row is None:
        raise SchemaError(f"来源 {source_id} 未登记权限，先入 source_policy")
    for k in PERM5:
        if row[k] == "denied":
            raise SchemaError(f"来源 {source_id} 权限 {k}=denied，拦截（{row['note'] or ''}）")
    if row["automated_access"] != "allowed":
        raise SchemaError(f"来源 {source_id} automated_access={row['automated_access']}"
                          "（非 allowed），自动采集待核不进生产")


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "kb-esports-ingest/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _load(rel, offline_dir):
    if offline_dir is not None:
        return (Path(offline_dir) / rel).read_bytes()
    return _fetch("https://ddragon.leagueoflegends.com/" + rel
                  if not rel.startswith("http") else rel)


def import_ddragon(version=None, lang="zh_CN", kinds=("champion",),
                   db_path=None, snap_dir=None, offline_dir=None):
    """固定版本导入：快照不可变 + 实体/别名 + JSON Pointer 证据。重复导入不增殖。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", lang or ""):
        raise SchemaError("locale 只能含字母、数字、下划线和连字符")
    if not kinds or len(set(kinds)) != len(kinds):
        raise SchemaError("kinds 不能为空或重复")
    unknown = [k for k in kinds if k not in DD_ENTITY_TYPE]
    if unknown:
        raise SchemaError(f"不支持的 Data Dragon 类型：{unknown}；可选 {sorted(DD_ENTITY_TYPE)}")
    init_db(db_path)
    con = _connect(db_path)
    snap_root = Path(snap_dir or SNAP_DIR)
    try:
        _policy_gate(con, "E02")
        versions = json.loads(_load("api/versions.json", offline_dir))
        if version is None:
            version = versions[0]
        if version not in versions:
            raise SchemaError(f"版本 {version} 不在官方版本列表，不许用 latest 别名归档")
        out = {"source_id": "E02", "version": version, "lang": lang,
               "skipped": [], "snapshots_new": 0, "entities_new": 0,
               "evidence_new": 0, "aliases_new": 0}
        for kind in kinds:
            rel = f"cdn/{version}/data/{lang}/{kind}.json"
            url = DD_CDN.format(version=version, lang=lang, kind=kind)
            raw = _load(rel, offline_dir) if offline_dir is not None else _fetch(url)
            digest = _sha(raw)
            obj = json.loads(raw)
            if obj.get("version") != version:
                raise SchemaError(f"响应内版本 {obj.get('version')} 与钉住版本 {version} 不符")
            if obj.get("type") != kind or not isinstance(obj.get("data"), dict):
                raise SchemaError(f"{kind} 快照 type/data 形状不符，拒收")
            sp = snap_root / "E02" / version / f"{kind}.{lang}.json"
            sp.parent.mkdir(parents=True, exist_ok=True)
            if sp.exists():
                if _sha(sp.read_bytes()) != digest:
                    raise SchemaError(f"同版本快照内容变化 {sp}，须人工核，不许静默覆盖")
            else:
                sp.write_bytes(raw)
            snap_id = f"E02:{version}:{kind}:{lang}:{digest[:12]}"
            cur = con.execute("insert or ignore into source_snapshot(snapshot_id,"
                              "source_id,original_url,source_record_id,fetched_at,"
                              "content_sha256,storage_ref,parser_version,fetch_status) "
                              "values(?,?,?,?,datetime('now'),?,?,?,?)",
                              (snap_id, "E02", url, version, digest,
                               str(sp), "kb_esports/v2", "ok"))
            out["snapshots_new"] += cur.rowcount
            pname_f, epithet_f = (DD_NAME_FIELD.get(lang, ("name", "title"))
                                  if kind == "champion" else ("name", "title"))
            for key, cobj in obj["data"].items():
                pname = cobj.get(pname_f)
                epithet = cobj.get(epithet_f)
                if not pname:
                    out["skipped"].append(f"{kind}/{key}: 缺 {pname_f}，不造空实体")
                    continue
                ent_id = f"lol:{kind}:{key}"
                cur = con.execute("insert or ignore into entity(entity_id,entity_type,"
                                  "game_id,canonical_name) values(?,?,?,?)",
                                  (ent_id, DD_ENTITY_TYPE[kind], "lol", pname))
                out["entities_new"] += cur.rowcount
                con.execute("insert or ignore into external_id(entity_id,provider,"
                            "external_id,review_status) values(?,?,?,?)",
                            (ent_id, "ddragon", key, "verified"))
                for alias, alang in ((cobj.get("id"), "en"),
                                     (epithet, lang)):
                    if not alias:
                        continue
                    aid = _sha(f"{ent_id}|{alias}|{alang}".encode())[:16]
                    cur = con.execute("insert or ignore into entity_alias(alias_id,"
                                      "entity_id,alias,language) values(?,?,?,?)",
                                      (aid, ent_id, alias, alang))
                    out["aliases_new"] += cur.rowcount
                canon = json.dumps(cobj, ensure_ascii=False, sort_keys=True)
                if json.loads(canon) != cobj:
                    raise SchemaError(f"{key} 证据序列化往返不一致，拒收")
                locator = f"/data/{key}"
                chash = _sha(canon.encode())
                ev_id = _sha(f"{snap_id}|{locator}|{chash}".encode())[:16]
                cur = con.execute("insert or ignore into evidence_block(evidence_id,"
                                  "snapshot_id,locator_type,locator,exact_text_or_value,"
                                  "content_hash,language,authority_scope,"
                                  "verification_status,retraction_status) "
                                  "values(?,?,?,?,?,?,?,?,?,?)",
                                  (ev_id, snap_id, "json_pointer", locator, canon,
                                   chash, lang, "official_static_data", "verified",
                                   "active"))
                out["evidence_new"] += cur.rowcount
                con.execute("insert or ignore into fact_support(row_version_id,"
                            "field_name,evidence_id,relation,review_status) "
                            "values(?,?,?,?,?)",
                            (ent_id, "canonical_name", ev_id, "states", "verified"))
        con.commit()
        return out
    finally:
        con.close()


def query_static(name, kind="champion", patch=None, db_path=None):
    """Data Dragon 静态实体查询：版本钉硬过滤 + 恰 1 块 selected_evidence。"""
    if kind not in DD_ENTITY_TYPE:
        raise SchemaError(f"不支持的静态实体类型 {kind}")
    con = _connect_readonly(db_path)
    try:
        rows = [r for r in _resolve(con, name, DD_ENTITY_TYPE[kind]) if r["game_id"] == "lol"]
        base = {"q": name, "query_conditions": {"patch": patch, "kind": kind},
                "retrieval_hits": []}
        if not rows:
            return {**base, "status": "miss", "selected_evidence": [],
                    "reason_code": "not_collected",
                    "reason": "库内没有该实体（不是『不存在』，只是本地没收集）"}
        if len(rows) > 1:
            return {**base, "status": "inconclusive", "selected_evidence": [],
                    "reason_code": "needs_clarification",
                    "candidates": [r["canonical_name"] for r in rows]}
        ent = rows[0]
        ev = con.execute(
            "select ev.*, ss.source_record_id as patch, ss.content_sha256 as snap_sha, "
            "ss.storage_ref from fact_support fs "
            "join evidence_block ev on ev.evidence_id=fs.evidence_id "
            "join source_snapshot ss on ss.snapshot_id=ev.snapshot_id "
            "where fs.row_version_id=? and fs.field_name='canonical_name' "
            "and fs.review_status='verified' and ev.retraction_status='active' "
            "order by ss.fetched_at desc, ev.evidence_id", (ent["entity_id"],)).fetchall()
        if patch is not None:
            ev = [e for e in ev if e["patch"] == patch]
        if not ev:
            return {**base, "status": "miss", "selected_evidence": [],
                    "reason_code": "version_not_collected",
                    "reason": f"补丁 {patch} 的快照未导入（现有版本见 source_snapshot）"}
        e = ev[0]
        cobj = json.loads(e["exact_text_or_value"])
        pname_f, epithet_f = (DD_NAME_FIELD.get(e["language"], ("name", "title"))
                              if kind == "champion" else ("name", "title"))
        if kind == "champion":
            value = {"name": cobj.get(pname_f), "title": cobj.get(epithet_f),
                     "tags": cobj.get("tags")}
            answer = (f"截至补丁 {e['patch']}（Data Dragon {e['language']}）："
                      f"{cobj.get(pname_f)}，称号「{cobj.get(epithet_f)}」。")
        elif kind == "item":
            value = {"name": cobj.get("name"), "description": cobj.get("description"),
                     "plaintext": cobj.get("plaintext"), "tags": cobj.get("tags"),
                     "gold": cobj.get("gold")}
            detail = cobj.get("plaintext") or cobj.get("description")
            answer = (f"截至补丁 {e['patch']}（Data Dragon {e['language']}）："
                      f"{cobj.get('name')}。{detail or '静态资料见证据'}")
            gold = cobj.get("gold")
            price = gold.get("total") if isinstance(gold, dict) else gold
            if price not in (None, "", 0, "0"):
                answer += f" 售价 {price} 金币。"
        else:
            cooldown = cobj.get("cooldownBurn") or cobj.get("cooldown")
            rng = cobj.get("rangeBurn") or cobj.get("range")
            value = {"name": cobj.get("name"), "description": cobj.get("description"),
                     "cooldown": cooldown, "range": rng,
                     "summonerLevel": cobj.get("summonerLevel")}
            answer = (f"截至补丁 {e['patch']}（Data Dragon {e['language']}）："
                      f"{cobj.get('name')}。{cobj.get('description') or '静态资料见证据'}")
            if cooldown not in (None, ""):
                answer += f" 冷却 {cooldown}。"
            if rng not in (None, ""):
                answer += f" 范围 {rng}。"
        claim = {"subject": ent["canonical_name"],
                 "attribute": DD_ATTRIBUTE[kind], "value": value,
                 "conditions": {"patch": e["patch"], "lang": e["language"],
                                "fact_kind": "静态数据，无现状时效声明"}}
        return {**base, "status": "pass", "reason_code": "evidence_bound",
                "claim": claim, "answer_text": answer,
                "selected_evidence": [_ev_dict(e)],
                "dataset_revision": f"ddragon:{e['patch']}:{e['language']}"}
    finally:
        con.close()


def query_champion(name, patch=None, db_path=None):
    return query_static(name, "champion", patch, db_path)


# ---- query_auto 窄适配器：只接唯一 LOL 静态实体 + 静态属性问句 ----
_STATIC_KIND_BY_TYPE = {"game_character": "champion", "game_item": "item",
                        "game_spell": "summoner"}
_STATIC_ATTRIBUTE_PATTERNS = (
    ("title", re.compile(r"称号|(?<![A-Za-z])title(?![A-Za-z])", re.I)),
    ("name", re.compile(r"名称|名字|姓名|(?<![A-Za-z])name(?![A-Za-z])", re.I)),
    ("tags", re.compile(r"标签|类型|(?<![A-Za-z])tags?(?![A-Za-z])", re.I)),
    ("description", re.compile(r"说明|描述|效果|(?<![A-Za-z])description(?![A-Za-z])", re.I)),
    ("price", re.compile(r"售价|价格|多少钱|花费|(?<![A-Za-z])(?:cost|price)(?![A-Za-z])", re.I)),
    ("cooldown", re.compile(r"冷却(?:时间)?|(?<![A-Za-z])cooldown(?![A-Za-z])", re.I)),
    ("range", re.compile(r"范围|射程|(?<![A-Za-z])range(?![A-Za-z])", re.I)),
    ("level", re.compile(r"需求等级|解锁等级|(?<![A-Za-z])summoner\s+level(?![A-Za-z])", re.I)),
)
_STATIC_ATTRIBUTE_KINDS = {
    "title": {"champion"}, "name": {"champion", "item", "summoner"},
    "tags": {"champion", "item"}, "description": {"item", "summoner"},
    "price": {"item"}, "cooldown": {"summoner"}, "range": {"summoner"},
    "level": {"summoner"},
}
_STATIC_KIND_RE = {
    "champion": re.compile(r"英雄|(?<![A-Za-z])(?:champion|hero)(?![A-Za-z])", re.I),
    "item": re.compile(r"装备|(?<![A-Za-z])items?(?![A-Za-z])", re.I),
    "summoner": re.compile(r"召唤师技能|召唤技能|(?<![A-Za-z])summoner\s+spell(?![A-Za-z])", re.I),
}
_LOL_CONTEXT_RE = re.compile(
    r"英雄联盟|(?<![A-Za-z0-9])lol(?![A-Za-z0-9])|league\s+of\s+legends", re.I)
_PATCH_TOKEN = r"\d+\.\d+(?:\.\d+)?"
_PATCH_PREFIX_RE = re.compile(
    r"(?:\bpatch\b|补丁|版本)\s*(?:[=:：]\s*)?(" + _PATCH_TOKEN + r")", re.I)
_PATCH_SUFFIX_RE = re.compile(r"(" + _PATCH_TOKEN + r")\s*(?:版本|补丁|patch)", re.I)
_ENTITY_JOIN_RE = re.compile(r"和|与|及|、|(?<![A-Za-z0-9])and(?![A-Za-z0-9])", re.I)


def _static_alias_hit(q, alias, allow_short):
    if not alias:
        return False
    if alias.isascii():
        if not allow_short and len(alias) < 4:
            return False
        return re.search(r"(?<![A-Za-z0-9_])" + re.escape(alias)
                         + r"(?![A-Za-z0-9_])", q, re.I) is not None
    if not allow_short and len(alias) < 2:
        return False
    return alias in q


def _static_attribute_value(attribute, value):
    if attribute == "description":
        return value.get("plaintext") or value.get("description")
    if attribute == "price":
        gold = value.get("gold")
        return gold.get("total") if isinstance(gold, dict) else gold
    if attribute == "level":
        return value.get("summonerLevel")
    return value.get(attribute)


def query_auto_static(q, game=None, revision=None, platform=None, db_path=None):
    """query_auto 的零生成式窄臂；不适用返回 None，由原文本路由继续。

    实体只从 SQLite canonical_name/entity_alias/external_id 读取，绝不内嵌英雄名单。
    显式 game/revision/platform 不兼容时返回 None，保留原过滤优先级。
    """
    if not isinstance(q, str) or not q.strip():
        return None
    if game:
        gid = re.sub(r"[\s_-]+", "", str(game)).lower()
        if gid not in ("lol", "leagueoflegends", "英雄联盟"):
            return None
    if platform and str(platform).strip().upper() != "ANY":
        return None
    if revision and not re.fullmatch(_PATCH_TOKEN, str(revision).strip()):
        return None

    qn = unicodedata.normalize("NFKC", q).strip()
    attr_hits = sorted((m.start(), attr, m.end())
                       for attr, rx in _STATIC_ATTRIBUTE_PATTERNS
                       for m in rx.finditer(qn))
    attrs = list(dict.fromkeys(attr for _, attr, _ in attr_hits))
    if not attrs:
        return None
    allowed_kinds = set(_STATIC_KIND_BY_TYPE.values())
    for attr in attrs:
        allowed_kinds &= _STATIC_ATTRIBUTE_KINDS[attr]
    explicit_kind = next((kind for kind, rx in _STATIC_KIND_RE.items()
                          if rx.search(qn)), None)
    if explicit_kind:
        allowed_kinds &= {explicit_kind}
    if not allowed_kinds:
        return None

    def base(status, reason_code, reason, candidates=None):
        out = {"q": q, "game": game, "revision": revision, "platform": platform,
               "want": [], "status": status, "reason_code": reason_code,
               "reason": reason, "backend": "esports_sqlite",
               "retrieval": "esports_sqlite", "retrieval_hits": [], "hits": [],
               "selected_evidence": [],
               "counts": {"candidates": len(candidates or []), "hits": 0,
                          "answerable": 0, "strong": 0},
               "query_conditions": {"kind": explicit_kind, "attribute": attrs,
                                    "patch": revision}}
        if candidates:
            out["candidates"] = candidates
        return out

    try:
        con = _connect_readonly(db_path)
    except (sqlite3.Error, OSError):
        return None
    try:
        names = con.execute(
            "select e.entity_id,e.entity_type,e.canonical_name,n.alias,n.name_source "
            "from entity e join ("
            " select entity_id,canonical_name as alias,'canonical' as name_source "
            " from entity where game_id='lol'"
            " union select entity_id,alias,'alias' from entity_alias"
            " union select entity_id,external_id,'external_id' from external_id"
            " where provider='ddragon'"
            ") n on n.entity_id=e.entity_id"
            " where e.game_id='lol' and e.entity_type in "
            "('game_character','game_item','game_spell')"
            " order by length(n.alias) desc,n.alias collate nocase").fetchall()
        lol_context = bool(_LOL_CONTEXT_RE.search(qn)) or bool(game)
        context = lol_context or explicit_kind is not None
        mentions = []
        for row in names:
            kind = _STATIC_KIND_BY_TYPE[row["entity_type"]]
            if kind not in allowed_kinds or not row["alias"]:
                continue
            if kind == "summoner" and not context and row["alias"].isascii():
                continue
            if kind == "item" and not context and len(row["alias"]) < 3:
                continue
            if not _static_alias_hit(qn, row["alias"], context):
                continue
            m = re.search(r"(?<![A-Za-z0-9_])" + re.escape(row["alias"])
                          + r"(?![A-Za-z0-9_])", qn, re.I) \
                if row["alias"].isascii() else re.search(re.escape(row["alias"]), qn)
            if m:
                mentions.append({"start": m.start(), "end": m.end(),
                                 "alias": row["alias"], "kind": kind,
                                 "name_source": row["name_source"]})
        if not mentions:
            # 未唯一识别实体时适配器不成立，继续原自动路由；不得把未知实体判成库内缺料。
            return None

        resolved = {}
        cache = {}
        for mention in mentions:
            key = (mention["alias"], mention["kind"])
            if key not in cache:
                cache[key] = [r for r in _resolve(con, mention["alias"],
                                                  DD_ENTITY_TYPE[mention["kind"]])
                              if r["game_id"] == "lol"]
            for row in cache[key]:
                resolved[row["entity_id"]] = row
        candidate_names = sorted({r["canonical_name"] for r in resolved.values()})
        if len(resolved) != 1:
            return base("inconclusive", "needs_clarification",
                        "问句命中多个 SQLite 静态实体，单实体适配器不合并猜测",
                        candidate_names)
        ent = next(iter(resolved.values()))
        # 唯一已知实体 + 连接词仍可能藏着未收录实体；只有同实体双别名并列才放行。
        subject = qn[:min(start for start, _, _ in attr_hits)]
        own_mentions = [m for m in mentions if m["start"] < len(subject)]
        if _ENTITY_JOIN_RE.search(subject) and len({(m["start"], m["end"])
                                                   for m in own_mentions}) < 2:
            return base("inconclusive", "needs_clarification",
                        "问句含多个实体连接词，但只唯一识别到一个静态实体；不猜另一实体",
                        candidate_names)

        if revision is not None:
            patch = str(revision).strip()
        else:
            patches = list(dict.fromkeys(_PATCH_PREFIX_RE.findall(qn)
                                         + _PATCH_SUFFIX_RE.findall(qn)))
            if len(patches) > 1:
                return base("inconclusive", "conflicting_version",
                            "问句出现多个不同补丁，拒绝任选最新版顶包", candidate_names)
            patch = patches[0] if patches else None
        kind = _STATIC_KIND_BY_TYPE[ent["entity_type"]]
        raw = query_static(ent["canonical_name"], kind, patch, db_path)
        if raw.get("status") != "pass":
            out = base(raw.get("status", "miss"), raw.get("reason_code", "not_collected"),
                       raw.get("reason") or "静态事实未放行", candidate_names)
            out["query_conditions"].update({"patch": patch, "kind": kind})
            out["static_entity"] = {"entity_id": ent["entity_id"],
                                    "entity_type": ent["entity_type"], "game_id": "lol",
                                    "canonical_name": ent["canonical_name"],
                                    "matched_alias": max(mentions, key=lambda m: len(m["alias"]))["alias"]}
            if raw.get("candidates"):
                out["candidates"] = raw["candidates"]
            return out

        selected = raw.get("selected_evidence") or []
        claim = raw.get("claim") or {}
        value = claim.get("value") or {}
        actual_patch = (claim.get("conditions") or {}).get("patch")
        if len(selected) != 1 or selected[0].get("locator_type") != "json_pointer" \
                or not str(selected[0].get("locator") or "").startswith("/data/") \
                or not raw.get("dataset_revision") or not actual_patch:
            return base("inconclusive", "evidence_contract_error",
                        "静态查询未满足唯一 JSON Pointer 证据契约，拒绝放行", candidate_names)
        missing = [a for a in attrs if _static_attribute_value(a, value) in (None, "", [], {})]
        if missing:
            out = base("miss", "attribute_not_collected",
                       "本地静态快照未收集所问属性：" + "、".join(missing), candidate_names)
            out["query_conditions"].update({"patch": patch, "kind": kind})
            out["static_entity"] = {"entity_id": ent["entity_id"],
                                    "entity_type": ent["entity_type"], "game_id": "lol",
                                    "canonical_name": ent["canonical_name"]}
            return out

        answer = str(raw.get("answer_text") or "")
        additions = []
        if "tags" in attrs:
            additions.append("标签：" + "、".join(map(str, value.get("tags") or [])) + "。")
        if "price" in attrs:
            price = _static_attribute_value("price", value)
            if f"售价 {price}" not in answer:
                additions.append(f"售价 {price} 金币。")
        if "level" in attrs:
            additions.append(f"需求等级 {_static_attribute_value('level', value)}。")
        if additions:
            answer = answer.rstrip() + " " + " ".join(additions)
        answer = answer.replace(f"截至补丁 {actual_patch}", f"截至补丁{actual_patch}", 1)
        if f"截至补丁{actual_patch}" not in answer:
            return base("inconclusive", "evidence_contract_error",
                        "静态答案缺少实际补丁条件，拒绝放行", candidate_names)

        ev = selected[0]
        projection = {**ev, "chunk_id": ev["evidence_id"], "score": 1.0,
                      "source_id": ev["snapshot_id"].split(":", 1)[0],
                      "status": "verified_read", "authority": "authoritative",
                      "revision": actual_patch, "game_id": "lol", "platform": "ANY",
                      "revision_match": True, "heading": ent["canonical_name"],
                      "matched_terms": [max(mentions, key=lambda m: len(m["alias"]))["alias"]],
                      "snippet": answer, "answerability": {"answerable": True},
                      "backend": "esports_sqlite", "dataset_revision": raw["dataset_revision"]}
        out = base("pass", raw.get("reason_code", "evidence_bound"),
                   raw.get("reason") or "SQLite 静态事实唯一证据放行", candidate_names)
        out.update({"claim": claim, "answer_text": answer,
                    "selected_evidence": [projection], "hits": [projection],
                    "dataset_revision": raw["dataset_revision"],
                    "counts": {"candidates": 1, "hits": 1, "answerable": 1, "strong": 1},
                    "authority_warnings": [],
                    "query_conditions": {"patch": patch, "resolved_patch": actual_patch,
                                         "kind": kind, "attribute": attrs},
                    "static_entity": {"entity_id": ent["entity_id"],
                                      "entity_type": ent["entity_type"], "game_id": "lol",
                                      "canonical_name": ent["canonical_name"],
                                      "matched_alias": max(mentions, key=lambda m: len(m["alias"]))["alias"]}})
        return out
    except (sqlite3.Error, OSError):
        return None
    finally:
        con.close()


# ---- 阶段一第3–5天：时间/补丁硬过滤（双时间选择器，规格 §2.4 / §4.3） ----

_FILTER_COLS = {
    "membership": {"person_id", "team_id", "membership_type", "competition_scope"},
    "series": {"series_id", "logical_record_id", "stage_id"},
    "transfer_event": {"person_id", "event_status"},
    "game_result": {"game_result_id", "series_id", "patch_id"},
}


def select_versions(con, table, where=None, knowledge_as_of=None):
    """身份+知识时间硬过滤，每个 logical_record_id 取最新可见版本。
    knowledge_as_of=None → 当前知识（record_status='active'）；
    给值则回放 recorded_at<=t 且未被 t 前修订取代的版本（纠错回放）。
    现实适用期（valid_*）由 valid_at 判，本函数不代做。"""
    if table not in _FILTER_COLS:
        raise SchemaError(f"表 {table} 不在双时间选择器白名单")
    conds, params = [], []
    for k, v in (where or {}).items():
        if k not in _FILTER_COLS[table]:
            raise SchemaError(f"过滤列 {k} 不在 {table} 白名单")
        conds.append(f"{k}=?")
        params.append(v)
    if knowledge_as_of is None:
        conds.append("record_status='active'")
    else:
        conds += ["recorded_at<=?", "(superseded_at is null or superseded_at>?)"]
        params += [knowledge_as_of, knowledge_as_of]
    rows = con.execute(f"select * from {table} where {' and '.join(conds)}",
                       params).fetchall()
    best = {}
    for r in rows:
        k = r["logical_record_id"]
        cur = best.get(k)
        if cur is None or (r["recorded_at"], r["row_version_id"]) > \
                (cur["recorded_at"], cur["row_version_id"]):
            best[k] = r
    return list(best.values())


def valid_at(row, as_of):
    """现实适用期三态：True=可证有效 / False=可证无效 / 'unknown_end'=起点有效但结束未知。
    区间左闭右开 [valid_from, valid_to)；valid_to=NULL 只有 end_bound_kind='open'
    才当开放区间，'unknown' 不许冒充开放（§2.3）。"""
    vf, vt = row["valid_from"], row["valid_to"]
    if vf is None or row["start_bound_kind"] == "unknown" or vf > as_of:
        return False
    if vt is None:
        return True if row["end_bound_kind"] == "open" else "unknown_end"
    return as_of < vt


def _resolve(con, name, entity_type=None):
    conds = ["(lower(e.canonical_name)=lower(?) or e.entity_id in "
             "(select entity_id from entity_alias where lower(alias)=lower(?)) or "
             "e.entity_id in (select entity_id from external_id "
             "where provider='ddragon' and lower(external_id)=lower(?)))"]
    params = [name, name, name]
    if entity_type:
        conds.append("e.entity_type=?")
        params.append(entity_type)
    return con.execute(f"select e.* from entity e where {' and '.join(conds)}",
                       params).fetchall()


def _bound_evidence(con, row_version_id, field):
    rows = con.execute(
        "select ev.*, ss.content_sha256 as snap_sha, ss.storage_ref "
        "from fact_support fs join evidence_block ev on ev.evidence_id=fs.evidence_id "
        "join source_snapshot ss on ss.snapshot_id=ev.snapshot_id "
        "where fs.row_version_id=? and fs.field_name=? and fs.review_status='verified' "
        "and ev.retraction_status='active' order by ev.evidence_id",
        (row_version_id, field)).fetchall()
    return rows[0] if rows else None


def _ev_dict(e):
    return {"evidence_id": e["evidence_id"], "snapshot_id": e["snapshot_id"],
            "locator_type": e["locator_type"], "locator": e["locator"],
            "content_hash": e["content_hash"], "snapshot_sha256": e["snap_sha"],
            "storage_ref": e["storage_ref"]}


def _now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def query_membership(person, as_of=None, knowledge_as_of=None, db_path=None):
    """阵容归属（状态类事实）。as_of=None=问现状：只有可证开放/未到期区间才 pass，
    旧名单或结束未知 → 拒绝冒充现状（stale_state），旧料只作历史展示（§2.4）。
    已官宣未生效的转会只进附注，绝不切换归属（announced_at≠effective_at，§4.3）。"""
    con = _connect(db_path)
    try:
        base = {"q": person, "query_conditions": {"as_of": as_of,
                "knowledge_as_of": knowledge_as_of}, "retrieval_hits": []}
        ents = _resolve(con, person, entity_type="person")
        if not ents:
            return {**base, "status": "miss", "selected_evidence": [],
                    "reason_code": "not_collected",
                    "reason": "库内没有该人物实体（不是『不存在』，只是本地没收集）"}
        if len(ents) > 1:
            return {**base, "status": "inconclusive", "selected_evidence": [],
                    "reason_code": "needs_clarification",
                    "candidates": [e["canonical_name"] for e in ents]}
        ent = ents[0]
        at = as_of if as_of is not None else _now_utc()
        rows = select_versions(con, "membership",
                               {"person_id": ent["entity_id"]}, knowledge_as_of)
        valid = sorted([r for r in rows if valid_at(r, at) is True],
                       key=lambda r: (r["membership_type"], r["row_version_id"]))
        if not valid:
            hist = [r for r in rows if r["valid_from"] and r["valid_from"] <= at]
            if as_of is None and hist:
                known = max(r["valid_from"] for r in hist)
                return {**base, "status": "inconclusive", "selected_evidence": [],
                        "reason_code": "stale_state",
                        "answer_text": f"无法确认当前阵容；已有资料仅能证明截至 {known} "
                                       f"的 {ent['canonical_name']} 归属记录。",
                        "historical_only": [
                            {"team_id": r["team_id"], "valid_from": r["valid_from"],
                             "valid_to": r["valid_to"],
                             "end_bound_kind": r["end_bound_kind"]} for r in hist]}
            return {**base, "status": "miss", "selected_evidence": [],
                    "reason_code": "no_record_valid_at",
                    "reason": f"没有可证在 {at} 有效的归属记录"}
        if len({r["team_id"] for r in valid}) > 1:
            return {**base, "status": "inconclusive", "selected_evidence": [],
                    "reason_code": "conflicting_membership",
                    "reason": "多条有效记录指向不同队伍（合同/注册/租借须分开核）",
                    "candidates": sorted({r["team_id"] for r in valid})}
        r = valid[0]
        ev = _bound_evidence(con, r["row_version_id"], "team_id")
        if ev is None:
            return {**base, "status": "inconclusive", "selected_evidence": [],
                    "reason_code": "no_evidence_bound",
                    "reason": "该记录版本没有已核验的字段级证据，不发 pass"}
        team = con.execute("select canonical_name from entity where entity_id=?",
                           (r["team_id"],)).fetchone()[0]
        trs = select_versions(con, "transfer_event",
                              {"person_id": ent["entity_id"],
                               "event_status": "announced"}, knowledge_as_of)
        notes = []
        for t in trs:
            if t["effective_at"] is None or t["effective_at"] > at:
                to = con.execute("select canonical_name from entity where entity_id=?",
                                 (t["to_team_id"],)).fetchone()[0]
                notes.append(f"另有官宣（{t['announced_at']}）将加盟{to}，"
                             f"生效时间 {t['effective_at'] or '未定'}，尚未生效，"
                             "不改变当前归属。")
        answer = (f"截至 {at}：{ent['canonical_name']} 效力于 {team}"
                  f"（{r['membership_type']}）。" + "".join(notes))
        claim = {"subject": ent["canonical_name"], "attribute": "队伍归属",
                 "value": {"team_id": r["team_id"], "team": team,
                           "membership_type": r["membership_type"]},
                 "conditions": {"as_of": at, "knowledge_as_of": knowledge_as_of,
                                "fact_kind": "状态类，仅证明有效区间内的归属"}}
        return {**base, "status": "pass", "reason_code": "evidence_bound",
                "claim": claim, "answer_text": answer,
                "selected_evidence": [_ev_dict(ev)],
                "dataset_revision": r["row_version_id"]}
    finally:
        con.close()


def query_series(series_id, knowledge_as_of=None, db_path=None):
    """赛果=历史事件，不因年代久远失效；只认 completed 且有 winner_id。
    未决/取消/行政判胜显式报状态，不从比分推断赢家（§2.3）。
    knowledge_as_of 回放本库当时知道的版本（修订链，§2.4）。"""
    con = _connect(db_path)
    try:
        base = {"q": series_id, "query_conditions": {"knowledge_as_of": knowledge_as_of},
                "retrieval_hits": []}
        rows = select_versions(con, "series", {"series_id": series_id}, knowledge_as_of)
        if not rows:
            return {**base, "status": "miss", "selected_evidence": [],
                    "reason_code": "not_collected",
                    "reason": "库内没有该系列赛记录（或该知识时点尚未入库）"}
        r = rows[0]
        if r["status"] != "completed" or not r["winner_id"]:
            return {**base, "status": "inconclusive", "selected_evidence": [],
                    "reason_code": "result_not_final",
                    "answer_text": f"该系列赛状态为 {r['status']}，"
                                   "没有可证的最终赢家；不从比分推断结果。",
                    "record_detail": {"status": r["status"],
                                      "result_method": r["result_method"],
                                      "score_a": r["score_a"], "score_b": r["score_b"]}}
        ev = _bound_evidence(con, r["row_version_id"], "winner_id")
        if ev is None:
            return {**base, "status": "inconclusive", "selected_evidence": [],
                    "reason_code": "no_evidence_bound",
                    "reason": "该记录版本没有已核验的赢家字段证据，不发 pass"}
        names = {}
        for tid in (r["team_a_id"], r["team_b_id"], r["winner_id"]):
            if tid and tid not in names:
                names[tid] = con.execute(
                    "select canonical_name from entity where entity_id=?",
                    (tid,)).fetchone()[0]
        method = f"（{r['result_method']}）" if r["result_method"] else ""
        answer = (f"{names[r['team_a_id']]} {r['score_a']}:{r['score_b']} "
                  f"{names[r['team_b_id']]}，胜者 {names[r['winner_id']]}{method}。")
        claim = {"subject": series_id, "attribute": "系列赛结果（胜局数）",
                 "value": {"winner_id": r["winner_id"], "score_a": r["score_a"],
                           "score_b": r["score_b"], "score_unit": "series_games",
                           "result_method": r["result_method"]},
                 "conditions": {"knowledge_as_of": knowledge_as_of,
                                "recorded_at": r["recorded_at"],
                                "fact_kind": "历史事件，不因年代久远失效"}}
        return {**base, "status": "pass", "reason_code": "evidence_bound",
                "claim": claim, "answer_text": answer,
                "selected_evidence": [_ev_dict(ev)],
                "dataset_revision": r["row_version_id"]}
    finally:
        con.close()


def patch_for_game(game_result_id, db_path=None):
    """赛事补丁解析：只认 game_result.patch_id（当局记录），
    绝不拿公网最新补丁顶替（§4.3）。返回 None=未记录，调用方须诚实 miss。"""
    con = _connect(db_path)
    try:
        rows = select_versions(con, "game_result", {"game_result_id": game_result_id})
        if not rows or not rows[0]["patch_id"]:
            return None
        return {"patch_id": rows[0]["patch_id"],
                "row_version_id": rows[0]["row_version_id"],
                "source": "game_result.patch_id"}
    finally:
        con.close()


def log_refresh_failure(source_id, url, db_path=None):
    """刷新失败只留痕（fetch_status='error'），绝不更新任何事实的 last_verified_at，
    也不动既有快照（§3.4：抓取失败反而刷新核验时间=必须阻止）。"""
    con = _connect(db_path)
    try:
        sid = f"{source_id}:refresh-error:" \
              f"{_sha((url + _now_utc()).encode())[:12]}"
        con.execute(
            "insert into source_snapshot(snapshot_id,source_id,original_url,"
            "fetched_at,content_sha256,storage_ref,fetch_status) "
            "values(?,?,?,datetime('now'),'','',?)", (sid, source_id, url, "error"))
        con.commit()
        return sid
    finally:
        con.close()