# 洛克人1候选语料就绪度回填（2026-11-25）

## 当前判定

**状态：`isolated_candidate_ready_for_ram_tooling_only`。**

- 已建立隔离候选索引：9 块、7 个索引文件、504 个词项。
- 来源资格：7 块 `authoritative`，2 块 `reference_only`；全部 `verified_read`。
- 版本边界：全部块只属于 `megaman1_nes_us`（NTSC 美版候选 ROM）。
- 冻结题集：12 题（9 道事实题、3 道拒答反例），生产查询默认与 strict 均为 **12/12**，错误出证 **0/0**。
- 真实状态隔离：构建与评测前后，生产 index、corpus map、sources、query log、电竞 DB、新闻快照的 SHA/bytes/mtime 均未变化。

## 从 2026-11-24 起补齐了什么

1. 4 份外部取证在隔离目录保留逐字副本，SHA 与原文件一致。
2. 新建 5 份外部事实摘录与 2 份本机实测摘录；摘录保留原文件行段，避免网页导航/页脚噪声进入候选索引。
3. 用生产 `kb.build()` 构建候选索引，没有翻生产 `corpus_map.json` 的 `index:false`。
4. 12 道题按真实 chunk 重锚并冻结；原草案保持不覆盖。
5. 用生产 `kb.query()` 跑默认与 strict 两臂，查询日志写入候选目录。

## 覆盖边界

| 已覆盖 | 未覆盖 |
|---|---|
| 对象 RAM 表、坐标轴、对象编号 | 官方说明书级玩法 |
| BizHawk 内存覆盖与 callback 机制 | 整款游戏内容知识库 |
| 本机武器 RAM 实测 | PAL-B 与 NTSC 美版等价性 |
| 本机对象表定位 T1 实测 | 生产路由与生产问答消费方 |
| segmented TAS / FM2 导入通用参考 | 洛克人1到目标时刻的真实存档点续作证据 |

## 仍未完成的生产门槛

- `kb_route.py` 没有 `megaman` 域，不能把候选索引接进自动路由。
- 没有专用生产问答消费方。
- 缺官方说明书级游戏内容语料。
- 未验证 PAL-B 与 NTSC 美版跨版等价。
- 未生成候选 dense/hybrid 富集件，也未验证真实用户查询样本。

因此本轮**不把候选索引提升为生产知识域**，也不声称已有“洛克人1整款游戏知识库”。

## 共享状态观察

本轮评测期间生产 index 的前后 SHA 均为 `5c6fdb832cac502845d2e9dce269f25023dd435af42a5f59c772efbe9169596b`；新闻快照当时为 `2a93e76d5876c1181e7784a20eca0f4d84888d0292d281fc6eea3564090b9260`。两者不同，但都不是本轮写入；本任务只验证“本轮前后不变”，没有替并行 KB 会话同步或重建。

## 复核入口

- 候选索引：`知识库P1_20261118/megaman1_candidate_20261125/index.json`
- 冻结题集：`知识库P1_20261118/megaman1_questions_frozen_20261125.json`
- 评测 JSON：`知识库P1_20261118/megaman1_candidate_eval_20261125.json`
- 评测 MD：`知识库P1_20261118/megaman1_candidate_eval_20261125.md`
- 构建报告：`知识库P1_20261118/megaman1_candidate_build_20261125.json`
