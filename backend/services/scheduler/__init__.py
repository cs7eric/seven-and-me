"""后台调度器集合。

不要在 package import 阶段加载具体 scheduler；部分 scheduler 会导入实时行情
依赖（如 eltdx），在只读缓存或测试环境里会造成不必要的导入失败。
"""

__all__: list[str] = []
