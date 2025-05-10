# strategies/base_strategy.py
from abc import ABC, abstractmethod
import pandas as pd
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    Each strategy must implement the generate_signal method.
    """
    def __init__(self, params: Dict[str, Any]):
        self.params = params if params is not None else {} 
        logger.info(f"Initialized strategy: {self.__class__.__name__} with params: {self.params}")

    @abstractmethod
    def generate_signal(self, df_with_ta: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        Analyzes kline data with TAs and generates a trading signal.
        Args:
            df_with_ta (pd.DataFrame): Kline data with technical indicators.
                                       Last row is the most recent candle.
        Returns:
            Dict or None: Signal details (e.g., {"signal": "BUY_LONG", "entry_price": float, "reason": str}) 
                          or None if no signal.
        """
        pass

    def calculate_sl_tp(self, entry_price: float, signal_type: str, 
                        sl_pct: float, tp_pct: float, 
                        price_precision: int = 4) -> Dict[str, float]:
        """
        Calculates Stop Loss (SL) and Take Profit (TP) levels.
        """
        logger.debug(
            f"Calculating SL/TP. Entry: {entry_price}, Type: {signal_type}, SL%: {sl_pct}, "
            f"TP%: {tp_pct}, Precision: {price_precision}"
        )
        stop_loss, take_profit = 0.0, 0.0

        if not (isinstance(entry_price, (int, float)) and entry_price > 0):
            logger.error(f"Invalid entry_price ({entry_price}) for SL/TP calc. Returning 0 for SL/TP.")
            return {"stop_loss": 0.0, "take_profit": 0.0}
        
        try:
            sl_pct = float(sl_pct) if sl_pct is not None else 0.0
            tp_pct = float(tp_pct) if tp_pct is not None else 0.0
        except (ValueError, TypeError):
            logger.warning(f"SL/TP percentages are not valid numbers. SL_pct: {sl_pct}, TP_pct: {tp_pct}. Using 0%.")
            sl_pct = 0.0
            tp_pct = 0.0

        if sl_pct <= 0: logger.warning(f"Invalid or zero sl_pct: {sl_pct}. Stop loss will be at entry or zero if not applicable.")
        if tp_pct <= 0: logger.warning(f"Invalid or zero tp_pct: {tp_pct}. Take profit will be at entry or zero if not applicable.")

        if signal_type == "BUY_LONG":
            stop_loss = entry_price * (1 - sl_pct) if sl_pct > 0 else entry_price 
            take_profit = entry_price * (1 + tp_pct) if tp_pct > 0 else entry_price
        elif signal_type == "SELL_SHORT":
            stop_loss = entry_price * (1 + sl_pct) if sl_pct > 0 else entry_price
            take_profit = entry_price * (1 - tp_pct) if tp_pct > 0 else entry_price
        else:
            logger.error(f"Unknown signal type '{signal_type}' for SL/TP calculation. SL/TP set to entry.")
            return {"stop_loss": round(entry_price, price_precision), 
                    "take_profit": round(entry_price, price_precision)}

        min_diff_factor = 1 / (10**price_precision) # Smallest possible difference based on precision
        if signal_type == "BUY_LONG" and sl_pct > 0 and stop_loss >= entry_price:
            logger.warning(
                f"Calculated SL ({stop_loss}) for BUY_LONG is at or above entry ({entry_price}). "
                f"Adjusting SL slightly below entry (by {min_diff_factor})."
            )
            # Adjust SL to be at least one 'tick' (based on precision) below entry
            # This is a simplified tick, real tick size from exchange is better
            stop_loss = entry_price - min_diff_factor
        elif signal_type == "SELL_SHORT" and sl_pct > 0 and stop_loss <= entry_price:
            logger.warning(
                f"Calculated SL ({stop_loss}) for SELL_SHORT is at or below entry ({entry_price}). "
                f"Adjusting SL slightly above entry (by {min_diff_factor})."
            )
            stop_loss = entry_price + min_diff_factor


        stop_loss_final = round(stop_loss, price_precision)
        take_profit_final = round(take_profit, price_precision)

        logger.info(
            f"Calculated SL: {stop_loss_final:.{price_precision}f}, TP: {take_profit_final:.{price_precision}f} "
            f"for entry {entry_price:.{price_precision}f}"
        )
        return {"stop_loss": stop_loss_final, "take_profit": take_profit_final}