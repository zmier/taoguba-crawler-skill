#!/usr/bin/env python3
"""Deterministic arithmetic helpers for Stage B position inference.

The helpers intentionally do not decide broker semantics, trade continuity,
identity, or confidence.  Callers must establish those prerequisites first.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import json
from typing import Any


def decimal(value: Decimal | str | int | float) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _positive(value: Decimal, name: str) -> Decimal:
    if value <= 0:
        raise ValueError(f"{name}_must_be_positive")
    return value


def rate_implied_current_value(
    amount: Decimal | str | int | float,
    displayed_percent: Decimal | str | int | float,
) -> Decimal:
    """Return ``amount / rate + amount`` for a signed displayed percentage."""

    amount_value = decimal(amount)
    rate = decimal(displayed_percent) / Decimal("100")
    if rate == 0:
        raise ValueError("displayed_percent_must_be_nonzero")
    if amount_value != 0 and (amount_value > 0) != (rate > 0):
        raise ValueError("amount_and_percent_sign_mismatch")
    current_value = amount_value / rate + amount_value
    return _positive(current_value, "implied_current_value")


def rate_implied_current_value_interval(
    amount: Decimal | str | int | float,
    displayed_percent: Decimal | str | int | float,
    *,
    percent_decimals: int,
    amount_decimals: int = 2,
) -> tuple[Decimal, Decimal]:
    """Propagate display rounding through the P/L-rate current-value formula."""

    if percent_decimals < 0 or amount_decimals < 0:
        raise ValueError("decimal_places_must_be_nonnegative")
    amount_value = decimal(amount)
    percent_value = decimal(displayed_percent)
    amount_half = Decimal("0.5") * (Decimal("10") ** -amount_decimals)
    percent_half = Decimal("0.5") * (Decimal("10") ** -percent_decimals)
    amount_bounds = (amount_value - amount_half, amount_value + amount_half)
    percent_bounds = (percent_value - percent_half, percent_value + percent_half)
    if percent_bounds[0] <= 0 <= percent_bounds[1]:
        raise ValueError("rounded_percent_interval_crosses_zero")
    values = [
        rate_implied_current_value(amount_bound, percent_bound)
        for amount_bound in amount_bounds
        for percent_bound in percent_bounds
    ]
    return min(values), max(values)


def quantity_from_value(
    current_market_value: Decimal | str | int | float,
    price: Decimal | str | int | float,
) -> Decimal:
    return _positive(decimal(current_market_value), "current_market_value") / _positive(
        decimal(price), "price"
    )


def round_lot_quantity_range(
    current_market_value: Decimal | str | int | float,
    low_price: Decimal | str | int | float,
    high_price: Decimal | str | int | float,
    *,
    lot_size: int = 100,
) -> tuple[int, int]:
    """Return inclusive round-lot quantity bounds compatible with a price range."""

    value = _positive(decimal(current_market_value), "current_market_value")
    low = _positive(decimal(low_price), "low_price")
    high = _positive(decimal(high_price), "high_price")
    if high < low:
        raise ValueError("high_price_below_low_price")
    if lot_size <= 0:
        raise ValueError("lot_size_must_be_positive")
    lot = Decimal(lot_size)
    minimum = int(((value / high) / lot).to_integral_value(rounding=ROUND_CEILING)) * lot_size
    maximum = int(((value / low) / lot).to_integral_value(rounding=ROUND_FLOOR)) * lot_size
    if minimum > maximum:
        raise ValueError("no_round_lot_quantity_in_price_range")
    return minimum, maximum


def holding_average_cost(
    current_market_value: Decimal | str | int | float,
    floating_profit_loss: Decimal | str | int | float,
    quantity: Decimal | str | int | float,
) -> Decimal:
    value = _positive(decimal(current_market_value), "current_market_value")
    quantity_value = _positive(decimal(quantity), "quantity")
    return _positive(value - decimal(floating_profit_loss), "holding_cost_amount") / quantity_value


def daily_pnl_reference_price(
    current_market_value: Decimal | str | int | float,
    daily_profit_loss: Decimal | str | int | float,
    quantity: Decimal | str | int | float,
) -> Decimal:
    value = _positive(decimal(current_market_value), "current_market_value")
    quantity_value = _positive(decimal(quantity), "quantity")
    return _positive(value - decimal(daily_profit_loss), "daily_reference_amount") / quantity_value


def _json_number(value: Decimal) -> str:
    return format(value, "f")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    rate_parser = subparsers.add_parser("rate-value")
    rate_parser.add_argument("--amount", required=True)
    rate_parser.add_argument("--percent", required=True)
    rate_parser.add_argument("--percent-decimals", type=int)
    rate_parser.add_argument("--amount-decimals", type=int, default=2)

    cost_parser = subparsers.add_parser("holding-cost")
    cost_parser.add_argument("--market-value", required=True)
    cost_parser.add_argument("--floating-pnl", required=True)
    cost_parser.add_argument("--quantity", required=True)

    daily_parser = subparsers.add_parser("daily-reference")
    daily_parser.add_argument("--market-value", required=True)
    daily_parser.add_argument("--daily-pnl", required=True)
    daily_parser.add_argument("--quantity", required=True)

    quantity_parser = subparsers.add_parser("quantity-range")
    quantity_parser.add_argument("--market-value", required=True)
    quantity_parser.add_argument("--low", required=True)
    quantity_parser.add_argument("--high", required=True)
    quantity_parser.add_argument("--lot-size", type=int, default=100)

    args = parser.parse_args()
    output: dict[str, Any]
    if args.command == "rate-value":
        value = rate_implied_current_value(args.amount, args.percent)
        output = {"current_market_value": _json_number(value)}
        if args.percent_decimals is not None:
            lower, upper = rate_implied_current_value_interval(
                args.amount,
                args.percent,
                percent_decimals=args.percent_decimals,
                amount_decimals=args.amount_decimals,
            )
            output["rounding_interval"] = [_json_number(lower), _json_number(upper)]
    elif args.command == "holding-cost":
        output = {
            "holding_average_cost": _json_number(
                holding_average_cost(args.market_value, args.floating_pnl, args.quantity)
            )
        }
    elif args.command == "daily-reference":
        output = {
            "daily_pnl_reference_price": _json_number(
                daily_pnl_reference_price(args.market_value, args.daily_pnl, args.quantity)
            )
        }
    else:
        lower, upper = round_lot_quantity_range(
            args.market_value, args.low, args.high, lot_size=args.lot_size
        )
        output = {"round_lot_quantity_range": [lower, upper]}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
