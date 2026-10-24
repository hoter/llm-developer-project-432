"""Стоимость вызова модели — в целых микроединицах.

Цены заданы в микроединицах за миллион токенов. Считать деньги float нельзя:
0.1 + 0.2 != 0.3, а суммы в отчёте должны сходиться. Поэтому стоимость —
целое число 1e-6 денежной единицы, а округление — половина вверх.
"""
from app.core.config import settings

TOKENS_PER_PRICE_UNIT = 1_000_000


def calculate_cost_micros(
    input_tokens: int,
    output_tokens: int,
    *,
    input_price_micros_per_1m: int,
    output_price_micros_per_1m: int,
) -> int:
    """Стоимость в микроединицах: целые числа, округление половина вверх."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("расход токенов не может быть отрицательным")
    return _tokens_cost(input_tokens, input_price_micros_per_1m) + _tokens_cost(
        output_tokens, output_price_micros_per_1m
    )


def prices_for(model: str) -> tuple[int, int]:
    """Цены (вход, выход) в микроединицах за 1M токенов для модели."""
    if model == settings.llm_aux_model and model != settings.llm_model:
        return (
            settings.llm_aux_price_input_micros_per_1m,
            settings.llm_aux_price_output_micros_per_1m,
        )
    return (
        settings.llm_price_input_micros_per_1m,
        settings.llm_price_output_micros_per_1m,
    )


def cost_micros_for(model: str, input_tokens: int, output_tokens: int) -> int:
    input_price, output_price = prices_for(model)
    return calculate_cost_micros(
        input_tokens,
        output_tokens,
        input_price_micros_per_1m=input_price,
        output_price_micros_per_1m=output_price,
    )


def format_micros(value: int) -> str:
    """Микроединицы → человекочитаемая сумма без float-ошибок."""
    return f"{value // 1_000_000}.{value % 1_000_000:06d}"


def _tokens_cost(tokens: int, price_micros_per_1m: int) -> int:
    if tokens <= 0 or price_micros_per_1m <= 0:
        return 0
    return (tokens * price_micros_per_1m + TOKENS_PER_PRICE_UNIT // 2) // TOKENS_PER_PRICE_UNIT


def main() -> None:
    """Разбивка вызовов по моделям: сколько вызовов и на какую сумму."""
    from app.core import db
    from app.repositories import llm_calls as llm_calls_repo

    with db.connection() as conn:
        rows = llm_calls_repo.summary_by_model(conn)

    if not rows:
        print("вызовов модели ещё не было")
        return

    header = f"{'model':32} {'role':18} {'calls':>6} {'in':>10} {'out':>10} {'cost':>12}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['model']:32} {row['role']:18} {row['calls']:6} "
            f"{row['input_tokens']:10} {row['output_tokens']:10} "
            f"{format_micros(row['cost_micros']):>12}"
        )

    total = sum(row["cost_micros"] for row in rows)
    print("-" * len(header))
    print(f"{'итого':32} {'':18} {sum(r['calls'] for r in rows):6} "
          f"{sum(r['input_tokens'] for r in rows):10} "
          f"{sum(r['output_tokens'] for r in rows):10} {format_micros(total):>12}")


if __name__ == "__main__":
    main()
