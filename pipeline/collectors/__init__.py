"""Collectors 包（架构 §3.7：MacroCollector/MarketCollector/CalendarCollector/NewsCollector）。"""

from pipeline.collectors.calendar import CalendarCollector
from pipeline.collectors.macro import MacroCollector
from pipeline.collectors.market import MarketCollector
from pipeline.collectors.news import NewsCollector

__all__ = ["CalendarCollector", "MacroCollector", "MarketCollector", "NewsCollector"]
