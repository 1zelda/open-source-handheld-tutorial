"""portkit：声明式移植流水线。

一个游戏 = 一份 spec JSON：源码钉版本 + 工具链档案 + 构建适配器 + 打包 + 闸门。
同一份 spec 可以产出掌机（PortMaster）和 Switch（NRO）两个目标。
"""

from .spec import PortSpec, SpecError, load_spec
from .runner import PortRunner, RunError

__all__ = ["PortSpec", "SpecError", "load_spec", "PortRunner", "RunError"]
