from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from nl_json_translator.domain.enums import BatchStatus
from nl_json_translator.infrastructure.orm_models import TransportBatchRecord


class BatchRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        batch_id: str,
        natural_language: Optional[str],
        constraints: dict[str, Any],
        provider_response_id: Optional[str] = None,
        provider_model: Optional[str] = None,
        provider_usage: Optional[dict[str, Any]] = None,
    ) -> TransportBatchRecord:
        record = TransportBatchRecord(
            id=batch_id,
            natural_language=natural_language,
            status=BatchStatus.CREATED.value,
            constraints_json=dict(constraints),
            provider_response_id=provider_response_id,
            provider_model=provider_model,
            provider_usage_json=dict(provider_usage or {}),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def set_status(self, batch_id: str, status: BatchStatus) -> bool:
        record = self.session.get(TransportBatchRecord, batch_id)
        if not record:
            return False
        record.status = status.value
        self.session.flush()
        return True
