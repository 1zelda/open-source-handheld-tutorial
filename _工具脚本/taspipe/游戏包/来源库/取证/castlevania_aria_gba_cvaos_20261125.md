# 取证：GitHub testyourmine/cvaos（USA matching decomp）

- 仓库 URL：https://github.com/testyourmine/cvaos
- 本机读取日期：2026-11-25
- 默认分支：main
- 页面给出的 currentOid：bc23d849d578c35ae12a5cec4e66549c3021a5be
- 状态：verified_read（仓库首页与相关源码正文已读取）

## 身份与版本边界

README 原文要点：

```text
This is a work in progress matching decompilation of Castlevania: Aria of Sorrow (USA).
cvaos_us.gba sha1: abd71fe01ebb201bcc133074db1dd8c5253776c7
```

当前项目实测 ROM：

```text
SHA1 40aab076a528f52e93260bb98d91a40039e0da02
```

两者不是同一 ROM。USA 反编译只能提供算法、结构关系和候选偏移，不能把地址直接搬成中文版已验证地址。

## 可复用算法

`src/code_08032444.c` 的魂库存数量读取逻辑：

```c
soulInventoryFirstGroupAmount = soulInventoryFirstGroup[soulIndex >> 1];
if (soulIndex & 1)
{
    soulInventoryFirstGroupAmount = (soulInventoryFirstGroupAmount >> 4) & 0xF;
}
else
{
    soulInventoryFirstGroupAmount = soulInventoryFirstGroupAmount & 0xF;
}
```

装备计数会把已装备魂额外加 1：

```c
switch (soulType)
{
    case 0:
        if ((soulIndex + 1) == gEwramData->unk_1325C.equippedRedSoul)
            soulInventoryFirstGroupAmount += 1;
        break;
    case 1:
        if ((soulIndex + 1) == gEwramData->unk_1325C.equippedBlueSoul)
            soulInventoryFirstGroupAmount += 1;
        break;
    case 2:
        if ((soulIndex + 1) == gEwramData->unk_1325C.equippedYellowSoul)
            soulInventoryFirstGroupAmount += 1;
        break;
}
```

各类魂数量（消费函数循环上界，不是末项 0-based 索引）：

```c
const u8 sUnk_080E1CD4[] = {
    0x37, 0x18, 0x23, 0x8
};
```

`src/code_080096AC.c` 与调试代码均按 `index < count` 遍历，因此对应红魂 55、蓝魂 24、黄魂 35、能力魂 8 项。此前把 `0x8` 解释成“末项索引”并写成能力魂 9 项，是计数口径错误，现予纠正。

`include/structs/ewram.h` 的能力魂布局为：

```c
/* 0x13392 */ u8 abilitySoulInventory[0x3];
/* 0x13395 */ u8 pad_13395[0x13396 - 0x13395]; // TODO: is abilitySoulInventory really 4 entries?
```

即 USA 版实际预留 4 字节，可容纳 8 个低/高 nibble 数量。结合中文社区已命中的红/蓝/黄库存起点，它们都比 USA 同结构字段小 `0x0C`；据此得到中文版能力魂候选 `0x13386–0x13389`。该地址尚未经过当前 ROM 的菜单消费或 gameplay 验收，不能写成 verified 字段。

当前待逐项验收的候选范围：

```text
红魂 0x13310–0x1332B，55 项
蓝魂 0x13348–0x13353，24 项
黄魂 0x13362–0x13373，35 项
能力魂 0x13386–0x13389，8 项（仅 USA 结构位移候选）
```

## 红魂触发与 MP 规则

`src/code_08033CAC.c` 的 `sub_08034624`：

```c
if (!(gEwramData->inputData.playerHeldInput & 0x40))
    return;
if (!(gEwramData->inputData.playerNewInput & gEwramData->unk_1325C.attackButton))
    return;
temp_r8 = sub_0802D284(gEwramData->unk_1325C.equippedRedSoul);
```

```c
if (temp_r8->unk_6 >= gEwramData->unk_1325C.currentMP)
    return;
```

施法成功后：

```c
gEwramData->unk_1325C.currentMP -= temp_r8->unk_6;
```

即 MP 必须严格大于消耗值；等于消耗值时不能施法。

## 可继续复用的函数

- `SoulInventory_GetFirstGroupSoulTotalDifferent`
- `SoulInventory_AddAmountToFirstGroupTotal`
- `SoulInventory_AddAmountToGroupTotal`
- `SoulInventory_GetSoulTotal`
- `SoulInventory_GetInventoryPointer`
- `SoulInventory_SetGroupTotalAmount`
- `SoulInventory_TransferFirstGroupTotalToSecondGroupTotal`
- `SoulInventory_TransferSecondGroupTotalToFirstGroupTotal`
- `sub_08032D58`
- `sub_08021344`
- `sub_08034624`

## 使用边界

1. USA 结构位移只能产生中文版候选；红/蓝/黄库存起点已由中文社区表命中，但能力魂 `0x13386–0x13389` 仍须当前 ROM 实测。
2. 旧候选 `0x133D3/0x133D7/0x133DB` 没有源码或消费点证据，已废弃，不得继续引用。
3. 菜单列表显示、RAM 写入保持、真实 gameplay 效果是三层不同证据，不能互相替代。
