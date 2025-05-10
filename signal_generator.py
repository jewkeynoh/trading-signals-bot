# signal_generator.py
import logging
import importlib
from pathlib import Path
import pandas as pd
from typing import Dict, Any, Optional, Type 
import sys

# Ensure strategies can be imported by adding project root or relevant paths
# This setup assumes signal_generator.py is at the project root or
# the main_bot.py (which calls it) correctly sets up sys.path.
try:
    from strategies.base_strategy import BaseStrategy
except ImportError:
    # This dynamic path modification is a fallback.
    # Ideally, the project should be structured as a package or run from a context
    # where 'strategies' is directly importable.
    current_file_dir = Path(__file__).resolve().parent
    project_root_paths = [current_file_dir, current_file_dir.parent] 
    for p_path in project_root_paths:
        if str(p_path) not in sys.path:
            sys.path.insert(0, str(p_path))
    
    # Retry import after path modification
    try:
        from strategies.base_strategy import BaseStrategy
    except ImportError as e_retry:
        logging.getLogger(__name__).critical(f"Failed to import BaseStrategy even after path modification: {e_retry}", exc_info=True)
        # Depending on how critical this is, you might raise the error or exit.
        # For now, if main_bot.py calls this, its own import handling might suffice.
        raise # Re-raise the error to be caught by the caller


logger = logging.getLogger(__name__)

class SignalGenerator:
    def __init__(self, strategy_module_path: str, strategy_class_name: str, 
                 strategy_params: Dict[str, Any], risk_params: Dict[str, Any]):
        self.strategy_module_path = strategy_module_path
        self.strategy_class_name = strategy_class_name
        # Ensure params are actual dictionaries, not None
        self.strategy_params = strategy_params if strategy_params is not None else {}
        self.risk_params = risk_params if risk_params is not None else {}
        
        self.strategy: Optional[BaseStrategy] = self._load_strategy(
            self.strategy_module_path, self.strategy_class_name, self.strategy_params
        )
        
        if not self.strategy:
            # Logger might not be fully configured if this init fails early in main_bot.py
            # So, also print to stderr for critical failures.
            err_msg = (f"SignalGenerator init failed: Could not load strategy '{self.strategy_class_name}' "
                       f"from module '{self.strategy_module_path}'.")
            logger.critical(err_msg)
            # print(f"CRITICAL ERROR (SignalGenerator): {err_msg}", file=sys.stderr) # For very early errors
            raise ValueError(err_msg) # This will be caught by main_bot.py's initialization

    def _load_strategy(self, module_path: str, class_name: str, params: Dict[str, Any]) -> Optional[BaseStrategy]:
        logger.info(f"Attempting to load strategy: '{class_name}' from module '{module_path}' with params: {params}")
        try:
            # Ensure the module path is a string usable by import_module
            if not isinstance(module_path, str) or not module_path:
                logger.error(f"Invalid module_path: '{module_path}'. Must be a non-empty string.")
                return None
            if not isinstance(class_name, str) or not class_name:
                logger.error(f"Invalid class_name: '{class_name}'. Must be a non-empty string.")
                return None

            strategy_module = importlib.import_module(module_path)
            StrategyClass: Type[BaseStrategy] = getattr(strategy_module, class_name)
            
            if not issubclass(StrategyClass, BaseStrategy): # Check inheritance
                logger.error(f"Class '{class_name}' in '{module_path}' is NOT a subclass of BaseStrategy.")
                return None

            logger.info(f"Successfully loaded strategy class: {class_name} from module {module_path}")
            return StrategyClass(params) # Instantiate the strategy with its parameters
        except ImportError:
            logger.error(f"ImportError: Module '{module_path}' for '{class_name}' not found or contains errors.", exc_info=True)
        except AttributeError: # If class_name is not in the loaded module
            logger.error(f"AttributeError: Class '{class_name}' not found in module '{module_path}'.", exc_info=True)
        except Exception as e: # Catch any other exceptions during loading/instantiation
            logger.error(f"General error loading strategy '{class_name}' from '{module_path}': {e}", exc_info=True)
        return None

    def generate_trade_signal(self, df_with_ta: pd.DataFrame, current_market_price: Optional[float]) -> Optional[Dict[str, Any]]:
        if self.strategy is None: # Should have been caught by __init__
            logger.error(
                f"No strategy ('{self.strategy_class_name}' from '{self.strategy_module_path}') loaded. "
                "Cannot generate signal."
            )
            return None
        
        if df_with_ta is None or df_with_ta.empty:
            logger.warning("DataFrame with TA is empty or None for signal generation. Skipping.")
            return None

        logger.info(
            f"Generating signal with strategy '{self.strategy_class_name}' using {len(df_with_ta)} data points."
        )
        signal_data = self.strategy.generate_signal(df_with_ta) # Call strategy's method

        if signal_data and isinstance(signal_data, dict) and "signal" in signal_data:
            signal_type = signal_data.get("signal")
            entry_price_from_strategy = signal_data.get("entry_price")

            # Determine actual entry price
            entry_price: Optional[float] = None # Initialize
            if current_market_price is not None and isinstance(current_market_price, (int, float)) and current_market_price > 0:
                entry_price = float(current_market_price)
                logger.info(f"Using live market price for entry: {entry_price:.4f}")
            elif entry_price_from_strategy is not None and isinstance(entry_price_from_strategy, (int, float)) and entry_price_from_strategy > 0 :
                entry_price = float(entry_price_from_strategy)
                logger.info(f"Using strategy-defined entry (e.g., last kline close): {entry_price:.4f}")
            else:
                logger.error(
                    "Invalid or no entry price determined (from market or strategy). "
                    "Cannot calculate SL/TP or form full signal."
                )
                return None 

            # Fetch risk parameters
            sl_pct = self.risk_params.get('stop_loss_pct', 0.0)
            tp_pct = self.risk_params.get('take_profit_pct', 0.0)
            price_precision = int(self.risk_params.get('price_precision', 4)) # Ensure int

            # Validate and cast SL/TP percentages
            try:
                sl_pct = float(sl_pct)
                tp_pct = float(tp_pct)
            except (ValueError, TypeError):
                logger.error(f"Invalid SL/TP percentages in config: sl_pct='{sl_pct}', tp_pct='{tp_pct}'. Setting to 0.0.")
                sl_pct, tp_pct = 0.0, 0.0
            
            # Calculate SL/TP levels using the strategy's method
            sl_tp_levels = self.strategy.calculate_sl_tp(
                entry_price=entry_price, # Already ensured float
                signal_type=str(signal_type), 
                sl_pct=sl_pct, 
                tp_pct=tp_pct,
                price_precision=price_precision
            )

            full_signal = {
                "type": str(signal_type),
                "entry_price": round(entry_price, price_precision), 
                "stop_loss": sl_tp_levels.get("stop_loss"), # Use .get for safety
                "take_profit": sl_tp_levels.get("take_profit"),
                "reason": str(signal_data.get("reason", "N/A"))
            }
            logger.info(f"FINAL SIGNAL GENERATED by '{self.strategy_class_name}': {full_signal}")
            return full_signal
        
        logger.debug(f"No signal generated by strategy '{self.strategy_class_name}' for this data cycle.")
        return None