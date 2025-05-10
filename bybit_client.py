# bybit_client.py
import logging
from pybit.unified_trading import HTTP
import pandas as pd
from typing import Optional, Dict, Any # Removed List as it wasn't used here
import time
import os
from dotenv import load_dotenv
import requests # For requests.exceptions

logger = logging.getLogger(__name__)

class BybitClient:
    def __init__(self, api_key: Optional[str], api_secret: Optional[str], testnet: bool = True,
                 api_retries: int = 3, api_retry_delay: int = 5):
        self.client: Optional[HTTP] = None
        self.testnet = testnet
        self.api_retries = api_retries
        self.api_retry_delay = api_retry_delay # in seconds
        
        if not api_key or not api_secret:
            logger.warning("API Key or Secret not provided. Client initialized in unauthenticated mode (public data only).")
            try:
                self.client = HTTP(testnet=self.testnet)
                logger.info(f"BybitClient initialized (UNAUTHENTICATED). Testnet: {self.testnet}")
            except Exception as e:
                logger.critical(f"Failed to initialize Bybit HTTP client (unauthenticated): {e}", exc_info=True)
                self.client = None # Ensure client is None on failure
        else:
            try:
                self.client = HTTP(
                    testnet=self.testnet,
                    api_key=api_key,
                    api_secret=api_secret,
                )
                # Optionally, verify connection with a simple call like get_server_time
                # server_time = self.client.get_server_time()
                # if server_time and server_time.get('retCode') == 0:
                #    logger.info(f"BybitClient initialized and server time checked. Testnet: {self.testnet}. API Key: {str(api_key)[:5]}...")
                # else:
                #    logger.warning(f"BybitClient initialized but couldn't verify server time. Resp: {server_time}")
                logger.info(f"BybitClient initialized (AUTHENTICATED). Testnet: {self.testnet}. API Key: {str(api_key)[:5]}...")
            except Exception as e:
                logger.critical(f"Failed to initialize Bybit HTTP client (authenticated): {e}", exc_info=True)
                self.client = None # Ensure client is None on failure


    def _make_api_call(self, api_method_callable, *args, **kwargs) -> Optional[Dict[str, Any]]:
        """Wrapper for API calls with retry logic."""
        if not self.client: # Should not happen if __init__ is guarded
            logger.error("Bybit internal client not available for API call.")
            return None

        for attempt in range(self.api_retries + 1): # +1 because range is exclusive at end
            try:
                response = api_method_callable(*args, **kwargs)
                
                if response and response.get('retCode') == 0:
                    logger.debug(f"API call successful on attempt {attempt + 1}. Method: {api_method_callable.__name__}")
                    return response
                elif response: 
                    logger.warning(
                        f"API call failed on attempt {attempt + 1}/{self.api_retries + 1}. "
                        f"Method: {api_method_callable.__name__}, "
                        f"RetCode: {response.get('retCode')}, RetMsg: {response.get('retMsg')}. "
                        # f"Args: {args}, Kwargs: {kwargs}" # Can be too verbose
                    )
                else: 
                    logger.warning(
                        f"API call returned no response object on attempt {attempt + 1}/{self.api_retries + 1}. "
                        f"Method: {api_method_callable.__name__}."
                    )
            # Catch specific exceptions that pybit or underlying requests might raise
            except requests.exceptions.Timeout: 
                logger.warning(
                    f"API call timed out on attempt {attempt + 1}/{self.api_retries + 1}. "
                    f"Method: {api_method_callable.__name__}."
                )
            except requests.exceptions.ConnectionError:
                 logger.warning(
                    f"API call connection error on attempt {attempt + 1}/{self.api_retries + 1}. "
                     f"Method: {api_method_callable.__name__}."
                )
            except Exception as e: 
                logger.error(
                    f"Unexpected exception during API call attempt {attempt + 1}/{self.api_retries + 1}: {e}. "
                    f"Method: {api_method_callable.__name__}.", exc_info=True # exc_info for traceback
                )
            
            if attempt < self.api_retries: # If not the last attempt
                logger.info(f"Retrying API call in {self.api_retry_delay} seconds...")
                time.sleep(self.api_retry_delay)
            else:
                logger.error(f"API call failed after {self.api_retries + 1} attempts. Method: {api_method_callable.__name__}.")
        return None


    def get_kline_data(self, symbol: str, interval: str, limit: int = 200) -> Optional[pd.DataFrame]:
        if not self.client:
            logger.error("Bybit client not initialized properly. Cannot fetch kline data.")
            return None
            
        logger.info(f"Fetching {limit} klines for {symbol}, interval {interval}")
        
        response = self._make_api_call(
            self.client.get_kline, 
            category="linear", 
            symbol=symbol,
            interval=interval,
            limit=limit
        )

        if response: 
            result_data = response.get('result', {})
            kline_list = result_data.get('list')
            
            if not kline_list: # Check if list is None or empty
                logger.warning(f"No kline data in 'list' for {symbol}, interval {interval}. Full result part: {result_data.get('category', 'N/A')}")
                return pd.DataFrame() 

            # Ensure kline_list is actually a list before creating DataFrame
            if not isinstance(kline_list, list):
                logger.error(f"Kline data for {symbol} is not a list: {type(kline_list)}. Response: {result_data}")
                return pd.DataFrame()

            df = pd.DataFrame(kline_list, columns=[
                "timestamp", "open", "high", "low", "close", "volume", "turnover"
            ])
            if df.empty: # If kline_list was empty, DataFrame will be empty
                logger.info(f"Received empty kline list for {symbol}, interval {interval}.")
                return df # Return empty DataFrame

            df = df.iloc[::-1].reset_index(drop=True) # Reverse order: oldest first

            # Convert to numeric, coercing errors. Use np.nan (lowercase) for missing.
            for col in ["timestamp", "open", "high", "low", "close", "volume", "turnover"]:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Drop rows where essential price data or timestamp is NaN
            df.dropna(subset=["timestamp", "open", "high", "low", "close"], inplace=True)
            if df.empty:
                logger.warning(f"DataFrame for {symbol} empty after numeric conversion/NaN drop for essential columns.")
                return df

            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
            df.dropna(subset=['datetime'], inplace=True) # Drop rows if datetime conversion failed
            
            if df.empty:
                logger.warning(f"DataFrame for {symbol} empty after datetime conversion/NaN drop.")
                return df

            logger.info(f"Successfully fetched and processed {len(df)} klines for {symbol}.")
            return df
        else:
            logger.error(f"Failed to fetch klines for {symbol} after retries.")
            return None

    def get_current_price(self, symbol: str) -> Optional[float]:
        if not self.client:
            logger.error("Bybit client not initialized properly. Cannot fetch current price.")
            return None

        logger.info(f"Fetching current price for {symbol}")
        response = self._make_api_call(
            self.client.get_tickers, 
            category="linear", 
            symbol=symbol
        )

        if response:
            tickers_list = response.get('result', {}).get('list', [])
            if tickers_list and isinstance(tickers_list, list) and len(tickers_list) > 0:
                ticker_data = tickers_list[0] # Assuming first item is the relevant one for the symbol
                if 'lastPrice' in ticker_data:
                    try:
                        last_price = float(ticker_data['lastPrice'])
                        logger.info(f"Current price for {symbol}: {last_price}")
                        return last_price
                    except (ValueError, TypeError):
                        logger.error(f"Could not convert lastPrice '{ticker_data['lastPrice']}' to float for {symbol}.")
                        return None
                else:
                    logger.warning(f"'lastPrice' key not found in ticker data for {symbol}. Data: {ticker_data}")
                    return None
            else:
                logger.warning(f"No ticker data in 'list' for {symbol} or list is empty/invalid. Response: {response.get('result', {})}")
                return None
        else:
            logger.error(f"Failed to fetch current price for {symbol} after retries.")
            return None

# Example Usage (for testing this module directly)
if __name__ == '__main__':
    # Basic logging for standalone test
    logging.basicConfig(level=logging.DEBUG, 
                        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s',
                        handlers=[logging.StreamHandler()]) # Ensure handler is set for standalone test
    
    project_root = Path(__file__).resolve().parent 
    dotenv_path = project_root / ".env" 
    
    if dotenv_path.is_file():
        logger.info(f"Standalone Test: Loading .env from {dotenv_path}")
        load_dotenv(dotenv_path=dotenv_path)
    else:
        logger.warning(f"Standalone Test: .env file not found at {dotenv_path}. API keys must be set in environment.")

    API_KEY = os.getenv("BYBIT_API_KEY")
    API_SECRET = os.getenv("BYBIT_API_SECRET")

    # Test with unauthenticated client if keys are missing
    if not API_KEY or not API_SECRET:
        logger.warning("API Key/Secret not found. Testing BybitClient in unauthenticated mode.")
        client = BybitClient(api_key=None, api_secret=None, testnet=True)
    else:
        client = BybitClient(api_key=API_KEY, api_secret=API_SECRET, testnet=True)
    
    if client.client: 
        kline_df = client.get_kline_data(symbol="BTCUSDT", interval="15", limit=5)
        if kline_df is not None and not kline_df.empty:
            print("\nFetched K-line Data (BTCUSDT, 15min, last 5 candles):")
            print(kline_df.to_string())
        elif kline_df is not None and kline_df.empty:
            print("\nFetched K-line Data for BTCUSDT: DataFrame is empty (no errors during fetch).")
        else:
            print("\nFailed to fetch K-line Data for BTCUSDT or result was None.")


        current_price = client.get_current_price(symbol="BTCUSDT")
        if current_price is not None:
            print(f"\nCurrent BTCUSDT Price: {current_price}")
        else:
            print(f"\nFailed to fetch current BTCUSDT Price.")
            
        # Test a non-existent symbol to check error handling
        logger.info("\n--- Testing with a non-existent symbol (XYZABC) ---")
        invalid_kline_df = client.get_kline_data(symbol="XYZABC", interval="15", limit=5)
        if invalid_kline_df is None:
            print("Correctly failed to fetch klines for XYZABC (returned None).")
        elif invalid_kline_df.empty:
             print("Correctly returned an empty DataFrame for XYZABC.")
        else:
            print(f"Unexpectedly got data for XYZABC: {invalid_kline_df}")
            
        invalid_price = client.get_current_price(symbol="XYZABC")
        if invalid_price is None:
            print("Correctly failed to fetch price for XYZABC (returned None).")
        else:
            print(f"Unexpectedly got price for XYZABC: {invalid_price}")

    else:
        logger.error("Standalone Test: BybitClient internal HTTP client is None. Initialization failed.")