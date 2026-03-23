from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class RORResult:
    ror: float
    ci_lower: float
    ci_upper: float
    significant: bool
    case_count: int


@dataclass
class PRRResult:
    prr: float
    chi_squared: float
    p_value: float
    significant: bool
    case_count: int


@dataclass
class BCPNNResult:
    ic: float
    ic_lower: float
    ic_upper: float
    significant: bool
    case_count: int


def calculate_ror(a: int, b: int, c: int, d: int) -> RORResult:
    """Calculate Reporting Odds Ratio from 2x2 contingency table.

    a=drug+event, b=drug+no_event, c=no_drug+event, d=no_drug+no_event
    """
    if b * c == 0:
        return RORResult(ror=0.0, ci_lower=0.0, ci_upper=0.0, significant=False, case_count=a)
    ror = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d) if all(x > 0 for x in [a, b, c, d]) else float("inf")
    ln_ror = math.log(ror) if ror > 0 else 0.0
    ci_lower = math.exp(ln_ror - 1.96 * se)
    ci_upper = math.exp(ln_ror + 1.96 * se)
    return RORResult(ror=ror, ci_lower=ci_lower, ci_upper=ci_upper, significant=ci_lower > 1.0, case_count=a)


def calculate_prr(a: int, b: int, c: int, d: int) -> PRRResult:
    """Calculate Proportional Reporting Ratio from 2x2 contingency table."""
    if (a + b) == 0 or (c + d) == 0:
        return PRRResult(prr=0.0, chi_squared=0.0, p_value=1.0, significant=False, case_count=a)
    prr = (a / (a + b)) / (c / (c + d))
    n = a + b + c + d
    expected_a = (a + b) * (a + c) / n if n > 0 else 0.0
    chi2 = ((a - expected_a) ** 2) / expected_a if expected_a > 0 else 0.0
    from scipy.stats import chi2 as chi2_dist
    p_value = float(chi2_dist.sf(chi2, df=1))
    return PRRResult(
        prr=prr,
        chi_squared=chi2,
        p_value=p_value,
        significant=prr >= 2.0 and chi2 >= 4.0,
        case_count=a,
    )


def calculate_bcpnn(a: int, b: int, c: int, d: int) -> BCPNNResult:
    """Calculate Bayesian Confidence Propagation Neural Network IC."""
    n = a + b + c + d
    if n == 0:
        return BCPNNResult(ic=0.0, ic_lower=0.0, ic_upper=0.0, significant=False, case_count=a)
    expected = ((a + b) * (a + c)) / n
    if expected == 0 or a == 0:
        return BCPNNResult(ic=0.0, ic_lower=0.0, ic_upper=0.0, significant=False, case_count=a)
    ic = math.log2(a / expected)
    se = 1 / (math.sqrt(a) * math.log(2))
    ci_lower = ic - 1.96 * se
    ci_upper = ic + 1.96 * se
    return BCPNNResult(ic=ic, ic_lower=ci_lower, ic_upper=ci_upper, significant=ci_lower > 0.0, case_count=a)
