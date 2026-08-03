"""FedWatch package (architecture §1.6)."""

from pipeline.fedwatch.calculator import FedWatchInput, compute_fedwatch, insufficient_data_snapshot
from pipeline.fedwatch.futures import fetch_contract_price, meeting_date_for_contract, next_contract_codes
from pipeline.fedwatch.snapshots import enrich_with_history, load_history, save_history

__all__ = [
    "FedWatchInput",
    "compute_fedwatch",
    "enrich_with_history",
    "fetch_contract_price",
    "insufficient_data_snapshot",
    "load_history",
    "meeting_date_for_contract",
    "next_contract_codes",
    "save_history",
]
