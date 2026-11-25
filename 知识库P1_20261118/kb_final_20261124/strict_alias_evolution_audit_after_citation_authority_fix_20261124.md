# strict 来源别名资格演变审计

- 冻结金标 SHA：P2 `b24712dc023ead293c7631f104d7e96fcefdcf5d8d2678e69ff6c47e29f48368`

| 代 | strict v2 | 修好 | 打坏 | 索引 |
|---|---|---|---|---|
| 旧strict_裸编号连坐 | 22/26 | 0 | 4 | 770块/01ba5d9cd9e0e5c1 |
| 临时strict_未知与已知编号全部不降级 | 25/26 | 0 | 1 | 770块/01ba5d9cd9e0e5c1 |
| 当前strict_来源别名资格 | 21/26 | 0 | 5 | 773块/2a93e76d5876c118 |

## 探针状态变化

| 探针 | 类型 | 旧strict | 临时 | 当前 |
|---|---|---|---|---|
| W10 | None | intercepted | still_passed | intercepted |
| W30 | None | intercepted | still_passed | still_passed |
| X03 | positive_control | intercepted | still_passed | intercepted |
| X04 | ambiguous | intercepted | still_passed | intercepted |
| X23 | insufficient_source | intercepted | still_passed | intercepted |

## 当前 strict 的 5 题回归

| 题 | 默认 | strict | 默认出证 | strict出证 |
|---|---|---|---|---|
| Q01 | pass | inconclusive | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L3-L7 | 无 |
| Q02 | pass | inconclusive | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L70-L85 | 无 |
| Q03 | pass | inconclusive | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | 无 |
| Q05 | pass | inconclusive | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L24-L33 | 无 |
| Q18 | pass | inconclusive | _工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md#L251-L259 | 无 |

## 结论

- 旧strict把所有裸S编号连坐降级，误拦正常汇总件；X03/X04/X23是其中可定位的误拦样例。
- 临时方案取消裸编号连坐后恢复25/26，但也把已知二手S1升成权威，X23重新放行。
- 当前方案按chunk.citation_authority解析来源别名：未知S99不连坐，已知二手/未核验/版本不符别名继承reference_only，本机实测标题可解除继承。
- 因此当前strict回到21/26；5题回归是已知二手别名被正确拦截的代价，不是通过改金标得到的假通过。
- X23冻结标签为insufficient_source，当前strict=intercepted，与冻结语义一致；临时strict=still_passed属于假放行。

- 本次审计 `ok=True`。
