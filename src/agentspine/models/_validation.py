"""模型共享的少量边界校验。"""

from datetime import datetime
from enum import Enum
from typing import Any


def require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} 必须是非空字符串")


def require_enum(value: Any, enum_type: type[Enum], field_name: str) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{field_name} 必须是 {enum_type.__name__} 类型")


def require_aware_datetime(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} 必须包含时区信息")


def require_time_order(started_at: datetime | None, finished_at: datetime | None) -> None:
    if started_at is not None and finished_at is not None and finished_at < started_at:
        raise ValueError("finished_at 不能早于 started_at")
