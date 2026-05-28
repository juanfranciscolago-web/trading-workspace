"""
Greeks calculator — Black-Scholes model.

Both Eolo and multi-agent use this for independent validation of broker-
provided Greeks. Determinístic, no LLM, no surprises.

Note: This is a basic Black-Scholes. For American options early exercise,
use binomial tree (TODO: add binomial_calculator.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

from shared_core.models import Greeks


# Standard normal CDF and PDF (scipy-free implementation)
def _norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Probability density function for standard normal."""
    return math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)


@dataclass
class BlackScholesInput:
    """Inputs for Black-Scholes pricing."""
    underlying_price: float       # S
    strike: float                  # K
    time_to_expiry_years: float   # T (in years)
    risk_free_rate: float         # r (decimal, e.g., 0.05 for 5%)
    volatility: float              # σ (decimal, e.g., 0.30 for 30%)
    option_type: Literal["call", "put"]
    dividend_yield: float = 0.0   # q (decimal)


def calculate_d1_d2(inputs: BlackScholesInput) -> tuple[float, float]:
    """Calculate d1 and d2 from Black-Scholes formula."""
    if inputs.time_to_expiry_years <= 0:
        return float("inf"), float("inf")
    if inputs.volatility <= 0:
        return float("inf"), float("inf")

    sigma_sqrt_t = inputs.volatility * math.sqrt(inputs.time_to_expiry_years)
    d1 = (
        math.log(inputs.underlying_price / inputs.strike)
        + (inputs.risk_free_rate - inputs.dividend_yield + 0.5 * inputs.volatility**2)
        * inputs.time_to_expiry_years
    ) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t
    return d1, d2


def black_scholes_price(inputs: BlackScholesInput) -> float:
    """Calculate option price using Black-Scholes."""
    if inputs.time_to_expiry_years <= 0:
        # Intrinsic value at expiration
        if inputs.option_type == "call":
            return max(inputs.underlying_price - inputs.strike, 0)
        else:
            return max(inputs.strike - inputs.underlying_price, 0)

    d1, d2 = calculate_d1_d2(inputs)
    discount = math.exp(-inputs.risk_free_rate * inputs.time_to_expiry_years)
    div_discount = math.exp(-inputs.dividend_yield * inputs.time_to_expiry_years)

    if inputs.option_type == "call":
        price = (
            inputs.underlying_price * div_discount * _norm_cdf(d1)
            - inputs.strike * discount * _norm_cdf(d2)
        )
    else:
        price = (
            inputs.strike * discount * _norm_cdf(-d2)
            - inputs.underlying_price * div_discount * _norm_cdf(-d1)
        )

    return price


def calculate_greeks(inputs: BlackScholesInput) -> Greeks:
    """
    Calculate all Greeks for an option.

    Returns Greeks per contract (not aggregate). Multiply by quantity * 100
    for total portfolio impact.
    """
    if inputs.time_to_expiry_years <= 0:
        return Greeks(iv=inputs.volatility)

    d1, d2 = calculate_d1_d2(inputs)
    sqrt_t = math.sqrt(inputs.time_to_expiry_years)
    discount = math.exp(-inputs.risk_free_rate * inputs.time_to_expiry_years)
    div_discount = math.exp(-inputs.dividend_yield * inputs.time_to_expiry_years)

    is_call = inputs.option_type == "call"

    # Delta
    if is_call:
        delta = div_discount * _norm_cdf(d1)
    else:
        delta = div_discount * (_norm_cdf(d1) - 1)

    # Gamma (same for calls and puts)
    gamma = (div_discount * _norm_pdf(d1)) / (
        inputs.underlying_price * inputs.volatility * sqrt_t
    )

    # Theta (per year — divide by 365 for per-day)
    common_theta = (
        -inputs.underlying_price * div_discount * _norm_pdf(d1) * inputs.volatility
        / (2 * sqrt_t)
    )
    if is_call:
        theta = (
            common_theta
            - inputs.risk_free_rate * inputs.strike * discount * _norm_cdf(d2)
            + inputs.dividend_yield * inputs.underlying_price * div_discount * _norm_cdf(d1)
        )
    else:
        theta = (
            common_theta
            + inputs.risk_free_rate * inputs.strike * discount * _norm_cdf(-d2)
            - inputs.dividend_yield * inputs.underlying_price * div_discount * _norm_cdf(-d1)
        )
    theta_per_day = theta / 365.0

    # Vega (for 1 percentage point change in IV — divide by 100 for "per 1 vol point")
    vega = inputs.underlying_price * div_discount * _norm_pdf(d1) * sqrt_t
    vega_per_pct = vega / 100.0

    # Rho (for 1 percentage point change in rate — divide by 100)
    if is_call:
        rho = inputs.strike * inputs.time_to_expiry_years * discount * _norm_cdf(d2)
    else:
        rho = -inputs.strike * inputs.time_to_expiry_years * discount * _norm_cdf(-d2)
    rho_per_pct = rho / 100.0

    return Greeks(
        delta=delta,
        gamma=gamma,
        theta=theta_per_day,
        vega=vega_per_pct,
        rho=rho_per_pct,
        iv=inputs.volatility,
    )


def calculate_vanna(inputs: BlackScholesInput) -> float:
    """Hull canonical Vanna = ∂Delta/∂σ = -e^(-qT) × N'(d1) × d2 / σ.

    Per-unit-σ change (multiply by 0.01 for per-1pct convention).

    Returns 0.0 si T<=0 o σ<=0 (degenerate, mirror calculate_greeks pattern).

    ADR-011 D6 amendment Sprint 13 gex-b (math accuracy Hull canonical).
    """
    if inputs.time_to_expiry_years <= 0 or inputs.volatility <= 0:
        return 0.0
    d1, d2 = calculate_d1_d2(inputs)
    div_discount = math.exp(-inputs.dividend_yield * inputs.time_to_expiry_years)
    return -div_discount * _norm_pdf(d1) * d2 / inputs.volatility


def calculate_charm(inputs: BlackScholesInput) -> float:
    """Hull canonical Charm = ∂Delta/∂T (rate of delta decay).

    For call: q × e^(-qT) × N(d1) - e^(-qT) × N'(d1) × [2(r-q)T - d2×σ√T] / (2T×σ√T)
    For put: -q × e^(-qT) × N(-d1) - e^(-qT) × N'(d1) × [2(r-q)T - d2×σ√T] / (2T×σ√T)

    Returns per-year value. Caller divides by 365 for per-day convention.

    Returns 0.0 si T<=0 o σ<=0 (degenerate, mirror calculate_greeks pattern).

    ADR-011 D6 amendment Sprint 13 gex-b (math accuracy Hull canonical).
    """
    if inputs.time_to_expiry_years <= 0 or inputs.volatility <= 0:
        return 0.0

    d1, d2 = calculate_d1_d2(inputs)
    T = inputs.time_to_expiry_years
    sqrt_t = math.sqrt(T)
    sigma_sqrt_t = inputs.volatility * sqrt_t
    div_discount = math.exp(-inputs.dividend_yield * T)
    is_call = inputs.option_type == "call"

    # Second term common (both call/put)
    second_term = div_discount * _norm_pdf(d1) * (
        2 * (inputs.risk_free_rate - inputs.dividend_yield) * T - d2 * sigma_sqrt_t
    ) / (2 * T * sigma_sqrt_t)

    # First term differs by option type
    if is_call:
        first_term = inputs.dividend_yield * div_discount * _norm_cdf(d1)
    else:
        first_term = -inputs.dividend_yield * div_discount * _norm_cdf(-d1)

    return first_term - second_term


def implied_volatility(
    market_price: float,
    underlying_price: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    option_type: Literal["call", "put"],
    dividend_yield: float = 0.0,
    tolerance: float = 0.0001,
    max_iterations: int = 100,
) -> float:
    """
    Calculate implied volatility from market price using Newton-Raphson.

    Returns IV as decimal (e.g., 0.30 for 30%).
    """
    # Initial guess: use a reasonable starting point
    sigma = 0.30

    for _ in range(max_iterations):
        inputs = BlackScholesInput(
            underlying_price=underlying_price,
            strike=strike,
            time_to_expiry_years=time_to_expiry_years,
            risk_free_rate=risk_free_rate,
            volatility=sigma,
            option_type=option_type,
            dividend_yield=dividend_yield,
        )

        price = black_scholes_price(inputs)
        greeks = calculate_greeks(inputs)
        # vega is "per 1 vol point" — multiply by 100 to get per unit
        vega_per_unit = greeks.vega * 100

        diff = price - market_price
        if abs(diff) < tolerance:
            return sigma
        if vega_per_unit < 1e-10:
            break

        sigma = sigma - diff / vega_per_unit
        # Keep sigma in reasonable bounds
        sigma = max(0.01, min(sigma, 5.0))

    return sigma


def time_to_expiry_years(today: date, expiration: date) -> float:
    """Convert calendar date difference to years (using 365 day calendar)."""
    delta = (expiration - today).days
    return max(delta / 365.0, 0.0)
