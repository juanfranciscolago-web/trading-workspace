"""ATM IV compute — D3 canonical formula (S.6.iv-d).

Single source of truth for "ATM IV from a Schwab options chain", per
ADR-005 D3. Used by:

- IvHistoryWorker (S.6.iv-c): writes daily snapshots to iv_history.
- SchwabDataLayer (S.6.iv-d): computes today's ATM IV to feed iv_rank
  compute against historical values from iv_history.

Both call sites MUST use this same function so that "today's ATM IV"
and "historical ATM IV" share semantics (avg call+put at strike closest
to spot in first expiration). Mismatch would invalidate iv_rank.

Extracted from IvHistoryWorker._compute_atm_iv (originally S.6.iv-c) in
S.6.iv-d per F10 unification — see ADR-005 + decision D-κ.
"""
from __future__ import annotations


def compute_atm_iv(chain: dict, spot: float) -> float | None:
    """Compute ATM IV per ADR-005 D3.

    ATM strike = strike closest to spot in first expiration.
    ATM IV = avg(call.iv, put.iv); fallback non-zero side; None if both 0.

    Args:
        chain: Schwab normalized chain dict with 'expirations', 'calls', 'puts'.
        spot: Underlying spot price.

    Returns:
        ATM IV value, or None if uncomputable (empty chain, invalid spot,
        or both call/put IV are 0).
    """
    expirations = chain.get("expirations", [])
    if not expirations or spot <= 0:
        return None

    first_exp = expirations[0]
    calls = chain.get("calls", {}).get(first_exp, {})
    puts = chain.get("puts", {}).get(first_exp, {})

    if not calls and not puts:
        return None

    # Find ATM strike (closest to spot) — use calls dict primarily.
    strikes_dict = calls or puts
    if not strikes_dict:
        return None
    atm_strike = min(strikes_dict.keys(), key=lambda s: abs(float(s) - spot))

    call_iv = calls.get(atm_strike, {}).get("iv", 0.0) if calls else 0.0
    put_iv = puts.get(atm_strike, {}).get("iv", 0.0) if puts else 0.0

    if call_iv > 0 and put_iv > 0:
        return (call_iv + put_iv) / 2
    if call_iv > 0:
        return call_iv
    if put_iv > 0:
        return put_iv
    return None
