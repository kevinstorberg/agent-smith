from __future__ import annotations

import pytest

from services.api.models.shared import listing


def test_bidirectional_sorts_handles_compound_terms_and_qualified_ties():
    orders = listing.bidirectional_sorts(
        {
            ("name", "name_desc"): ("lower(item.name)",),
            ("type_asc", "type_desc"): ("lower(item.kind)", "lower(item.category)"),
        },
        tie_breaker="item.id",
    )
    assert orders == {
        "name": "lower(item.name) ASC NULLS LAST, item.id ASC",
        "name_desc": "lower(item.name) DESC NULLS LAST, item.id DESC",
        "type_asc": "lower(item.kind) ASC NULLS LAST, lower(item.category) ASC NULLS LAST, item.id ASC",
        "type_desc": "lower(item.kind) DESC NULLS LAST, lower(item.category) DESC NULLS LAST, item.id DESC",
    }
    assert listing.sort_clause("name_desc", orders) == orders["name_desc"]


@pytest.mark.parametrize(
    "columns",
    [
        {},
        {("name", "name_desc"): ()},
        {("name", "name_desc"): ("",)},
        {("name", "name_desc"): ("  ",)},
        {("name", "name_desc"): "name"},
        {("name",): ("name",)},
        {("", "name_desc"): ("name",)},
        {("name", "name"): ("name",)},
        {("name", "name_desc"): ("name",), ("name_desc", "other"): ("other",)},
    ],
)
def test_bidirectional_sorts_rejects_invalid_programmer_configuration(columns):
    with pytest.raises(ValueError):
        listing.bidirectional_sorts(columns)


@pytest.mark.parametrize("tie_breaker", ["", "  ", None])
def test_bidirectional_sorts_requires_a_trusted_unique_tie(tie_breaker):
    with pytest.raises(ValueError):
        listing.bidirectional_sorts(
            {("name", "name_desc"): ("name",)}, tie_breaker=tie_breaker
        )
