"""Parameter registry tests (Phase-2 Section 23)."""
from ema_scanner.strategy.parameter_registry import PARAMETER_CATEGORIES, classify, classify_all

VALID_CATEGORIES = {
    "SOURCE_DERIVED_RULE", "MATHEMATICAL_DEFINITION", "RESEARCH_HYPOTHESIS",
    "OPTIONAL_FILTER", "OPTIONAL_PARAMETER", "ENGINEERING_PARAMETER",
    "ENGINEERING_DECISION", "PLACEHOLDER_UNVERIFIED",
}


def test_every_registered_category_is_a_known_label():
    for path, category in PARAMETER_CATEGORIES.items():
        assert category in VALID_CATEGORIES, f"{path} has an unrecognized category {category!r}"


def test_unregistered_path_returns_unclassified_not_a_crash():
    assert classify("some.made.up.path") == "UNCLASSIFIED"


def test_classify_all_returns_a_copy_not_the_live_registry():
    result = classify_all()
    result["strategy.ema.fast"] = "MUTATED"
    assert PARAMETER_CATEGORIES["strategy.ema.fast"] == "SOURCE_DERIVED_RULE"


def test_cost_parameters_are_flagged_unverified():
    assert classify("costs.brokerage_pct") == "PLACEHOLDER_UNVERIFIED"
