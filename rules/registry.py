"""Rule registry: maps rule_type strings to rule classes and handles instantiation.

This module is the single source of truth for:
- Which rule types are available (RULE_CLASS_REGISTRY)
- Fuzzy name aliases (RULE_TYPE_ALIASES)
- Canonical rule_type resolution
- Parameter normalization per rule type
- Rule instantiation with signature introspection
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, Tuple

from rules.base_rule import RuleMetadata
from rules.technical_rules import (
    ATRVolatilityRule,
    BollingerBandsRule,
    MACDRule,
    MovingAverageCrossRule,
    RSIRule,
    RsiMacdRule,
    TrendFollowingRule,
    VolumeBreakoutRule,
)

logger = logging.getLogger(__name__)


class UnknownRuleTypeError(ValueError):
    """Raised when RULE_TYPE cannot be mapped to an existing rule class."""


RULE_CLASS_REGISTRY = {
    "RSI": RSIRule,
    "MACD": MACDRule,
    "RSI_MACD": RsiMacdRule,
    "MOVING_AVERAGE_CROSS": MovingAverageCrossRule,
    "BOLLINGER_BANDS": BollingerBandsRule,
    "VOLUME_BREAKOUT": VolumeBreakoutRule,
    "TREND_FOLLOWING": TrendFollowingRule,
    "ATR_VOLATILITY": ATRVolatilityRule,
}

RULE_TYPE_ALIASES = {
    "RSIMACD": "RSI_MACD",
    "RSI+MACD": "RSI_MACD",
    "MA_CROSS": "MOVING_AVERAGE_CROSS",
    "MOVINGAVERAGECROSS": "MOVING_AVERAGE_CROSS",
}


def canonical_rule_type(rule_type_raw: str) -> str:
    """Resolve a raw rule_type string to its canonical form.

    Raises ``UnknownRuleTypeError`` if no match is found.
    """
    normalized = rule_type_raw.strip().upper()
    canonical = RULE_TYPE_ALIASES.get(normalized, normalized)
    if canonical not in RULE_CLASS_REGISTRY:
        raise UnknownRuleTypeError(f"Unknown RULE_TYPE: {rule_type_raw}")
    return canonical


def normalize_rule_params(canonical_rt: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize fuzzy parameter names to canonical names for specific rule types."""
    normalized = dict(params)

    if canonical_rt == "RSI_MACD":
        if "oversold" in normalized and "rsi_oversold" not in normalized:
            normalized["rsi_oversold"] = normalized["oversold"]
        if "overbought" in normalized and "rsi_overbought" not in normalized:
            normalized["rsi_overbought"] = normalized["overbought"]
        if "period" in normalized and "rsi_period" not in normalized:
            normalized["rsi_period"] = normalized["period"]
        if "fast" in normalized and "macd_fast" not in normalized:
            normalized["macd_fast"] = normalized["fast"]
        if "slow" in normalized and "macd_slow" not in normalized:
            normalized["macd_slow"] = normalized["slow"]
        if "signal" in normalized and "macd_signal" not in normalized:
            normalized["macd_signal"] = normalized["signal"]

    return normalized


def instantiate_rule(
    canonical_rt: str,
    params: Dict[str, Any],
    run_id: str,
) -> Tuple[Any, Dict[str, Any]]:
    """Create a rule instance by introspecting the constructor signature.

    Returns ``(rule_instance, normalized_params)``.
    """
    rule_class = RULE_CLASS_REGISTRY[canonical_rt]
    normalized_params = normalize_rule_params(canonical_rt, params)

    signature = inspect.signature(rule_class.__init__)
    constructor_kwargs: Dict[str, Any] = {}
    for name in signature.parameters:
        if name in ("self", "metadata"):
            continue
        if name in normalized_params and normalized_params[name] is not None:
            constructor_kwargs[name] = normalized_params[name]

    metadata = RuleMetadata(
        rule_id=f"{canonical_rt}_{run_id[:8]}",
        name=canonical_rt,
        description=f"{canonical_rt} worker execution",
        source="technical",
    )
    rule = rule_class(metadata=metadata, **constructor_kwargs)
    return rule, normalized_params
