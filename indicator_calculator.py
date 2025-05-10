# indicator_calculator.py
import pandas as pd
import pandas_ta as ta
import logging
from typing import Dict, Any
import numpy as np # Import numpy as np

logger = logging.getLogger(__name__)

def calculate_indicators(df: pd.DataFrame, strategy_params: Dict[str, Any]) -> pd.DataFrame:
    """
    Calculates technical indicators based on the strategy's needs using pandas_ta.
    Ensures input DataFrame has necessary columns and numeric types.
    """
    if df is None or df.empty:
        logger.warning("Input DataFrame is empty or None. Cannot calculate indicators.")
        return pd.DataFrame() # Return empty DataFrame

    logger.info(f"Calculating technical indicators. Initial df length: {len(df)}. Params: {strategy_params}")
    df_with_ta = df.copy()

    # Ensure essential columns exist and are numeric
    essential_cols = ['open', 'high', 'low', 'close'] # volume is often used too
    for col in essential_cols:
        if col not in df_with_ta.columns:
            logger.error(f"Essential column '{col}' missing in DataFrame. Cannot proceed with TA calculation.")
            return pd.DataFrame() # Return empty if critical columns are missing
        
        # Attempt to convert to numeric, coercing errors to np.nan (lowercase)
        if not pd.api.types.is_numeric_dtype(df_with_ta[col]):
            logger.debug(f"Column '{col}' is not numeric ({df_with_ta[col].dtype}), attempting conversion.")
            df_with_ta[col] = pd.to_numeric(df_with_ta[col], errors='coerce')
            if df_with_ta[col].isnull().all(): # If all values became NaN after coercion
                 logger.error(f"Column '{col}' became all NaNs after numeric conversion. Cannot proceed.")
                 return pd.DataFrame()
    
    # Drop rows if essential columns have NaNs after conversion (important for TA library)
    df_with_ta.dropna(subset=essential_cols, inplace=True)
    if df_with_ta.empty:
        logger.warning("DataFrame became empty after ensuring essential columns are numeric and dropping NaNs.")
        return pd.DataFrame()

    try:
        # --- Moving Averages ---
        short_ma_period = strategy_params.get('short_ma_period')
        long_ma_period = strategy_params.get('long_ma_period')
        
        if short_ma_period is not None and long_ma_period is not None: # Check for None explicitly
            try:
                short_ma_period = int(short_ma_period)
                long_ma_period = int(long_ma_period)
                if short_ma_period > 0 and long_ma_period > 0:
                    logger.debug(f"Calculating SMA_{short_ma_period} and SMA_{long_ma_period}")
                    # Ensure 'close' is float for pandas_ta if it's object type from conversion
                    df_with_ta.ta.sma(close=df_with_ta['close'].astype(float), length=short_ma_period, append=True, col_names=(f"SMA_{short_ma_period}",))
                    df_with_ta.ta.sma(close=df_with_ta['close'].astype(float), length=long_ma_period, append=True, col_names=(f"SMA_{long_ma_period}",))
                else:
                    logger.warning(f"Invalid MA periods (short: {short_ma_period}, long: {long_ma_period}). Skipping SMAs.")
            except ValueError:
                logger.warning(f"MA periods (short: {short_ma_period}, long: {long_ma_period}) are not valid integers. Skipping SMAs.")
        else:
            logger.debug("SMA periods (short_ma_period or long_ma_period) not configured. Skipping SMAs.")

        # --- RSI ---
        rsi_period = strategy_params.get('rsi_period')
        if rsi_period is not None: # Check for None explicitly
            try:
                rsi_period = int(rsi_period)
                if rsi_period > 0:
                    logger.debug(f"Calculating RSI_{rsi_period}")
                    df_with_ta.ta.rsi(close=df_with_ta['close'].astype(float), length=rsi_period, append=True, col_names=(f"RSI_{rsi_period}",))
                else:
                    logger.warning(f"Invalid RSI period ({rsi_period}). Skipping RSI.")
            except ValueError:
                 logger.warning(f"RSI period ({rsi_period}) is not a valid integer. Skipping RSI.")
        else:
            logger.debug("RSI period not configured. Skipping RSI.")
        
        # --- Remove rows with NaN values created by TA calculations (pandas_ta often creates NaNs for initial periods) ---
        initial_len = len(df_with_ta)
        df_with_ta.dropna(inplace=True) 
        dropped_rows = initial_len - len(df_with_ta)
        if dropped_rows > 0:
            logger.info(f"Dropped {dropped_rows} rows with NaNs after TA calculation.")
        
        if df_with_ta.empty:
             logger.warning("DataFrame became empty after TA calculation and NaN drop. No data for strategy.")
             return pd.DataFrame() # Return empty DataFrame

        logger.info(f"Technical indicators calculation complete. Final df length: {len(df_with_ta)}")
    except AttributeError as e_attr: # Catch errors if df_with_ta.ta is not available or specific TA fails
        logger.error(f"AttributeError during TA calculation (possibly pandas_ta issue or bad column): {e_attr}", exc_info=True)
        return pd.DataFrame() # Return empty on such errors
    except Exception as e:
        logger.error(f"General error calculating technical indicators: {e}", exc_info=True)
        return pd.DataFrame() # Return empty on other errors
    
    return df_with_ta

# Example Usage for standalone testing (ensure np.nan is used if needed)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Sample data demonstrating use of np.nan for missing values if you were constructing it manually
    sample_data_raw = {
        'open': [10.0, 10.1, np.nan, 9.9, 10.2, 10.3, 10.5, 10.4, 10.6, 10.7] * 5,
        'high': [10.3, 10.4, 10.2, 10.1, 10.5, 10.6, 10.7, 10.6, 10.8, 10.9] * 5,
        'low':  [9.8, 9.9, 9.8, 9.7, 10.0, 10.1, 10.2, 10.3, 10.4, 10.5] * 5,
        'close':[10.1, 10.0, 9.9, 10.2, 10.3, 10.5, 10.4, 10.6, 10.7, 10.8] * 5,
        'volume':[100, 110, 105, 120, 115, 130, 125, 140, 135, 150] * 5
    }
    sample_df_for_ta = pd.DataFrame(sample_data_raw)
    # Note: The calculate_indicators function will drop rows with NaNs in essential columns before TA.

    test_strategy_params_for_ta = {
        'short_ma_period': 3, 
        'long_ma_period': 5,  
        'rsi_period': 4       
    }

    logger.info("--- Running Standalone Test for indicator_calculator.py ---")
    df_original_copy = sample_df_for_ta.copy() # Keep a copy of original for inspection
    df_with_indicators_result = calculate_indicators(df_original_copy, test_strategy_params_for_ta)
    
    print("\nOriginal Sample DataFrame (first 10 rows with potential NaNs):")
    print(sample_df_for_ta.head(10).to_string())
    print("\nDataFrame with Technical Indicators (result from calculate_indicators):")
    if df_with_indicators_result.empty:
        print("Resulting DataFrame is empty.")
    else:
        print(df_with_indicators_result.to_string())