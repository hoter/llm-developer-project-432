"""Стоимость: целые микроединицы, округление, цены двух моделей."""
import pytest

from app.core.config import settings
from app.llm.cost import (
    calculate_cost_micros,
    cost_micros_for,
    format_micros,
    prices_for,
)


def test_cost_is_sum_of_input_and_output():
    cost = calculate_cost_micros(
        1000,
        500,
        input_price_micros_per_1m=150_000,
        output_price_micros_per_1m=600_000,
    )
    # 1000 * 0.15 + 500 * 0.60 = 150 + 300 микроединиц
    assert cost == 450
    assert isinstance(cost, int)


def test_cost_rounds_half_up():
    half = calculate_cost_micros(
        1, 0, input_price_micros_per_1m=500_000, output_price_micros_per_1m=0
    )
    below = calculate_cost_micros(
        1, 0, input_price_micros_per_1m=499_999, output_price_micros_per_1m=0
    )
    assert half == 1
    assert below == 0


def test_zero_price_is_free():
    assert (
        calculate_cost_micros(
            1_000_000, 1_000_000, input_price_micros_per_1m=0, output_price_micros_per_1m=0
        )
        == 0
    )


def test_negative_tokens_rejected():
    with pytest.raises(ValueError):
        calculate_cost_micros(
            -1, 0, input_price_micros_per_1m=1, output_price_micros_per_1m=1
        )


def test_prices_depend_on_model(monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "main-model")
    monkeypatch.setattr(settings, "llm_aux_model", "cheap-model")
    monkeypatch.setattr(settings, "llm_price_input_micros_per_1m", 300_000)
    monkeypatch.setattr(settings, "llm_price_output_micros_per_1m", 900_000)
    monkeypatch.setattr(settings, "llm_aux_price_input_micros_per_1m", 100_000)
    monkeypatch.setattr(settings, "llm_aux_price_output_micros_per_1m", 200_000)

    assert prices_for("main-model") == (300_000, 900_000)
    assert prices_for("cheap-model") == (100_000, 200_000)
    assert cost_micros_for("cheap-model", 1_000_000, 0) == 100_000
    assert cost_micros_for("main-model", 1_000_000, 0) == 300_000


def test_format_micros_without_float():
    assert format_micros(1_234_567) == "1.234567"
    assert format_micros(0) == "0.000000"
