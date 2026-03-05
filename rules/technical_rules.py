"""
Technical Rules based on the 68-feature pipeline
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
import logging
from .base_rule import BaseRule, RuleMetadata, Signal

logger = logging.getLogger(__name__)


class MovingAverageCrossRule(BaseRule):
    """Moving Average Crossover Strategy"""

    def __init__(
        self,
        metadata: RuleMetadata,
        fast_period: int = 20,
        slow_period: int = 50
    ):
        params = {
            'fast_period': fast_period,
            'slow_period': slow_period
        }
        super().__init__(metadata, params)
        self.fast_period = fast_period
        self.slow_period = slow_period

    def evaluate(self, row: pd.Series, context: Optional[Dict[str, Any]] = None) -> Signal:
        """Golden cross = buy, Death cross = sell"""
        fast_ma = row.get(f'sma_{self.fast_period}')
        slow_ma = row.get(f'sma_{self.slow_period}')

        if pd.isna(fast_ma) or pd.isna(slow_ma):
            return Signal('hold', 0.0, "Missing MA data")

        # Calculate crossover strength
        diff = (fast_ma - slow_ma) / slow_ma
        confidence = min(abs(diff) * 10, 1.0)  # Scale to 0-1

        if fast_ma > slow_ma:
            reasoning = f"Golden Cross: SMA{self.fast_period} ({fast_ma:.2f}) > SMA{self.slow_period} ({slow_ma:.2f})"
            return Signal('buy', confidence, reasoning)
        elif fast_ma < slow_ma:
            reasoning = f"Death Cross: SMA{self.fast_period} ({fast_ma:.2f}) < SMA{self.slow_period} ({slow_ma:.2f})"
            return Signal('sell', confidence, reasoning)
        else:
            return Signal('hold', 0.0, "MAs equal")

    def get_required_features(self) -> List[str]:
        return [f'sma_{self.fast_period}', f'sma_{self.slow_period}']


class RSIRule(BaseRule):
    """RSI Overbought/Oversold Strategy"""

    def __init__(
        self,
        metadata: RuleMetadata,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0
    ):
        period = int(period)
        oversold = float(oversold)
        overbought = float(overbought)

        if not (0 <= oversold < overbought <= 100):
            raise ValueError(
                f"Invalid RSI thresholds: oversold={oversold}, overbought={overbought}. "
                f"Required: 0 <= oversold < overbought <= 100"
            )

        params = {
            'period': period,
            'oversold': oversold,
            'overbought': overbought
        }
        super().__init__(metadata, params)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def evaluate(self, row: pd.Series, context: Optional[Dict[str, Any]] = None) -> Signal:
        """RSI < 30 = buy, RSI > 70 = sell"""
        rsi = row.get('rsi')

        if pd.isna(rsi):
            return Signal('hold', 0.0, "Missing RSI data")

        if rsi < self.oversold:
            # More oversold = higher confidence
            confidence = min((self.oversold - rsi) / self.oversold, 1.0)
            reasoning = f"RSI oversold: {rsi:.2f} < {self.oversold}"
            return Signal('buy', confidence, reasoning)
        elif rsi > self.overbought:
            # More overbought = higher confidence
            confidence = min((rsi - self.overbought) / (100 - self.overbought), 1.0)
            reasoning = f"RSI overbought: {rsi:.2f} > {self.overbought}"
            return Signal('sell', confidence, reasoning)
        else:
            return Signal('hold', 0.0, f"RSI neutral: {rsi:.2f}")

    def get_required_features(self) -> List[str]:
        return ['rsi']


class BollingerBandsRule(BaseRule):
    """Bollinger Bands Mean Reversion Strategy"""

    def __init__(
        self,
        metadata: RuleMetadata,
        period: int = 20,
        std_dev: float = 2.0
    ):
        params = {
            'period': period,
            'std_dev': std_dev
        }
        super().__init__(metadata, params)
        self.period = period
        self.std_dev = std_dev

    def evaluate(self, row: pd.Series, context: Optional[Dict[str, Any]] = None) -> Signal:
        """Price touches lower band = buy, upper band = sell"""
        price = row['close']
        bb_middle = row.get('bb_middle')
        bb_upper = row.get('bb_upper')
        bb_lower = row.get('bb_lower')

        if pd.isna(bb_middle) or pd.isna(bb_upper) or pd.isna(bb_lower):
            return Signal('hold', 0.0, "Missing BB data")

        # Calculate position within bands
        bb_width = bb_upper - bb_lower
        if bb_width == 0:
            return Signal('hold', 0.0, "BB width = 0")

        position = (price - bb_lower) / bb_width  # 0 = lower band, 1 = upper band

        if position < 0.1:  # Near lower band
            confidence = 0.1 - position if position < 0.1 else 0.0
            confidence = min(confidence * 10, 1.0)
            reasoning = f"Price near lower BB: {price:.2f} (position: {position:.2%})"
            return Signal('buy', confidence, reasoning)
        elif position > 0.9:  # Near upper band
            confidence = position - 0.9 if position > 0.9 else 0.0
            confidence = min(confidence * 10, 1.0)
            reasoning = f"Price near upper BB: {price:.2f} (position: {position:.2%})"
            return Signal('sell', confidence, reasoning)
        else:
            return Signal('hold', 0.0, f"Price in BB middle: {position:.2%}")

    def get_required_features(self) -> List[str]:
        return [
            'close',
            'bb_middle',
            'bb_upper',
            'bb_lower'
        ]


class MACDRule(BaseRule):
    """MACD Crossover Strategy"""

    def __init__(self, metadata: RuleMetadata):
        super().__init__(metadata, params={})

    def evaluate(self, row: pd.Series, context: Optional[Dict[str, Any]] = None) -> Signal:
        """MACD crosses above signal = buy, below = sell"""
        macd = row.get('macd')
        macd_signal = row.get('macd_signal')

        if pd.isna(macd) or pd.isna(macd_signal):
            return Signal('hold', 0.0, "Missing MACD data")

        diff = macd - macd_signal
        confidence = min(abs(diff) / 2.0, 1.0)  # Scale to 0-1

        if diff > 0:
            reasoning = f"MACD bullish: {macd:.4f} > {macd_signal:.4f}"
            return Signal('buy', confidence, reasoning)
        elif diff < 0:
            reasoning = f"MACD bearish: {macd:.4f} < {macd_signal:.4f}"
            return Signal('sell', confidence, reasoning)
        else:
            return Signal('hold', 0.0, "MACD neutral")

    def get_required_features(self) -> List[str]:
        return ['macd', 'macd_signal']


class VolumeBreakoutRule(BaseRule):
    """Volume Breakout Strategy"""

    def __init__(
        self,
        metadata: RuleMetadata,
        volume_ma_period: int = 20,
        breakout_multiplier: float = 2.0
    ):
        params = {
            'volume_ma_period': volume_ma_period,
            'breakout_multiplier': breakout_multiplier
        }
        super().__init__(metadata, params)
        self.volume_ma_period = volume_ma_period
        self.breakout_multiplier = breakout_multiplier

    def evaluate(self, row: pd.Series, context: Optional[Dict[str, Any]] = None) -> Signal:
        """High volume + price increase = buy"""
        volume = row.get('volume')
        volume_ma = row.get(f'volume_ma_{self.volume_ma_period}')
        price_change = row.get('price_change_pct')

        if pd.isna(volume) or pd.isna(volume_ma) or pd.isna(price_change):
            return Signal('hold', 0.0, "Missing volume/price data")

        volume_ratio = volume / volume_ma if volume_ma > 0 else 0

        # Volume breakout with positive price action
        if volume_ratio > self.breakout_multiplier and price_change > 0:
            confidence = min(volume_ratio / (self.breakout_multiplier * 2), 1.0)
            reasoning = f"Volume breakout: {volume_ratio:.2f}x avg, price +{price_change:.2%}"
            return Signal('buy', confidence, reasoning)
        # Volume breakout with negative price action
        elif volume_ratio > self.breakout_multiplier and price_change < 0:
            confidence = min(volume_ratio / (self.breakout_multiplier * 2), 1.0)
            reasoning = f"Volume breakout: {volume_ratio:.2f}x avg, price {price_change:.2%}"
            return Signal('sell', confidence, reasoning)
        else:
            return Signal('hold', 0.0, f"Volume normal: {volume_ratio:.2f}x")

    def get_required_features(self) -> List[str]:
        return ['volume', f'volume_ma_{self.volume_ma_period}', 'price_change_pct']


class TrendFollowingRule(BaseRule):
    """Multi-timeframe Trend Following"""

    def __init__(
        self,
        metadata: RuleMetadata,
        short_period: int = 20,
        medium_period: int = 50,
        long_period: int = 200
    ):
        params = {
            'short_period': short_period,
            'medium_period': medium_period,
            'long_period': long_period
        }
        super().__init__(metadata, params)
        self.short_period = short_period
        self.medium_period = medium_period
        self.long_period = long_period

    def evaluate(self, row: pd.Series, context: Optional[Dict[str, Any]] = None) -> Signal:
        """All MAs aligned = strong trend signal"""
        price = row['close']
        short_ma = row.get(f'sma_{self.short_period}')
        medium_ma = row.get(f'sma_{self.medium_period}')
        long_ma = row.get(f'sma_{self.long_period}')

        if any(pd.isna(x) for x in [short_ma, medium_ma, long_ma]):
            return Signal('hold', 0.0, "Missing MA data")

        # Uptrend: price > short > medium > long
        if price > short_ma > medium_ma > long_ma:
            # Calculate trend strength
            spread = (price - long_ma) / long_ma
            confidence = min(spread * 5, 1.0)
            reasoning = f"Strong uptrend: Price > SMA{self.short_period} > SMA{self.medium_period} > SMA{self.long_period}"
            return Signal('buy', confidence, reasoning)
        # Downtrend: price < short < medium < long
        elif price < short_ma < medium_ma < long_ma:
            spread = (long_ma - price) / long_ma
            confidence = min(spread * 5, 1.0)
            reasoning = f"Strong downtrend: Price < SMA{self.short_period} < SMA{self.medium_period} < SMA{self.long_period}"
            return Signal('sell', confidence, reasoning)
        else:
            return Signal('hold', 0.0, "No clear trend")

    def get_required_features(self) -> List[str]:
        return [
            'close',
            f'sma_{self.short_period}',
            f'sma_{self.medium_period}',
            f'sma_{self.long_period}'
        ]


class ATRVolatilityRule(BaseRule):
    """ATR-based Volatility Filter"""

    def __init__(
        self,
        metadata: RuleMetadata,
        period: int = 14,
        high_threshold: float = 0.05,  # 5% ATR
        low_threshold: float = 0.02    # 2% ATR
    ):
        params = {
            'period': period,
            'high_threshold': high_threshold,
            'low_threshold': low_threshold
        }
        super().__init__(metadata, params)
        self.period = period
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold

    def evaluate(self, row: pd.Series, context: Optional[Dict[str, Any]] = None) -> Signal:
        """High volatility = avoid, low volatility = opportunity"""
        atr = row.get('atr')
        price = row['close']

        if pd.isna(atr) or price == 0:
            return Signal('hold', 0.0, "Missing ATR data")

        atr_pct = atr / price

        if atr_pct > self.high_threshold:
            confidence = min((atr_pct - self.high_threshold) / self.high_threshold, 1.0)
            reasoning = f"High volatility: ATR {atr_pct:.2%} > {self.high_threshold:.2%}"
            return Signal('sell', confidence, reasoning)  # Risk-off
        elif atr_pct < self.low_threshold:
            confidence = min((self.low_threshold - atr_pct) / self.low_threshold, 1.0)
            reasoning = f"Low volatility: ATR {atr_pct:.2%} < {self.low_threshold:.2%}"
            return Signal('buy', confidence, reasoning)  # Opportunity
        else:
            return Signal('hold', 0.0, f"Normal volatility: ATR {atr_pct:.2%}")

    def get_required_features(self) -> List[str]:
        return ['close', 'atr']


class RsiMacdRule(BaseRule):
    """Combined RSI + MACD Strategy (single rule, no internal rule delegation)"""

    def __init__(
        self,
        metadata: RuleMetadata,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9
    ):
        rsi_period = int(rsi_period)
        rsi_oversold = float(rsi_oversold)
        rsi_overbought = float(rsi_overbought)
        macd_fast = int(macd_fast)
        macd_slow = int(macd_slow)
        macd_signal = int(macd_signal)

        if not (0 <= rsi_oversold < rsi_overbought <= 100):
            raise ValueError(
                f"Invalid RSI thresholds: rsi_oversold={rsi_oversold}, rsi_overbought={rsi_overbought}. "
                f"Required: 0 <= rsi_oversold < rsi_overbought <= 100"
            )

        params = {
            'rsi_period': rsi_period,
            'rsi_oversold': rsi_oversold,
            'rsi_overbought': rsi_overbought,
            'macd_fast': macd_fast,
            'macd_slow': macd_slow,
            'macd_signal': macd_signal,
        }
        super().__init__(metadata, params)
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    def evaluate(self, row: pd.Series, context: Optional[Dict[str, Any]] = None) -> Signal:
        """Buy: RSI<30 AND MACD>Signal. Sell: RSI>70 OR MACD<Signal."""
        rsi = row.get('rsi')
        macd = row.get('macd')
        macd_signal = row.get('macd_signal')

        if any(pd.isna(v) for v in [rsi, macd, macd_signal]):
            return Signal('hold', 0.0, "Missing RSI/MACD data")

        rsi_oversold = rsi < self.rsi_oversold
        macd_bullish = macd > macd_signal
        rsi_overbought = rsi > self.rsi_overbought
        macd_bearish = macd < macd_signal

        # Buy: both conditions must agree (AND)
        if rsi_oversold and macd_bullish:
            rsi_conf = min((self.rsi_oversold - rsi) / self.rsi_oversold, 1.0)
            macd_conf = min(abs(macd - macd_signal) / 2.0, 1.0)
            confidence = (rsi_conf + macd_conf) / 2.0
            reasoning = f"RSI oversold ({rsi:.1f}) AND MACD bullish ({macd:.4f}>{macd_signal:.4f})"
            return Signal('buy', confidence, reasoning)

        # Sell: either condition triggers (OR)
        if rsi_overbought:
            confidence = min((rsi - self.rsi_overbought) / (100 - self.rsi_overbought), 1.0)
            reasoning = f"RSI overbought: {rsi:.1f} > {self.rsi_overbought}"
            return Signal('sell', confidence, reasoning)

        if macd_bearish:
            confidence = min(abs(macd - macd_signal) / 2.0, 1.0)
            reasoning = f"MACD bearish: {macd:.4f} < {macd_signal:.4f}"
            return Signal('sell', confidence, reasoning)

        return Signal('hold', 0.0, f"Neutral: RSI={rsi:.1f}, MACD={macd:.4f}")

    def get_required_features(self) -> List[str]:
        return ['rsi', 'macd', 'macd_signal']


if __name__ == "__main__":
    # Test code
    from datetime import datetime

    metadata = RuleMetadata(
        rule_id="TECH_MA_001",
        name="MA Crossover",
        description="20/50 SMA crossover",
        source="technical"
    )

    rule = MovingAverageCrossRule(metadata, fast_period=20, slow_period=50)
    print(f"Required features: {rule.get_required_features()}")

    # Test with sample data
    test_row = pd.Series({
        'close': 100,
        'sma_20': 102,
        'sma_50': 98
    })

    signal = rule.evaluate(test_row)
    print(f"Signal: {signal.action} (confidence: {signal.confidence:.2f})")
    print(f"Reasoning: {signal.reasoning}")
