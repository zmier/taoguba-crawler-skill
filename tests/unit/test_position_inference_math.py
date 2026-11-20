from decimal import Decimal

import pytest

from scripts.tgb_position_inference_math import (
    daily_pnl_reference_price,
    holding_average_cost,
    quantity_from_value,
    rate_implied_current_value,
    rate_implied_current_value_interval,
    round_lot_quantity_range,
)


def test_rate_implied_value_and_rounding_interval() -> None:
    value = rate_implied_current_value("690", "9.971")
    lower, upper = rate_implied_current_value_interval(
        "690", "9.971", percent_decimals=3, amount_decimals=3
    )
    assert lower < value < upper
    assert abs(value - Decimal("7610.068197773543275498946946")) < Decimal("1e-20")


def test_quantity_cost_and_daily_reference_are_separate() -> None:
    assert quantity_from_value("7610", "7.61") == Decimal("1000")
    assert holding_average_cost("7610", "3240", "1000") == Decimal("4.37")
    assert daily_pnl_reference_price("7610", "690", "1000") == Decimal("6.92")


def test_round_lot_quantity_range() -> None:
    assert round_lot_quantity_range("1553106", "18.78", "18.78") == (82700, 82700)
    assert round_lot_quantity_range("10522068.6", "3.92", "4.14") == (
        2541600,
        2684200,
    )


def test_formula_rejects_invalid_semantics_shape() -> None:
    with pytest.raises(ValueError, match="sign_mismatch"):
        rate_implied_current_value("100", "-1")
    with pytest.raises(ValueError, match="crosses_zero"):
        rate_implied_current_value_interval(
            "1", "0.0", percent_decimals=1, amount_decimals=2
        )
