# main_bot.py
import logging
import yaml
from pathlib import Path
import os
import sys
import schedule
import time
from datetime import datetime
from zoneinfo import ZoneInfo # For timezone (Python 3.9+)
from dotenv import load_dotenv
from typing import Optional, Dict, Any, List, Union

# --- Pydantic Models for Configuration Validation ---
from pydantic import (
    BaseModel, Field, FilePath, DirectoryPath,
    field_validator, ValidationInfo # For Pydantic V2 style validators
)

# --- Project Root Definition ---
# Define PROJECT_ROOT_DIR early as Pydantic models might need it for path resolution if using FilePath/DirectoryPath
PROJECT_ROOT_DIR = Path(__file__).resolve().parent

# --- Pydantic Models Definitions ---
class AppConfig(BaseModel):
    bot_name: str = Field("My Trading Signal Bot", min_length=1)

class BybitAPIConfig(BaseModel):
    testnet: bool = True
    api_key_env: str = Field("BYBIT_API_KEY", min_length=1)
    api_secret_env: str = Field("BYBIT_API_SECRET", min_length=1)
    symbol: str = Field("BTCUSDT", pattern=r"^[A-Z0-9]+USDT$")
    interval: str = Field("15", pattern=r"^[1-9][0-9]*[mhdMD]?$|^[1-9][wW]$")
    limit: int = Field(200, gt=0, le=1000)
    api_retries: int = Field(3, ge=0)
    api_retry_delay_seconds: int = Field(5, ge=0)

class StrategyParams(BaseModel):
    class Config:
        extra = 'allow' # Allows any parameters not explicitly defined

class StrategyProfileConfig(BaseModel):
    module_path: str = Field(..., min_length=1)
    class_name: str = Field(..., min_length=1)
    parameters: StrategyParams = StrategyParams()

class RiskManagementConfig(BaseModel):
    stop_loss_pct: float = Field(0.0, ge=0.0)
    take_profit_pct: float = Field(0.0, ge=0.0)
    price_precision: int = Field(4, ge=0, le=8)

class TelegramConfig(BaseModel):
    bot_token_env: str = Field("TELEGRAM_BOT_TOKEN", min_length=1)
    chat_id: str = Field(..., min_length=1)

class LoggingConfig(BaseModel):
    log_file: Union[FilePath, str] = "logs/signal_bot.log" # str for flexibility
    log_level: str = "INFO"

    @field_validator('log_level')
    @classmethod
    def log_level_must_be_valid(cls, value: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if value.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return value.upper()

class MainConfig(BaseModel):
    app: AppConfig = AppConfig()
    bybit: BybitAPIConfig = BybitAPIConfig()
    strategy_profiles: Dict[str, StrategyProfileConfig]
    active_strategy_profile_name: str
    risk_management: RiskManagementConfig = RiskManagementConfig()
    telegram: TelegramConfig
    schedule_interval_minutes: int = Field(15, ge=0)
    logging: LoggingConfig = LoggingConfig()

    @field_validator('active_strategy_profile_name')
    @classmethod
    def active_profile_must_exist(cls, value: str, info: ValidationInfo) -> str:
        if info.data and 'strategy_profiles' in info.data:
            if value not in info.data['strategy_profiles']:
                available_profiles = list(info.data['strategy_profiles'].keys())
                raise ValueError(
                    f"active_strategy_profile_name '{value}' not found in strategy_profiles. "
                    f"Available profiles: {available_profiles}"
                )
        return value

    @field_validator('logging')
    @classmethod
    def ensure_log_dir_exists(cls, v_logging_config: LoggingConfig) -> LoggingConfig:
        log_path_str = str(v_logging_config.log_file)
        # Resolve relative paths based on PROJECT_ROOT_DIR
        if not Path(log_path_str).is_absolute():
            log_file_resolved = PROJECT_ROOT_DIR / log_path_str
        else:
            log_file_resolved = Path(log_path_str)
        try:
            log_file_resolved.parent.mkdir(parents=True, exist_ok=True)
            # If v_logging_config.log_file was a relative string, update it to the resolved path
            # This ensures FilePath in basicConfig gets an absolute or correctly resolved path.
            # However, Pydantic's FilePath should ideally handle this if configured correctly.
            # For simplicity, we ensure the directory exists.
            # If log_file is FilePath, Pydantic might do more. If str, this is good.
            v_logging_config.log_file = str(log_file_resolved) # Store the resolved path
        except OSError as e:
            print(f"WARNING: Could not create log directory {log_file_resolved.parent}: {e}", file=sys.stderr)
        return v_logging_config

# --- Attempt to set up sys.path for module imports ---
if str(PROJECT_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_DIR))

# Now, attempt to import project modules
try:
    from bybit_client import BybitClient
    from indicator_calculator import calculate_indicators
    from signal_generator import SignalGenerator
    from telegram_notifier import TelegramNotifier, _escape_mdv2_local # Import escaper
    from telegram.constants import ParseMode as TGParseMode # For TGParseMode.MARKDOWN_V2
except ImportError as e_import:
    print(f"[CRITICAL ERROR] Failed to import project modules: {e_import}\n"
          f"Ensure all .py files are in the directory: {PROJECT_ROOT_DIR} "
          f"or your PYTHONPATH is correctly set.", file=sys.stderr)
    sys.exit(1)

# --- Global variable for validated configuration ---
APP_SETTINGS: Optional[MainConfig] = None

def load_app_config(config_file_path: Union[str, Path] = 'config.yaml') -> Optional[MainConfig]:
    global APP_SETTINGS
    _temp_logger = logging.getLogger("ConfigLoaderInternal")
    if not _temp_logger.handlers: # Setup basic handler only if none exist
        _ch = logging.StreamHandler(sys.stdout)
        _ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - ConfigLoader - %(message)s'))
        _temp_logger.addHandler(_ch)
        _temp_logger.setLevel(logging.INFO)

    config_path_abs = PROJECT_ROOT_DIR / Path(config_file_path) # Resolve relative to project root
    _temp_logger.info(f"Loading application configuration from: {config_path_abs.resolve()}")

    if not config_path_abs.is_file():
        _temp_logger.critical(f"FATAL: Configuration file not found: {config_path_abs.resolve()}")
        sys.exit(1)
    try:
        with open(config_path_abs, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)
        if not raw_config:
            raise ValueError("Configuration file is empty or not valid YAML.")

        APP_SETTINGS = MainConfig(**raw_config)
        _temp_logger.info("Application configuration loaded and validated successfully using Pydantic.")
        return APP_SETTINGS
    except yaml.YAMLError as e:
        _temp_logger.critical(f"FATAL: Error parsing YAML from {config_path_abs.resolve()}: {e}", exc_info=True)
    except Exception as e:
        _temp_logger.critical(f"FATAL: Error loading/validating config from {config_path_abs.resolve()}: {e}", exc_info=True)
    sys.exit(1)

APP_SETTINGS = load_app_config('config.yaml') # Load relative to project root

# --- Setup Main Application Logging (using validated config) ---
log_cfg_validated = APP_SETTINGS.logging
# The log_file path should already be resolved (potentially to absolute) by the Pydantic validator
log_file_final_path = Path(log_cfg_validated.log_file)

logging.basicConfig(
    level=getattr(logging, log_cfg_validated.log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler(log_file_final_path, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)
logger = logging.getLogger(__name__) # Main application logger for this file

dotenv_path = PROJECT_ROOT_DIR / ".env"
if dotenv_path.is_file():
    logger.info(f"Loading .env from: {dotenv_path.resolve()}")
    load_dotenv(dotenv_path=dotenv_path)
else:
    logger.warning(f".env file not found at {dotenv_path.resolve()}. Secrets might be missing.")

# --- Components ---
bybit_handler: Optional[BybitClient] = None
telegram_sender: Optional[TelegramNotifier] = None
signal_gen: Optional[SignalGenerator] = None

# --- Helper function for time-based greeting ---
def get_time_based_greeting(bot_name_raw: str) -> str:
    """
    Generates a MarkdownV2 formatted greeting message in English.
    Dynamic parts like bot_name are escaped for MarkdownV2.
    """
    esc = _escape_mdv2_local # Imported from telegram_notifier

    try:
        ph_time = datetime.now(ZoneInfo("Asia/Manila"))
        hour = ph_time.hour
        time_str = ph_time.strftime("%I:%M %p %Z") # e.g., 03:58 PM PST

        safe_bot_name = esc(bot_name_raw)
        greeting_intro = f"Hello\\! Your bot, *{safe_bot_name}*, is "
        greeting_detail = ""
        emoji = ""

        if 5 <= hour < 12:
            emoji = "☀️"
            greeting_detail = "awake and ready to monitor market signals for you\\. Let's start the day with sharp focus\\!"
            full_greeting = f"{emoji} Good morning\\! {greeting_intro}{greeting_detail}"
        elif 12 <= hour < 18:
            emoji = "🌤️"
            greeting_detail = "reporting for duty\\. Continuing to watch for potential signals\\."
            full_greeting = f"{emoji} Good afternoon\\! {greeting_intro}{greeting_detail}"
        elif 18 <= hour < 24:
            emoji = "🌙"
            greeting_detail = "still on standby for trading signals\\. Hope the market is favorable tonight\\!"
            full_greeting = f"{emoji} Good evening\\! {greeting_intro}{greeting_detail}"
        else:
            emoji = "🦉"
            greeting_detail = "still up and observing signals for you through the night\\."
            full_greeting = f"{emoji} Good night\\! {greeting_intro}{greeting_detail}"

        safe_time_str = esc(time_str)
        return f"{full_greeting}\n\n_Bot started successfully at: {safe_time_str}_"
    except Exception as e:
        logger.error(f"Error generating English time-based greeting: {e}", exc_info=True)
        return f"Hello\\! {esc(bot_name_raw)} started successfully\\. (Could not determine time of day for custom greeting)"

def initialize_components() -> bool:
    global bybit_handler, telegram_sender, signal_gen, APP_SETTINGS
    logger.info("Initializing bot components...")
    bybit_cfg = APP_SETTINGS.bybit
    api_key = os.getenv(bybit_cfg.api_key_env)
    api_secret = os.getenv(bybit_cfg.api_secret_env)
    if not api_key or not api_secret:
        logger.warning(f"Bybit API Key/Secret (env: {bybit_cfg.api_key_env}/{bybit_cfg.api_secret_env}) NOT FOUND. Unauth mode.")
    try:
        bybit_handler = BybitClient(api_key, api_secret, bybit_cfg.testnet, bybit_cfg.api_retries, bybit_cfg.api_retry_delay_seconds)
        if (api_key and api_secret) and (not bybit_handler.client):
             logger.critical("BybitClient (authenticated) FAILED to initialize its internal HTTP client.")
             return False
        logger.info(f"BybitClient initialized ({'AUTH' if api_key and api_secret and bybit_handler.client else 'UNAUTH'} mode).")
    except Exception as e:
        logger.critical(f"Failed to create BybitClient instance: {e}", exc_info=True)
        return False

    tg_cfg = APP_SETTINGS.telegram
    bot_token = os.getenv(tg_cfg.bot_token_env)
    if not bot_token:
        logger.critical(f"TELEGRAM_BOT_TOKEN (env var: {tg_cfg.bot_token_env}) is NOT SET. Notifier cannot be initialized.")
        return False
    telegram_sender = TelegramNotifier(bot_token=bot_token, chat_id=tg_cfg.chat_id)
    if not telegram_sender.is_configured:
        logger.critical("TelegramNotifier FAILED to configure. Check token and chat_id.")
        return False

    active_profile_name = APP_SETTINGS.active_strategy_profile_name
    active_strategy_profile = APP_SETTINGS.strategy_profiles[active_profile_name]
    logger.info(f"Loading strategy profile: '{active_profile_name}' - Module: {active_strategy_profile.module_path}, Class: {active_strategy_profile.class_name}")
    try:
        strategy_params_dict = active_strategy_profile.parameters.model_dump(exclude_unset=True)
        risk_params_dict = APP_SETTINGS.risk_management.model_dump()
        signal_gen = SignalGenerator(
            strategy_module_path=active_strategy_profile.module_path,
            strategy_class_name=active_strategy_profile.class_name,
            strategy_params=strategy_params_dict,
            risk_params=risk_params_dict
        )
    except ValueError as e_strat_load:
        logger.critical(f"CRITICAL: Failed to initialize SignalGenerator (strategy loading): {e_strat_load}", exc_info=True)
        return False
    except Exception as e_gen_init:
        logger.critical(f"CRITICAL: Unexpected error initializing SignalGenerator: {e_gen_init}", exc_info=True)
        return False
    logger.info(f"All bot components initialized successfully. Active strategy: '{active_profile_name}'")
    return True

def check_for_signals_and_notify():
    logger.info("=== Starting New Signal Check Cycle ===")
    if not all([bybit_handler, signal_gen, telegram_sender]):
        logger.error("Critical components not initialized. Skipping cycle.")
        return

    bybit_cfg = APP_SETTINGS.bybit
    active_profile_name = APP_SETTINGS.active_strategy_profile_name
    active_strategy_config = APP_SETTINGS.strategy_profiles[active_profile_name]

    logger.info(f"Processing for strategy '{active_profile_name}': Symbol: {bybit_cfg.symbol}, Interval: {bybit_cfg.interval}, Limit: {bybit_cfg.limit}")

    kline_df = bybit_handler.get_kline_data(bybit_cfg.symbol, bybit_cfg.interval, bybit_cfg.limit)
    if kline_df is None or kline_df.empty:
        logger.error(f"No K-line data for {bybit_cfg.symbol}. Skipping signal generation."); return

    indicator_params_dict = active_strategy_config.parameters.model_dump(exclude_unset=True)
    df_with_ta = calculate_indicators(kline_df, indicator_params_dict)

    if df_with_ta is None or df_with_ta.empty:
        logger.error(f"DataFrame for {bybit_cfg.symbol} is empty/None after TA. Skipping signal generation."); return

    logger.debug(f"DataFrame with TA for {bybit_cfg.symbol} (last 3 rows):\n{df_with_ta.tail(3).to_string(index=True)}")

    current_price = bybit_handler.get_current_price(bybit_cfg.symbol)
    trade_signal = signal_gen.generate_trade_signal(df_with_ta, current_price)

    if trade_signal and telegram_sender and telegram_sender.is_configured:
        logger.info(f"Signal for {bybit_cfg.symbol} by '{active_profile_name}'. Sending to Telegram...")
        try:
            signal_type_str = str(trade_signal.get('type','N/A'))
            entry_price_val = float(trade_signal.get('entry_price', 0.0))
            stop_loss_val = float(trade_signal.get('stop_loss', 0.0))
            take_profit_val = float(trade_signal.get('take_profit', 0.0))
            reason_str = str(trade_signal.get('reason','N/A'))
            telegram_sender.send_signal_message_sync(
                symbol=bybit_cfg.symbol, timeframe=bybit_cfg.interval, signal_type=signal_type_str,
                entry_price=entry_price_val, stop_loss=stop_loss_val,
                take_profit=take_profit_val, reason=reason_str
            )
        except Exception as e_notify:
            logger.error(f"Error formatting or sending Telegram signal notification: {e_notify}", exc_info=True)
    elif trade_signal:
        logger.warning(f"Signal for {bybit_cfg.symbol} by '{active_profile_name}' but Telegram not configured/failed. Signal: {trade_signal}")
    else:
        logger.info(f"No new signal for {bybit_cfg.symbol} this cycle (Strategy: {active_profile_name}).")
    logger.info("=== Signal Check Cycle Finished ===")

def main():
    bot_display_name = APP_SETTINGS.app.bot_name
    logger.info(f"--- {bot_display_name} Application Instance Starting (PID: {os.getpid()}) ---")

    if not initialize_components():
        logger.critical("Failed to initialize critical components. Bot cannot run. Exiting.")
        if telegram_sender and telegram_sender.is_configured:
             safe_bot_name_for_error = _escape_mdv2_local(APP_SETTINGS.app.bot_name)
             error_msg_md = f"*CRITICAL FAILURE:*\nBot `'{safe_bot_name_for_error}'` failed to initialize key components and will exit\\. Please check the server logs immediately\\."
             telegram_sender.send_general_message_sync(error_msg_md, parse_mode=TGParseMode.MARKDOWN_V2)
        return

    if telegram_sender and telegram_sender.is_configured:
        greeting_md = get_time_based_greeting(bot_display_name)
        logger.info("Sending startup greeting to Telegram...")
        telegram_sender.send_general_message_sync(greeting_md, parse_mode=TGParseMode.MARKDOWN_V2)

    schedule_interval = APP_SETTINGS.schedule_interval_minutes

    def send_shutdown_message(reason: str = "shutdown"):
        if telegram_sender and telegram_sender.is_configured:
            logger.info(f"Preparing to send {reason} message...")
            safe_bot_name_shutdown = _escape_mdv2_local(APP_SETTINGS.app.bot_name)
            ph_time_shutdown = datetime.now(ZoneInfo("Asia/Manila"))
            time_str_shutdown = ph_time_shutdown.strftime("%I:%M %p %Z")
            safe_time_str_shutdown = _escape_mdv2_local(time_str_shutdown)
            
            status_emoji = "⚫️" # General stop
            status_text = "is shutting down"
            if "error" in reason.lower():
                status_emoji = "🆘"
                status_text = "encountered a critical error and is shutting down"

            shutdown_msg = (f"{status_emoji} Bot *{safe_bot_name_shutdown}* {status_text} NOW at _{safe_time_str_shutdown}_\\.\n"
                            f"It will no longer send signals until restarted\\.")
            if "error" in reason.lower():
                 shutdown_msg += f"\nReason: _{_escape_mdv2_local(reason)}_"

            telegram_sender.send_general_message_sync(shutdown_msg, parse_mode=TGParseMode.MARKDOWN_V2)
            logger.info(f"{reason.capitalize()} message sent to Telegram.")
        else:
            logger.info(f"Telegram sender not configured; cannot send {reason} message.")

    if schedule_interval > 0:
        logger.info(f"Scheduling signal checks to run every {schedule_interval} minutes.")
        try:
            check_for_signals_and_notify()
        except Exception as e_initial_run:
             logger.critical(f"Unhandled exception during initial signal check: {e_initial_run}", exc_info=True)
        schedule.every(schedule_interval).minutes.do(check_for_signals_and_notify)
        logger.info(f"Scheduler started. Bot is running. Press Ctrl+C to exit.")
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info(f"{bot_display_name} received Ctrl+C. Initiating graceful shutdown...")
            send_shutdown_message("User interruption (Ctrl+C)")
        except Exception as e_loop:
            logger.critical(f"Unhandled exception in main schedule loop: {e_loop}", exc_info=True)
            send_shutdown_message(f"Critical error in main loop: {str(e_loop)[:100]}") # Send part of error
    else:
        logger.info("schedule_interval_minutes is 0. Running signal check once.")
        try:
            check_for_signals_and_notify()
        except Exception as e_single_run:
            logger.critical(f"Unhandled exception during single signal check run: {e_single_run}", exc_info=True)
            send_shutdown_message(f"Error during single run: {str(e_single_run)[:100]}")
        else:
            send_shutdown_message("Single run completed") # Send after successful single run

    logger.info(f"--- {bot_display_name} Application Instance Stopped ---")

if __name__ == "__main__":
    if not APP_SETTINGS:
        print("[CRITICAL ERROR] APP_SETTINGS is None at __main__ guard. Config loading failed. Exiting.", file=sys.stderr)
        sys.exit(1)

    if not os.getenv(APP_SETTINGS.telegram.bot_token_env):
        logger.critical(f"CRITICAL STARTUP ERROR: Telegram Bot Token (env var: {APP_SETTINGS.telegram.bot_token_env}) is NOT SET. Exiting.")
        sys.exit(1)
    if not os.getenv(APP_SETTINGS.bybit.api_key_env) or not os.getenv(APP_SETTINGS.bybit.api_secret_env):
        logger.warning(f"STARTUP WARNING: Bybit API Key/Secret (env: {APP_SETTINGS.bybit.api_key_env}/{APP_SETTINGS.bybit.api_secret_env}) NOT SET. Unauth mode.")

    logger.info(f"--- {APP_SETTINGS.app.bot_name} Initializing via __main__ guard ---")
    main()