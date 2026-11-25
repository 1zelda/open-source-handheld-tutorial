# 洛克人1 候选语料与独立盲测就绪度（2026-11-24）

## 结论

**可以开始做隔离候选索引和盲测草案，但不能直接启用为生产知识域。**

当前已有：一个版本身份、四份已取回并登记的 TASVideos 原文，以及本机生产实测文档。缺的是：`kb_route` 的 `megaman` 域、专门生产消费方、官方说明书级游戏内容覆盖，以及按候选索引重新冻结的金标。因此本轮不改 `corpus_map.json`、不重建 770 块生产索引、不改快照对账。

## 1. 版本身份与机制权威是两回事

| 项 | 当前证据 | 能证明 | 不能证明 |
|---|---|---|---|
| NTSC 美版候选 ROM | `04-游戏资源库/TAS输入录像库/roms_verify/NES/megamanhd.nes`；131,088 B；SHA-1 `2F88381557339A14C20428455F6991C1EB902C99` | 生产 catalog 与 NesCartDB 指向 NTSC；文件名 `hd` 不是身份 | 文件名本身不能证明版本；该哈希也不是官方机制来源 |
| PAL-B 候选 | `F:/BaiduNetdiskDownload/rom/nes/洛克人1.nes`；SHA-1 `0fe255649359ece8cb64b6f24acaf09f17af746c` | 存在另一份地区候选 | 不能拿来回答 NTSC 美版问题，未验证跨版等价 |
| 身份未核候选 | `mega_man_usa.nes`；SHA-1 `d8b8c5e2ee76f2ec1820123bb9f8c70f5e603923` | 仅候选路径与哈希 | 不能凭文件名升格为 USA/NTSC |
| 本机 showcase | `megaman1_weapons.showcase.json` 钉上述 NTSC SHA-1 | 我方生产输入、ROM 与回放链一致 | 自产证据不自动等于官方说明书权威 |

结论：候选索引只绑定 `megaman1_nes_us`，拒绝 PAL-B 和身份未核件。

## 2. 已登记语料

`corpus_map.json` 已有 `megaman1_nes_us` revision 和四条 entry，全部 `index:false`：

| 文件 | 当前 authority | 可用内容 | 边界 |
|---|---|---|---|
| `tasvideos_gameresources_rockman_data_2026-11-23.txt` | authoritative | 坐标方向、分数坐标、对象属性表、对象编号、Rockman/Boss 编号 | RAM/对象数据，不是完整游戏攻略 |
| `tasvideos_bizhawk_faq_refresh_2026-11-23.txt` | authoritative | 每帧覆盖、memory callback、核心时序差异 | 工具方法，不是 MM1 专属玩法 |
| `tasvideos_forum_19912_bizhawk_import_fm2_2026-11-23.txt` | reference_only | FCEUX `.fm2` 转 BizHawk `.tasproj` 的社区流程 | 社区经验，不作权威机制结论 |
| `tasvideos_glossary_segmented_tas_2026-11-23.txt` | reference_only | segmented TAS 定义 | 通用术语，不是 MM1 官方资料 |

现有排除理由仍成立：没有 `megaman` 路由域，没有专用生产问答消费方，翻入 BM25 会改变共享索引块基数与选题层快照对账。

## 3. 本机可补充的强事实

来自 `测试问题与闸门说明书.md` 和 `场景取得方法_调研与设计_2026-11-23.md` 的生产实测：

1. `owned=$5D` 位场，`current_weapon=$5F`；值 `0..7 = P,C,I,B,F,E,G,M`。
2. `$0480`/`$0600` 是 Rockman `n=0` 的权威对象表 X/Y 高位；写派生显示地址 `$0022` 无效，写对象表会真实移动角色。
3. 写不同相机值却得到相同像素差，是“没有换房”的恒量反证，不能把像素动画差当换房证据。
4. 这些是**本机受控实测**，可以独立标注 `local_measurement`，但不应伪装成官方说明书。

`场景取得方法_调研与设计_2026-11-23.md` 还明确记录：Data Crystal、TCRF、GameFAQs、TASVideos 游戏页没有本地原文，相关内容只能算待核线索。

## 4. 独立盲测草案

文件：`megaman1_questions_draft_20261124.json`，共 12 题：

- 9 题有明确原文或本机实测金标草案；
- 1 题 segmented TAS 只有 `reference_only`，冻结前必须改档或找到权威出处；
- 2 题是缺证与跨版本拒答反例。

这不是已冻结盲测集，也不能直接对 770 块生产索引跑分：MM1 四条原文目前全部不在索引中，硬跑只会得到缺证拒答，不能评价候选语料。冻结顺序应为：

1. 复制 corpus map 到隔离目录；
2. 只启用明确 `authoritative` 的 MM1 条目；
3. 用生产 `kb.build()` 建隔离索引；
4. 跑生产 `kb.query()`；
5. 按真实 chunk 重锚 gold，再冻结题集并重跑；
6. 全程保护真实 index、map、sources、query log 和电竞库。

## 5. 启用前缺口

### 硬缺口

- `kb_route.py` 没有 `megaman` 域；
- 没有 MM1 生产问答消费方；
- 四条 entry 仍全部 `index:false`；
- 独立索引尚未建立，题集仍是草案；
- 官方说明书/官方游戏资料未取回。

### 质量缺口

- 目前强项是 RAM、工具链和本机实测，不是完整游戏内容；
- 攻略类问题若只靠 RAM 文档，会出现“查得到方法、答不了玩法”的覆盖假象；
- 跨版本、跨地区、hack 与官方原版必须分开；
- 本机实测文档含撤回与更正，必须走严格片段资格，不能整段继承。

### 明确不做

- 不下载或写入商业 ROM/BIOS；
- 不调用外部生成模型或付费 API；
- 不发送授权申请；
- 不把自产 showcase 升成官方权威；
- 不为了让盲测全绿而放宽拒答或跨版本闸门。

## 6. 下一步最小闭环

先补一份官方说明书或可信官方游戏资料，再建隔离 MM1 候选索引并冻结 12 题。若官方资料仍缺，可先交付“RAM/工具方法子域”的隔离评测，但必须把覆盖范围写明，不能称为整款游戏知识库。
