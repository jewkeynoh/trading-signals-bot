# Trading Signals Bot for Bybit

This Python-based bot is designed to generate trading signals for assets on the Bybit exchange based on configurable trading strategies. It fetches market data, calculates technical indicators, applies a chosen strategy, and sends signal notifications (including entry price, stop loss, and take profit) via Telegram.

## Features

* **Bybit Integration:** Fetches K-line (candlestick) data and current market prices from Bybit (supports Testnet and Mainnet).
* **Configurable Strategies:**
    * Easily define and switch between different trading strategies using `config.yaml`.
    * Parameters for each strategy are also configurable.
    * Includes an example `MA_RSI_Strategy` (Moving Average Crossover with RSI confirmation).
    * Base class provided for creating custom strategies.
* **Technical Indicator Calculation:** Uses `pandas-ta` to calculate necessary technical indicators.
* **Telegram Notifications:**
    * Sends detailed signal alerts (Buy Long/Sell Short, entry, SL, TP, reason).
    * Sends a time-based startup greeting message.
    * Sends a shutdown message when the bot is stopped gracefully.
* **Risk Management:** Calculates Stop Loss (SL) and Take Profit (TP) levels based on configurable percentages.
* **Scheduling:** Runs signal checks at configurable intervals using `schedule`.
* **Configuration Management:**
    * Centralized configuration via `config.yaml`.
    * Secure API key and token management using a `.env` file.
    * Configuration validation using Pydantic.
* **Logging:** Comprehensive logging to both console and a log file.
* **Robustness:** Includes basic API call retries and error handling.

## Project Structure

trading-signals-alert/│├── .env                     # For API keys and secrets (create this yourself)├── config.yaml              # Main configuration file for the bot├── main_bot.py              # Main application script to run the bot├── requirements.txt         # Python dependencies│├── bybit_client.py          # Handles communication with Bybit API├── indicator_calculator.py  # Calculates technical indicators├── signal_generator.py      # Loads strategies and generates trade signals├── telegram_notifier.py     # Handles sending messages to Telegram│├── strategies/              # Directory for trading strategy implementations│   ├── init.py│   ├── base_strategy.py     # Abstract base class for strategies│   └── example_strategy_ma_rsi.py # Example strategy│└── logs/                    # Directory for log files (created automatically)└── signal_bot.log
## Prerequisites

* Python 3.9 or higher
* `pip` (Python package installer)
* A Bybit account (for API keys, Testnet recommended for initial setup)
* A Telegram Bot and its API Token (get this from BotFather on Telegram)
* Your Telegram Chat ID (or Group ID)

## Setup and Installation

1.  **Clone the Repository (if applicable):**
    If this project is in a Git repository, clone it:
    ```bash
    git clone <repository_url>
    cd trading-signals-alert
    ```
    If you just have the files, ensure they are in a directory named `trading-signals-alert`.

2.  **Create and Activate a Virtual Environment:**
    It's highly recommended to use a virtual environment.
    ```bash
    python -m venv venv
    ```
    Activate it:
    * Windows: `venv\Scripts\activate`
    * macOS/Linux: `source venv/bin/activate`

3.  **Install Dependencies:**
    Ensure your `pip` is up-to-date:
    ```bash
    python -m pip install --upgrade pip
    ```
    Install the required packages:
    ```bash
    pip install -r requirements.txt --no-cache-dir
    ```
    *(The `requirements.txt` should include `tzdata` as per our previous discussions).*

4.  **Create and Configure `.env` File:**
    Create a file named `.env` in the project root (`trading-signals-alert/`) and add your API keys and tokens:
    ```env
    BYBIT_API_KEY="YOUR_BYBIT_API_KEY_HERE"
    BYBIT_API_SECRET="YOUR_BYBIT_API_SECRET_HERE"
    TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN_HERE"
    ```
    **Note:** Replace the placeholder values with your actual credentials. For Bybit, start with Testnet API keys.

5.  **Configure `config.yaml`:**
    Open `config.yaml` and review/update the settings:
    * **`bybit` section:**
        * `testnet`: Set to `true` for Testnet, `false` for Mainnet. **ALWAYS START WITH TESTNET!**
        * `symbol`, `interval`, `limit`: Define the default trading pair and data fetching parameters.
    * **`telegram` section:**
        * `chat_id`: Replace `"YOUR_TELEGRAM_CHAT_ID_HERE"` with your actual Telegram User ID or Group ID.
            * To get your User ID, message `@userinfobot` on Telegram.
            * For Group ID, add `@RawDataBot` to your group, send any message, and find the `chat.id` (usually a negative number).
    * Review other sections like `strategy_profiles`, `active_strategy_profile_name`, `risk_management`, `schedule_interval_minutes`, and `logging` as needed (see "Configuration Details" below).

## Running the Bot

Once everything is set up, you can run the bot from the project root directory (where `main_bot.py` is located):

```bash
python main_bot.py
The bot will start, send a greeting message to your configured Telegram chat, and then begin checking for signals based on the schedule. Press Ctrl+C to stop the bot gracefully (it will attempt to send a shutdown message).Configuration Details (config.yaml)The config.yaml file is central to customizing the bot's behavior.app:bot_name: The name displayed in startup/shutdown messages.bybit:testnet: true or false.api_key_env, api_secret_env: Names of the environment variables for Bybit credentials.symbol, interval, limit: Default data fetching parameters.api_retries, api_retry_delay_seconds: Settings for retrying failed API calls.strategy_profiles:This section allows you to define multiple strategy configurations (profiles).Each profile has a unique name (e.g., ma_rsi_default).Inside each profile:module_path: The Python import path to the strategy file (e.g., strategies.example_strategy_ma_rsi).class_name: The exact class name of the strategy (e.g., MA_RSI_Strategy).parameters: A dictionary of parameters specific to that strategy (e.g., short_ma_period, rsi_oversold).active_strategy_profile_name:Set this to the name of one of the profiles defined under strategy_profiles to select which strategy the bot will use.risk_management:stop_loss_pct: Stop loss percentage from the entry price (e.g., 0.01 for 1%).take_profit_pct: Take profit percentage.price_precision: Number of decimal places for SL/TP prices.telegram:bot_token_env: Name of the environment variable for the Telegram bot token.chat_id: Your Telegram User ID or Group ID where messages will be sent.schedule_interval_minutes:How often (in minutes) the bot checks for signals. Set to 0 to run only once.logging:log_file: Path to the log file (e.g., logs/signal_bot.log).log_level: Logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL).Creating Custom StrategiesInherit from BaseStrategy:Your new strategy class should be created in a new Python file inside the strategies/ directory (e.g., strategies/my_custom_strategy.py).It must inherit from BaseStrategy (from strategies.base_strategy).You must implement the generate_signal(self, df_with_ta: pd.DataFrame) -> Optional[Dict[str, Any]] method.This method receives a Pandas DataFrame containing K-line data with technical indicators already calculated (based on parameters your strategy might need, which you'd typically define in config.yaml and pass to indicator_calculator.py).It should return a dictionary with signal details (e.g., {"signal": "BUY_LONG", "entry_price": 12345.67, "reason": "Condition X met"}) or None if no signal is generated.The entry_price returned by the strategy is typically the close of the last fully closed candle that confirmed the signal. The bot can also use the current market price if available.Example Strategy File (strategies/my_custom_strategy.py):# strategies/my_custom_strategy.py
import pandas as pd
from .base_strategy import BaseStrategy
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MyCustomStrategy(BaseStrategy):
    def __init__(self, params: Dict[str, Any]):
        super().__init__(params)
        # Initialize any strategy-specific parameters here
        self.my_param = self.params.get('my_custom_parameter', 10) # Example
        logger.info(f"MyCustomStrategy initialized with my_param: {self.my_param}")

    def generate_signal(self, df_with_ta: pd.DataFrame) -> Optional[Dict[str, Any]]:
        logger.debug(f"MyCustomStrategy generating signal with {len(df_with_ta)} data points.")
        # Implement your strategy logic here
        # Access TA columns from df_with_ta (e.g., df_with_ta['SMA_20'], df_with_ta['RSI_14'])
        # Access strategy parameters via self.params or self.my_param

        # Example: Placeholder logic
        last_row = df_with_ta.iloc[-1]
        # prev_row = df_with_ta.iloc[-2] # If you need previous candle data

        # if last_row['close'] > self.my_param: # Your condition
        #     return {
        #         "signal": "BUY_LONG", 
        #         "entry_price": float(last_row['close']), # Or current market price
        #         "reason": f"Close price {last_row['close']} > {self.my_param}"
        #     }
        return None # No signal
Define Indicator Needs in indicator_calculator.py:If your strategy needs specific indicators (e.g., EMA, MACD, Bollinger Bands) with certain parameters, you'll need to ensure indicator_calculator.py can compute them.The calculate_indicators function currently looks for parameters like short_ma_period, long_ma_period, rsi_period from the strategy's parameters in config.yaml. You would add logic for your new indicators there, driven by parameters you define for your strategy.Add Profile to config.yaml:In config.yaml, under strategy_profiles, add a new profile for your custom strategy:# config.yaml
strategy_profiles:
  # ... other profiles ...
  my_custom_strat_v1:
    module_path: "strategies.my_custom_strategy" # Python path to your file
    class_name: "MyCustomStrategy"              # Your strategy class name
    parameters:
      my_custom_parameter: 15 # Example parameter
      # Add other parameters your strategy needs (these will also be passed to indicator_calculator)
      # e.g., if you need EMA_50 for your strategy:
      # ema_period_1: 50 
      # You would then add logic in indicator_calculator.py to calculate EMA_50 if ema_period_1 is present.
Activate Your Strategy:In config.yaml, set active_strategy_profile_name: "my_custom_strat_v1".LoggingLogs are printed to the console.Logs are also saved to a file specified in config.yaml (default: logs/signal_bot.log).The log level can be adjusted in config.yaml (e.g., INFO, DEBUG). DEBUG is useful for troubleshooting.DisclaimerTrading cryptocurrencies involves significant risk of loss. This bot is provided for informational and educational purposes only and should not be considered financial advice. Any trading decisions you make are your own responsibility. Always do your own research (DYOR) and never trade with money you cannot afford to lose. Test thoroughly on Bybit's Testnet before considering any real-money trading.Future Enhancements (Potential To-Do)Support for multiple symbols simultaneously.More sophisticated error handling and recovery.Integration with a proper database for storing signals or trade history.Web interface for monitoring or configuration.Advanced