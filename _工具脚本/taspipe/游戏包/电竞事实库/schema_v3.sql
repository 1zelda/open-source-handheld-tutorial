-- 电竞结构化事实库 schema v3（2026-11-24，Data Dragon 静态实体扩展）
-- 权威规格 = 根目录 全域游戏知识库与电竞落地_实施计划_2026-11-20.md §2.3
-- v2→v3 原因：v2 的 entity_type 只允许 game_character，无法按契约保存
--   Data Dragon 的 game_item/game_spell；扩展实体白名单，其余表口径不变。
--   schema_v2.sql 原样冻结留审计，迁移由 kb_esports.init_db 在事务内完成。
-- 口径：外部ID=来源命名空间+字符串；权限=allowed/denied/unknown；
--       双时间=valid_*（现实适用期）vs recorded_at/superseded_at（本库何时知道）。

PRAGMA foreign_keys = ON;

CREATE TABLE schema_meta (
    schema_version TEXT PRIMARY KEY,
    frozen_at      TEXT NOT NULL,
    spec_doc       TEXT NOT NULL
);
INSERT INTO schema_meta VALUES
    ('v3', '2026-11-24', '全域游戏知识库与电竞落地_实施计划_2026-11-20.md §2.3（静态实体类型扩展）');

-- ============ 共用表 ============

CREATE TABLE entity (
    entity_id      TEXT PRIMARY KEY,
    entity_type    TEXT NOT NULL CHECK (entity_type IN
                   ('person','account','club','division','competition','game_character',
                    'game_item','game_spell')),
    game_id        TEXT,
    canonical_name TEXT NOT NULL
);

CREATE TABLE entity_alias (
    alias_id    TEXT PRIMARY KEY,
    entity_id   TEXT NOT NULL REFERENCES entity(entity_id),
    alias       TEXT NOT NULL,
    language    TEXT,
    region      TEXT,
    valid_from  TEXT,
    valid_to    TEXT,
    evidence_id TEXT
);

CREATE TABLE external_id (
    entity_id           TEXT NOT NULL REFERENCES entity(entity_id),
    provider            TEXT NOT NULL,
    external_id         TEXT NOT NULL,
    mapping_evidence_id TEXT,
    review_status       TEXT NOT NULL DEFAULT 'pending'
                        CHECK (review_status IN ('pending','verified','rejected')),
    PRIMARY KEY (provider, external_id)
);

CREATE TABLE source_policy (
    source_id        TEXT PRIMARY KEY,
    terms_url        TEXT,
    terms_revision   TEXT,
    checked_at       TEXT,
    purpose          TEXT,
    automated_access TEXT NOT NULL CHECK (automated_access IN ('allowed','denied','unknown')),
    local_retention  TEXT NOT NULL CHECK (local_retention  IN ('allowed','denied','unknown')),
    commercial_use   TEXT NOT NULL CHECK (commercial_use   IN ('allowed','denied','unknown')),
    quotation        TEXT NOT NULL CHECK (quotation        IN ('allowed','denied','unknown')),
    redistribution   TEXT NOT NULL CHECK (redistribution   IN ('allowed','denied','unknown')),
    retention_days   INTEGER,
    authorization_ref TEXT,
    note             TEXT
);

CREATE TABLE source_snapshot (
    snapshot_id      TEXT PRIMARY KEY,
    source_id        TEXT NOT NULL REFERENCES source_policy(source_id),
    original_url     TEXT,
    source_record_id TEXT,
    published_at     TEXT,
    source_updated_at TEXT,
    fetched_at       TEXT NOT NULL,
    content_sha256   TEXT NOT NULL,
    storage_ref      TEXT NOT NULL,
    parser_version   TEXT,
    fetch_status     TEXT NOT NULL CHECK (fetch_status IN ('ok','empty','error','partial'))
);

CREATE TABLE evidence_block (
    evidence_id        TEXT PRIMARY KEY,
    snapshot_id        TEXT NOT NULL REFERENCES source_snapshot(snapshot_id),
    locator_type       TEXT NOT NULL,
    locator            TEXT NOT NULL,
    exact_text_or_value TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    language           TEXT,
    authority_scope    TEXT,
    derived_from       TEXT,
    verification_status TEXT NOT NULL DEFAULT 'pending'
                       CHECK (verification_status IN ('pending','verified','rejected')),
    retraction_status  TEXT NOT NULL DEFAULT 'active'
                       CHECK (retraction_status IN ('active','retracted','superseded'))
);

-- ============ 双时间列（每条可变化记录共同带） ============
-- valid_*：现实中何时适用；recorded_at/superseded_at：本库何时知道这一版本。
-- announced_at ≠ effective_at；time_precision 不许填午夜伪装精确；
-- valid_to=NULL 必须配 end_bound_kind 区分开放区间与未知结束。
-- 主键=row_version_id：同一逻辑记录（logical_record_id/业务ID）允许多行版本。

CREATE TABLE fact_support (
    row_version_id TEXT NOT NULL,
    field_name     TEXT NOT NULL,
    evidence_id    TEXT NOT NULL REFERENCES evidence_block(evidence_id),
    relation       TEXT NOT NULL,
    review_status  TEXT NOT NULL DEFAULT 'pending'
                   CHECK (review_status IN ('pending','verified','rejected')),
    PRIMARY KEY (row_version_id, field_name, evidence_id)
);

-- ============ 电竞业务表 ============

CREATE TABLE competition (
    competition_id TEXT PRIMARY KEY,
    game_id        TEXT NOT NULL,
    organizer_id   TEXT REFERENCES entity(entity_id),
    season         TEXT,
    split          TEXT,
    region         TEXT,
    tier           TEXT,
    starts_at      TEXT,
    ends_at        TEXT
);

CREATE TABLE stage (
    stage_id        TEXT PRIMARY KEY,
    competition_id  TEXT NOT NULL REFERENCES competition(competition_id),
    stage_name      TEXT NOT NULL,
    format          TEXT,
    rule_version_id TEXT
);

CREATE TABLE series (
    series_id       TEXT NOT NULL,
    stage_id        TEXT NOT NULL REFERENCES stage(stage_id),
    round           TEXT,
    team_a_id       TEXT REFERENCES entity(entity_id),
    team_b_id       TEXT REFERENCES entity(entity_id),
    best_of         INTEGER,
    scheduled_start TEXT,
    actual_start    TEXT,
    actual_end      TEXT,
    status          TEXT NOT NULL,
    winner_id       TEXT REFERENCES entity(entity_id),
    score_a         INTEGER,
    score_b         INTEGER,
    result_method   TEXT,
    row_version_id  TEXT PRIMARY KEY,
    logical_record_id TEXT NOT NULL,
    valid_from      TEXT,
    valid_to        TEXT,
    start_bound_kind TEXT CHECK (start_bound_kind IN ('exact','open','unknown')),
    end_bound_kind  TEXT CHECK (end_bound_kind  IN ('exact','open','unknown')),
    time_precision  TEXT CHECK (time_precision  IN ('second','day','month','unknown')),
    original_timezone TEXT,
    recorded_at     TEXT NOT NULL,
    superseded_at   TEXT,
    last_verified_at TEXT,
    verification_basis TEXT,
    source_revision TEXT,
    record_status   TEXT NOT NULL DEFAULT 'active'
                    CHECK (record_status IN ('active','superseded','retracted'))
);

CREATE TABLE game_result (
    game_result_id  TEXT NOT NULL,
    series_id       TEXT NOT NULL,
    game_number     INTEGER,
    attempt_number  INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL,
    counts_toward_series INTEGER NOT NULL DEFAULT 1,
    map_id          TEXT,
    patch_id        TEXT REFERENCES patch(patch_id),
    team_a_id       TEXT REFERENCES entity(entity_id),
    team_b_id       TEXT REFERENCES entity(entity_id),
    score_a         INTEGER,
    score_b         INTEGER,
    score_unit      TEXT NOT NULL CHECK (score_unit IN
                    ('series_games','map_rounds','in_game_kills','other')),
    winner_id       TEXT REFERENCES entity(entity_id),
    duration_seconds INTEGER,
    row_version_id  TEXT PRIMARY KEY,
    logical_record_id TEXT NOT NULL,
    valid_from      TEXT,
    valid_to        TEXT,
    start_bound_kind TEXT CHECK (start_bound_kind IN ('exact','open','unknown')),
    end_bound_kind  TEXT CHECK (end_bound_kind  IN ('exact','open','unknown')),
    time_precision  TEXT CHECK (time_precision  IN ('second','day','month','unknown')),
    original_timezone TEXT,
    recorded_at     TEXT NOT NULL,
    superseded_at   TEXT,
    last_verified_at TEXT,
    verification_basis TEXT,
    source_revision TEXT,
    record_status   TEXT NOT NULL DEFAULT 'active'
                    CHECK (record_status IN ('active','superseded','retracted'))
);

CREATE TABLE membership (
    membership_id   TEXT NOT NULL,
    person_id       TEXT NOT NULL REFERENCES entity(entity_id),
    team_id         TEXT NOT NULL REFERENCES entity(entity_id),
    membership_type TEXT NOT NULL CHECK (membership_type IN
                    ('contract','registered','loan','trial','staff')),
    role            TEXT,
    status          TEXT NOT NULL,
    competition_scope TEXT,
    row_version_id  TEXT PRIMARY KEY,
    logical_record_id TEXT NOT NULL,
    valid_from      TEXT,
    valid_to        TEXT,
    start_bound_kind TEXT CHECK (start_bound_kind IN ('exact','open','unknown')),
    end_bound_kind  TEXT CHECK (end_bound_kind  IN ('exact','open','unknown')),
    time_precision  TEXT CHECK (time_precision  IN ('second','day','month','unknown')),
    original_timezone TEXT,
    recorded_at     TEXT NOT NULL,
    superseded_at   TEXT,
    last_verified_at TEXT,
    verification_basis TEXT,
    source_revision TEXT,
    record_status   TEXT NOT NULL DEFAULT 'active'
                    CHECK (record_status IN ('active','superseded','retracted'))
);

CREATE TABLE lineup_player (
    game_result_id  TEXT NOT NULL,
    person_id       TEXT NOT NULL REFERENCES entity(entity_id),
    team_id         TEXT NOT NULL REFERENCES entity(entity_id),
    role            TEXT,
    slot            INTEGER,
    participation_status TEXT NOT NULL CHECK (participation_status IN
                    ('started','substituted_in','substituted_out','roster_only')),
    row_version_id  TEXT NOT NULL,
    recorded_at     TEXT NOT NULL,
    superseded_at   TEXT,
    record_status   TEXT NOT NULL DEFAULT 'active'
                    CHECK (record_status IN ('active','superseded','retracted')),
    PRIMARY KEY (game_result_id, person_id, team_id, row_version_id)
);

CREATE TABLE transfer_event (
    transfer_id     TEXT NOT NULL,
    person_id       TEXT NOT NULL REFERENCES entity(entity_id),
    from_team_id    TEXT REFERENCES entity(entity_id),
    to_team_id      TEXT REFERENCES entity(entity_id),
    move_type       TEXT NOT NULL,
    event_status    TEXT NOT NULL CHECK (event_status IN
                    ('rumor','announced','effective','cancelled','completed')),
    announced_at    TEXT,
    effective_at    TEXT,
    cancels_event_id TEXT,
    row_version_id  TEXT PRIMARY KEY,
    logical_record_id TEXT NOT NULL,
    valid_from      TEXT,
    valid_to        TEXT,
    start_bound_kind TEXT CHECK (start_bound_kind IN ('exact','open','unknown')),
    end_bound_kind  TEXT CHECK (end_bound_kind  IN ('exact','open','unknown')),
    time_precision  TEXT CHECK (time_precision  IN ('second','day','month','unknown')),
    original_timezone TEXT,
    recorded_at     TEXT NOT NULL,
    superseded_at   TEXT,
    last_verified_at TEXT,
    verification_basis TEXT,
    source_revision TEXT,
    record_status   TEXT NOT NULL DEFAULT 'active'
                    CHECK (record_status IN ('active','superseded','retracted'))
);

CREATE TABLE patch (
    patch_id        TEXT PRIMARY KEY,
    game_id         TEXT NOT NULL,
    patch_label     TEXT NOT NULL,
    parent_patch_id TEXT REFERENCES patch(patch_id),
    release_channel TEXT,
    hotfix_id       TEXT
);

CREATE TABLE patch_deployment (
    deployment_id   TEXT NOT NULL,
    patch_id        TEXT NOT NULL REFERENCES patch(patch_id),
    region          TEXT NOT NULL,
    server_type     TEXT NOT NULL CHECK (server_type IN
                    ('public','tournament','ptr','other')),
    competition_id  TEXT REFERENCES competition(competition_id),
    game_result_id  TEXT,
    deployed_at     TEXT,
    retired_at      TEXT,
    row_version_id  TEXT PRIMARY KEY,
    recorded_at     TEXT NOT NULL,
    superseded_at   TEXT,
    last_verified_at TEXT,
    verification_basis TEXT,
    record_status   TEXT NOT NULL DEFAULT 'active'
                    CHECK (record_status IN ('active','superseded','retracted'))
);

CREATE TABLE rule_version (
    rule_version_id TEXT NOT NULL,
    competition_id  TEXT REFERENCES competition(competition_id),
    stage_id        TEXT REFERENCES stage(stage_id),
    season          TEXT,
    rule_topic      TEXT NOT NULL,
    rule_value      TEXT NOT NULL,
    document_revision TEXT,
    row_version_id  TEXT PRIMARY KEY,
    recorded_at     TEXT NOT NULL,
    superseded_at   TEXT,
    record_status   TEXT NOT NULL DEFAULT 'active'
                    CHECK (record_status IN ('active','superseded','retracted'))
);

CREATE INDEX idx_snapshot_source ON source_snapshot(source_id);
CREATE INDEX idx_evidence_snapshot ON evidence_block(snapshot_id);
CREATE INDEX idx_series_stage ON series(stage_id);
CREATE INDEX idx_series_sid ON series(series_id);
CREATE INDEX idx_series_logical ON series(logical_record_id);
CREATE INDEX idx_game_result_series ON game_result(series_id);
CREATE INDEX idx_game_result_gid ON game_result(game_result_id);
CREATE INDEX idx_membership_person ON membership(person_id);
CREATE INDEX idx_membership_mid ON membership(membership_id);
CREATE INDEX idx_lineup_person ON lineup_player(person_id);
CREATE INDEX idx_transfer_person ON transfer_event(person_id);
CREATE INDEX idx_transfer_tid ON transfer_event(transfer_id);
CREATE INDEX idx_deployment_patch ON patch_deployment(patch_id);
CREATE INDEX idx_deployment_did ON patch_deployment(deployment_id);
CREATE INDEX idx_rule_rid ON rule_version(rule_version_id);