# telegram_notifier.py
import logging
import requests # For sync send
from telegram import Bot 
from telegram.constants import ParseMode as TGParseMode # Import TGParseMode
from telegram.error import TelegramError
import re 
from typing import Optional, Any, Dict # Added Dict

logger = logging.getLogger(__name__)

def _escape_mdv2_local(text: Any) -> str:
    """
    Safely escapes text for Telegram MarkdownV2.
    Should be used by the CALLER when constructing a Markdown string with dynamic content.
    """
    if not isinstance(text, str): 
        try:
            text = str(text)
        except Exception: 
            text = "UNSTRINGABLE_OBJECT"
            logger.warning(f"Could not convert object of type {type(text)} to string for MD escaping.")
    
    # Characters to escape for MarkdownV2, as per Telegram Bot API documentation
    # _ * [ ] ( ) ~ ` > # + - = | { } . !
    # Note: \ is the escape character itself and must be escaped too if you intend to send a literal \.
    # However, re.escape handles this if \ is part of escape_chars.
    # The official list: _ * [ ] ( ) ~ ` > # + - = | { } . !
    escape_chars = r'_*[]()~`>#+\-=|{}.!' 
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


class TelegramNotifier:
    def __init__(self, bot_token: Optional[str], chat_id: Optional[str]):
        self.bot: Optional[Bot] = None
        self.chat_id: Optional[str] = None
        self.is_configured: bool = False
        self.bot_token_for_sync: Optional[str] = bot_token

        if not bot_token or not chat_id:
            logger.critical("TelegramNotifier: Bot Token or Chat ID is MISSING. Notifications disabled.")
        else:
            try:
                self.bot = Bot(token=bot_token)
                self.chat_id = str(chat_id) # Ensure chat_id is string
                self.is_configured = True
                logger.info(f"TelegramNotifier initialized for chat ID: {self.chat_id}.")
            except Exception as e:
                logger.critical(f"TelegramNotifier: Failed to initialize Bot with token: {e}", exc_info=True)
                self.is_configured = False

    async def send_formatted_message_async(self, message_text: str, parse_mode: Optional[TGParseMode] = TGParseMode.MARKDOWN_V2):
        if not self.is_configured or not self.bot:
            logger.error("TelegramNotifier not configured or bot not initialized. Cannot send async message."); return
        
        logger.info(f"Attempting to send ASYNC message to chat {self.chat_id} (ParseMode: {parse_mode if parse_mode else 'Plain'}).")
        logger.debug(f"ASYNC Message content (first 200 chars): {message_text[:200]}...")
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=message_text, parse_mode=parse_mode)
            logger.info(f"ASYNC message successfully sent to Telegram chat ID {self.chat_id}.")
        except TelegramError as e:
            logger.error(f"Telegram API Error sending ASYNC (Mode: {parse_mode if parse_mode else 'Plain'}): {e.message}")
            logger.debug(f"Failed ASYNC message content for chat {self.chat_id}:\n{message_text}")
            if parse_mode: 
                plain_text_error_header = f"Error sending formatted message (Telegram rejected format). Original error: {e.message[:100]}\n---\n"
                try:
                    await self.bot.send_message(chat_id=self.chat_id, text=plain_text_error_header + message_text) 
                    logger.info(f"ASYNC plain text fallback (original content) sent for chat ID {self.chat_id}.")
                except Exception as e_plain:
                     logger.error(f"Failed to send ASYNC plain text fallback (original content): {e_plain}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error sending ASYNC message: {e}", exc_info=True)

    def _send_sync_request(self, payload: Dict[str, Any], context: str = "general") -> bool:
        """Helper to send synchronous requests to Telegram API."""
        if not self.is_configured or not self.bot_token_for_sync or not self.chat_id:
            logger.error(f"TelegramNotifier not configured for SYNC send ({context}).")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token_for_sync}/sendMessage"
        logger.info(f"Attempting SYNC {context} message to chat {self.chat_id}...")
        # Avoid logging potentially sensitive full message payload in production INFO level
        logger.debug(f"SYNC Message Payload (Chat ID: {payload.get('chat_id')}, ParseMode: {payload.get('parse_mode')}, Text Length: {len(payload.get('text',''))})")

        try:
            response = requests.post(url, data=payload, timeout=10)
            response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
            
            response_data = response.json() 
            if response_data.get("ok"):
                logger.info(f"SYNC {context} message successfully sent to Telegram.")
                return True
            else: # Should be caught by raise_for_status, but as a fallback
                logger.error(f"SYNC {context}: Failed to send. API Response (ok=false): {response.text}")
                return False
        except requests.exceptions.HTTPError as e_http:
            logger.error(f"SYNC {context}: HTTP error sending. Status: {e_http.response.status_code}, Response: {e_http.response.text}")
        except requests.exceptions.RequestException as e_req: 
             logger.error(f"SYNC {context}: Requests library exception sending: {e_req}", exc_info=True)
        except Exception as e: # Catch-all for other unexpected errors
            logger.error(f"SYNC {context}: General exception sending message: {e}", exc_info=True)
        return False

    def send_general_message_sync(self, message_text: str, parse_mode: Optional[TGParseMode] = None):
        """
        Sends a general message synchronously.
        The caller is responsible for pre-formatting the message_text if a parse_mode is used
        (e.g., constructing MarkdownV2 string, escaping dynamic parts if necessary).
        """
        payload: Dict[str, Any] = {'chat_id': self.chat_id, 'text': message_text}
        if parse_mode:
            payload['parse_mode'] = parse_mode
        
        if not self._send_sync_request(payload, context="general message"):
            # If a parse_mode was attempted and failed, try sending as plain text
            if parse_mode:
                logger.info("Attempting plain text fallback for general message after formatted send failed.")
                plain_payload = {'chat_id': self.chat_id, 'text': message_text} # Send original text as plain
                self._send_sync_request(plain_payload, context="general message fallback (plain)")

    def send_signal_message_sync(self, symbol: str, timeframe: str, signal_type: str, 
                                 entry_price: float, stop_loss: float, take_profit: float, 
                                 reason: str = "Strategy Condition Met"):
        """Sends a pre-formatted signal message using MarkdownV2."""
        # _escape_mdv2_local is used here because this method constructs the Markdown string itself.
        esc = _escape_mdv2_local 
        
        signal_emoji = "🟢" if "BUY" in signal_type.upper() else \
                       "🔴" if "SELL" in signal_type.upper() else \
                       "⚠️"
        try:
            # Format numbers, they will be inside `backticks` in Markdown, so no further escaping needed for the numbers themselves.
            entry_price_f = f"{float(entry_price):.4f}"
            stop_loss_f = f"{float(stop_loss):.4f}"
            take_profit_f = f"{float(take_profit):.4f}"
        except (ValueError, TypeError):
            logger.error(f"Invalid price format for signal message. Entry: {entry_price}, SL: {stop_loss}, TP: {take_profit}")
            entry_price_f, stop_loss_f, take_profit_f = "N/A", "N/A", "N/A"

        # Construct MarkdownV2 message. Dynamic parts (symbol, timeframe, etc.) are escaped.
        message_parts = [
            f"{signal_emoji} *Trading Signal: {esc(symbol)} \\({esc(str(timeframe))}m\\)* {signal_emoji}\n", # Escape m if it's literal, or use a variable
            f"*Signal Type:* `{esc(str(signal_type))}`",
            f"*Entry Price \\(approx\\.\\):* `{entry_price_f}`", 
            f"*Stop Loss:* `{stop_loss_f}`",
            f"*Take Profit:* `{take_profit_f}`",
            f"\n*Reason:* _{esc(str(reason))}_ \n", 
            f"_Disclaimer: For informational purposes only\\. Trade at your own risk\\._"
        ]
        message = "\n".join(message_parts)
        payload = {'chat_id': self.chat_id, 'text': message, 'parse_mode': TGParseMode.MARKDOWN_V2}
        
        if not self._send_sync_request(payload, context="signal message"):
            # Fallback for signal message if MarkdownV2 send fails
            self._send_plain_text_fallback_for_signal(symbol, timeframe, signal_type, entry_price, stop_loss, take_profit, reason, "Formatted signal send failed")

    def _send_plain_text_fallback_for_signal(self, symbol, timeframe, signal_type, entry_price, stop_loss, take_profit, reason, error_context):
        """Helper to send a plain text fallback specifically for signal messages."""
        if not self.is_configured or not self.bot_token_for_sync or not self.chat_id: return

        logger.info(f"Attempting SYNC plain text fallback for signal {symbol} due to: {error_context}")
        signal_emoji = "⚠️" # Plain text, so complex emojis might not render consistently across all platforms
        plain_text_message = (
            f"{signal_emoji} FALLBACK SIGNAL (Error with formatted send)\n"
            f"Symbol: {symbol} ({timeframe}m)\n"
            f"Type: {signal_type}\n"
            f"Entry: {entry_price:.4f}\n" 
            f"SL: {stop_loss:.4f}\n"
            f"TP: {take_profit:.4f}\n"
            f"Reason: {reason}\n"
            f"Original Send Error Context: {error_context}\n"
            f"Disclaimer: DYOR."
        )
        plain_payload = {'chat_id': self.chat_id, 'text': plain_text_message}
        self._send_sync_request(plain_payload, context="signal message fallback (plain)")