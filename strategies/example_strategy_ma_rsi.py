# strategies/example_strategy_ma_rsi.py
import pandas as pd
from .base_strategy import BaseStrategy # Relative import
import logging
from typing import Dict, Any, Optional
import numpy as np # For np.nan if needed for other things, pandas handles NaNs from TA

logger = logging.getLogger(__name__)

class MA_RSI_Strategy(BaseStrategy):
    """
    Example Strategy: Simple Moving Average (SMA) Crossover combined with RSI.
    - BUY LONG: Short SMA crosses above Long SMA on the signal_candle (previous closed)
                AND RSI on signal_candle is not overbought.
    - SELL SHORT: Short SMA crosses below Long SMA on the signal_candle
                  AND RSI on signal_candle is not oversold.
    Entry price for the signal is based on the close of the last_candle (most recent data).
    """
    def generate_signal(self, df_with_ta: pd.DataFrame) -> Optional[Dict[str, Any]]:
        try:
            short_ma_period = int(self.params.get('short_ma_period', 9))
            long_ma_period = int(self.params.get('long_ma_period', 21))
            rsi_period = int(self.params.get('rsi_period', 14))
            rsi_oversold = float(self.params.get('rsi_oversold', 30))
            rsi_overbought = float(self.params.get('rsi_overbought', 70))
        except (ValueError, TypeError) as e:
            logger.error(f"MA_RSI_Strategy: Invalid parameter type in config for strategy {self.__class__.__name__}: {e}", exc_info=True)
            return None
        
        if not (short_ma_period > 0 and long_ma_period > 0 and rsi_period > 0 and \
                0 < rsi_oversold < 100 and 0 < rsi_overbought < 100 and rsi_oversold < rsi_overbought):
            logger.error(f"MA_RSI_Strategy: Invalid strategy parameter values. Check periods, oversold/overbought levels. Params: {self.params}")
            return None


        short_sma_col = f"SMA_{short_ma_period}"
        long_sma_col = f"SMA_{long_ma_period}"
        rsi_col = f"RSI_{rsi_period}"

        required_cols = [short_sma_col, long_sma_col, rsi_col, 'close', 'open', 'high', 'low'] # Added OHLC for completeness
        if not all(col in df_with_ta.columns for col in required_cols):
            missing = [col for col in required_cols if col not in df_with_ta.columns]
            logger.error(f"MA_RSI_Strategy: Missing required TA/data columns: {missing}. Available: {df_with_ta.columns.tolist()}")
            return None
        
        # Need at least 3 rows for prev_prev_candle logic for crossover,
        # plus TA libraries might need more initial data points not reflected in final df_with_ta length
        # A more robust check might consider the longest period used in TA + number of candles for logic.
        if len(df_with_ta) < max(long_ma_period, rsi_period, 3) : # Check against longest period or min 3
             logger.debug(f"MA_RSI_Strategy: Not enough data (have {len(df_with_ta)}, need more based on indicator periods or min 3).")
             return None


        # -1: current (most recent) candle. Used for entry price (close of this candle).
        # -2: previous fully closed candle (this is our "signal candle").
        # -3: candle before signal candle (for checking crossover condition).
        try:
            # Ensure data types are numeric before indexing. df_with_ta should already be cleaned by indicator_calculator
            last_candle = df_with_ta.iloc[-1]
            signal_candle = df_with_ta.iloc[-2] 
            candle_before_signal = df_with_ta.iloc[-3]
        except IndexError:
            logger.debug(f"MA_RSI_Strategy: Not enough rows in DataFrame (have {len(df_with_ta)}) for candle indexing logic. Need at least 3.")
            return None


        # Check for NaN values in critical series at specific points
        # pd.isna should handle np.nan correctly
        critical_values_for_signal = [
            candle_before_signal[short_sma_col], candle_before_signal[long_sma_col],
            signal_candle[short_sma_col], signal_candle[long_sma_col],
            signal_candle[rsi_col], last_candle['close']
        ]
        if any(pd.isna(val) for val in critical_values_for_signal):
            logger.debug("MA_RSI_Strategy: NaN values found in critical data points for signal generation. Skipping.")
            # Log which specific value was NaN for better debugging
            nan_debug = {
                "cbs_short_sma": pd.isna(candle_before_signal[short_sma_col]),
                "cbs_long_sma": pd.isna(candle_before_signal[long_sma_col]),
                "sc_short_sma": pd.isna(signal_candle[short_sma_col]),
                "sc_long_sma": pd.isna(signal_candle[long_sma_col]),
                "sc_rsi": pd.isna(signal_candle[rsi_col]),
                "lc_close": pd.isna(last_candle['close']),
            }
            logger.debug(f"NaN debug info: {nan_debug}")
            return None

        entry_price = float(last_candle['close']) # Ensure entry price is float

        # Log with proper formatting for floats
        signal_candle_time = signal_candle.name if hasattr(signal_candle, 'name') and signal_candle.name else 'N/A'
        logger.debug(f"MA_RSI Strategy Check - Signal Candle Time: {signal_candle_time}")
        logger.debug(f"  SignalCandle: Close={signal_candle['close']:.4f}, Entry (LastClose)={entry_price:.4f}")
        logger.debug(f"  SignalCandle: {short_sma_col}={signal_candle[short_sma_col]:.2f}, {long_sma_col}={signal_candle[long_sma_col]:.2f}")
        logger.debug(f"  CandleBeforeSignal: {short_sma_col}={candle_before_signal[short_sma_col]:.2f}, {long_sma_col}={candle_before_signal[long_sma_col]:.2f}")
        logger.debug(f"  SignalCandle: {rsi_col}={signal_candle[rsi_col]:.2f}, OB_Thresh={rsi_overbought}, OS_Thresh={rsi_oversold}")

        # Buy Conditions
        short_crossed_above_long = (candle_before_signal[short_sma_col] < candle_before_signal[long_sma_col] and
                                    signal_candle[short_sma_col] > signal_candle[long_sma_col])
        rsi_not_overbought = signal_candle[rsi_col] < rsi_overbought 

        if short_crossed_above_long and rsi_not_overbought:
            reason = (f"SMA({short_ma_period}) crossed UP SMA({long_ma_period}) "
                      f"& SignalRSI({signal_candle[rsi_col]:.2f}) < {rsi_overbought}")
            logger.info(f"BUY LONG Signal: {reason} | Entry (based on last_close): {entry_price:.4f}")
            return {"signal": "BUY_LONG", "entry_price": entry_price, "reason": reason}

        # Sell Conditions
        short_crossed_below_long = (candle_before_signal[short_sma_col] > candle_before_signal[long_sma_col] and
                                    signal_candle[short_sma_col] < signal_candle[long_sma_col])
        rsi_not_oversold = signal_candle[rsi_col] > rsi_oversold

        if short_crossed_below_long and rsi_not_oversold:
            reason = (f"SMA({short_ma_period}) crossed DOWN SMA({long_ma_period}) "
                      f"& SignalRSI({signal_candle[rsi_col]:.2f}) > {rsi_oversold}")
            logger.info(f"SELL SHORT Signal: {reason} | Entry (based on last_close): {entry_price:.4f}")
            return {"signal": "SELL_SHORT", "entry_price": entry_price, "reason": reason}

        logger.debug("MA_RSI_Strategy: No signal generated for this candle set.")
        return None