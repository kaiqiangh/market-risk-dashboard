"""Market Risk Dashboard — data pipeline package.

Architecture §1.3: pipeline/ is a pure local data pipeline (collect → indicators → 6-dimension risk →
fact layer → storage). This package provides the engineering skeleton in T01 (settings/run), the data
contracts in T02 (schemas/analysis), and the Provider/Collector/Indicator/Risk business logic in T03.
"""

__version__ = "0.1.0"
