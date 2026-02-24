def format_price(price: float | int | None) -> str:
    value = float(price or 0)
    abs_value = abs(value)
    if abs_value < 0.000001:
        return f"${value:.8f}"
    if abs_value < 0.001:
        return f"${value:.6f}"
    if abs_value < 1:
        return f"${value:.4f}"
    if abs_value < 1000:
        return f"${value:,.2f}"
    return f"${value:,.0f}"


def format_usd(amount: float | int | None) -> str:
    value = float(amount or 0)
    abs_value = abs(value)
    if abs_value >= 1_000_000:
        return f"${value/1_000_000:.1f}M"
    if abs_value >= 1000:
        return f"${value:,.0f}"
    return f"${value:.2f}"

