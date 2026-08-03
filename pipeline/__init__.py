"""Market Risk Dashboard — 数据管道包。

架构 §1.3：pipeline/ 为纯本地数据管道（采集→指标→6维风险→事实层→存储）。
本包在 T01 提供工程骨架（settings/run），T02 提供数据契约（schemas/analysis），
T03 实现 Provider/Collector/Indicator/Risk 等业务逻辑。
"""

__version__ = "0.1.0"
