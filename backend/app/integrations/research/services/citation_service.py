from __future__ import annotations

from uuid import UUID


class CitationValidationService:
    @staticmethod
    def validate_references(research_id: UUID, source_ids: list[str], valid_source_ids: set[str]) -> list[str]:
        invalid: list[str] = []
        for source_id in source_ids:
            if source_id not in valid_source_ids:
                invalid.append(source_id)
        return invalid
