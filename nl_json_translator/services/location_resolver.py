from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
from typing import Optional

from nl_json_translator.domain.location_text import normalize_location_text
from nl_json_translator.repositories.locations import LocationData, LocationRepository


class LocationResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LocationCandidate:
    location_id: str
    name: str
    score: float
    matched_by: str


@dataclass(frozen=True)
class LocationResolution:
    query: str
    normalized_query: str
    status: LocationResolutionStatus
    candidates: tuple[LocationCandidate, ...] = ()

    @property
    def location_id(self) -> Optional[str]:
        if self.status is LocationResolutionStatus.RESOLVED and self.candidates:
            return self.candidates[0].location_id
        return None

    def require_location_id(self) -> str:
        if self.location_id:
            return self.location_id
        if self.status is LocationResolutionStatus.AMBIGUOUS:
            names = ", ".join(candidate.name for candidate in self.candidates)
            raise AmbiguousLocationError(f'Location "{self.query}" is ambiguous: {names}')
        raise UnknownLocationError(f'Unknown location "{self.query}"')


class UnknownLocationError(ValueError):
    pass


class AmbiguousLocationError(ValueError):
    pass


class LocationResolver:
    def __init__(
        self,
        repository: LocationRepository,
        *,
        fuzzy_threshold: float = 0.78,
        ambiguity_margin: float = 0.06,
    ):
        self.repository = repository
        self.fuzzy_threshold = fuzzy_threshold
        self.ambiguity_margin = ambiguity_margin

    def resolve(self, query: str) -> LocationResolution:
        normalized_query = normalize_location_text(query)
        if not normalized_query:
            return LocationResolution(query, normalized_query, LocationResolutionStatus.UNKNOWN)

        locations = self.repository.list_enabled()
        exact = self._exact_candidates(locations, normalized_query)
        if len(exact) == 1:
            return LocationResolution(
                query, normalized_query, LocationResolutionStatus.RESOLVED, tuple(exact)
            )
        if len(exact) > 1:
            return LocationResolution(
                query, normalized_query, LocationResolutionStatus.AMBIGUOUS, tuple(exact)
            )

        fuzzy = self._fuzzy_candidates(locations, normalized_query)
        if not fuzzy or fuzzy[0].score < self.fuzzy_threshold:
            return LocationResolution(query, normalized_query, LocationResolutionStatus.UNKNOWN)
        close_candidates = [
            candidate
            for candidate in fuzzy
            if fuzzy[0].score - candidate.score < self.ambiguity_margin
        ]
        status = (
            LocationResolutionStatus.RESOLVED
            if len(close_candidates) == 1
            else LocationResolutionStatus.AMBIGUOUS
        )
        return LocationResolution(query, normalized_query, status, tuple(close_candidates[:5]))

    @staticmethod
    def _exact_candidates(
        locations: list[LocationData], normalized_query: str
    ) -> list[LocationCandidate]:
        candidates: list[LocationCandidate] = []
        for location in locations:
            if normalize_location_text(location.name) == normalized_query:
                candidates.append(LocationCandidate(location.id, location.name, 1.0, "name"))
                continue
            if any(
                normalize_location_text(alias) == normalized_query for alias in location.aliases
            ):
                candidates.append(LocationCandidate(location.id, location.name, 1.0, "alias"))
        return candidates

    @staticmethod
    def _fuzzy_candidates(
        locations: list[LocationData], normalized_query: str
    ) -> list[LocationCandidate]:
        candidates: list[LocationCandidate] = []
        for location in locations:
            terms = [(location.name, "name"), *((alias, "alias") for alias in location.aliases)]
            best_score = 0.0
            best_source = "name"
            for term, source in terms:
                score = SequenceMatcher(
                    None, normalized_query, normalize_location_text(term)
                ).ratio()
                if score > best_score:
                    best_score = score
                    best_source = source
            candidates.append(
                LocationCandidate(location.id, location.name, round(best_score, 4), best_source)
            )
        return sorted(candidates, key=lambda candidate: (-candidate.score, candidate.name))
