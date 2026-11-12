import re
import aiohttp
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ButtonStyle

from ... import LOGGER
from ...core.config_manager import Config


class RichBotChat:
    def __init__(self, chat_id, title=None, username=None, type="supergroup"):
        self.id = chat_id
        self.title = title
        self.username = username
        self.type = type


class RichBotMessage:
    def __init__(self, raw_data=None, text="", chat_id=None, message_id=None):
        self.text = text
        if isinstance(raw_data, dict):
            res = raw_data.get("result", raw_data)
            self.id = res.get("message_id", message_id)
            self.message_id = self.id
            chat_info = res.get("chat", {})
            self.chat = RichBotChat(
                chat_info.get("id", chat_id),
                chat_info.get("title"),
                chat_info.get("username"),
                chat_info.get("type", "supergroup")
            )
            self.date = res.get("date")
            if not self.text:
                self.text = res.get("text", "")
            self.media = None
            self._raw = res
        elif raw_data is not None:
            self.id = getattr(raw_data, "id", None) or getattr(raw_data, "message_id", message_id or 0)
            self.message_id = self.id
            chat_obj = getattr(raw_data, "chat", None)
            self.chat = chat_obj or RichBotChat(chat_id or 0)
            self.date = getattr(raw_data, "date", None)
            self.media = getattr(raw_data, "media", None)
            if not self.text:
                self.text = getattr(raw_data, "text", "")
            self._raw = raw_data
        else:
            self.id = message_id or 0
            self.message_id = self.id
            self.chat = RichBotChat(chat_id or 0)
            self.date = None
            self.media = None
            self._raw = {}

    @property
    def link(self):
        username = getattr(self.chat, "username", None)
        if username:
            return f"https://t.me/{username}/{self.id}"
        cid = str(getattr(self.chat, "id", 0))
        if cid.startswith("-100"):
            cid = cid[4:]
        return f"https://t.me/c/{cid}/{self.id}"

    async def edit(self, text, *args, **kwargs):
        return await edit_rich_message(self.chat.id, self.id, text, **kwargs)

    async def edit_text(self, text, *args, **kwargs):
        return await self.edit(text, *args, **kwargs)

    async def delete(self):
        try:
            from ...core.tg_client import TgClient
            return await TgClient.bot.delete_messages(self.chat.id, self.id)
        except Exception:
            return None

    def __getattr__(self, name):
        return None


def clean_inside_buttons(text):
    if not text:
        return text
    return re.sub(r'</?tg-button(-row)?(\s+[^>]*)?>', '', str(text))


def clean_rich_to_html(text):
    if not text:
        return ""
    s = str(text)
    # Convert 4-column table headers and rows (e.g. Bot Stats)
    s = re.sub(r'<tr>\s*<th>(.*?)</th>\s*<th>(.*?)</th>\s*<th>(.*?)</th>\s*<th>(.*?)</th>\s*</tr>', r'<b>\1</b> | <b>\2</b> | <b>\3</b> | <b>\4</b>\n', s, flags=re.IGNORECASE)
    s = re.sub(r'<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', r'\1 | \2 | \3 | \4\n', s, flags=re.IGNORECASE)
    # Convert 2-column table rows
    s = re.sub(r'<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>', r'<b>\1:</b> \2\n', s, flags=re.IGNORECASE)
    # Strip remaining table tags
    s = re.sub(r'</?(table|tbody|tr|th|td)(\s+[^>]*)?>', '', s, flags=re.IGNORECASE)
    # Strip inside button tags
    s = clean_inside_buttons(s)
    # Normalize extra blank lines
    s = re.sub(r'\n{3,}', '\n\n', s).strip()
    return s


def extract_buttons_from_html(text):
    if not text or "<tg-button" not in text:
        return None
    matrix = []
    rows = re.findall(r'<tg-button-row(?:\s+[^>]*)?>(.*?)</tg-button-row>', text, flags=re.DOTALL | re.IGNORECASE)
    for row in rows:
        btn_row = []
        btns = re.findall(r'<tg-button\s+([^>]*?)>(.*?)</tg-button>', row, flags=re.DOTALL | re.IGNORECASE)
        for attrs_str, label in btns:
            attrs = dict(re.findall(r'(\w+)=["\']([^"\']*)["\']', attrs_str))
            item = {"text": label.strip()}
            if "url" in attrs:
                item["url"] = attrs["url"]
            elif "data" in attrs:
                item["callback_data"] = attrs["data"]
            if "style" in attrs:
                item["style"] = attrs["style"]
            btn_row.append(item)
        if btn_row:
            matrix.append(btn_row)
    if not matrix:
        return None
    return {"inline_keyboard": matrix}


def _map_btn_style(style):
    if not style:
        return None
    if isinstance(style, ButtonStyle):
        style = style.name.lower()
    style_str = str(style).lower()
    if "primary" in style_str:
        return "primary"
    elif "danger" in style_str:
        return "danger"
    elif "success" in style_str:
        return "success"
    elif "link" in style_str:
        return "link"
    return None


def keyboard_to_bot_api(reply_markup):
    if not reply_markup:
        return None
    if isinstance(reply_markup, dict) and "inline_keyboard" in reply_markup:
        return reply_markup
    if isinstance(reply_markup, InlineKeyboardMarkup):
        matrix = reply_markup.inline_keyboard
    elif isinstance(reply_markup, list):
        matrix = reply_markup
    else:
        return None

    api_keyboard = []
    for row in matrix:
        api_row = []
        for btn in row:
            if isinstance(btn, dict):
                api_row.append(btn)
                continue
            item = {"text": getattr(btn, "text", "")}
            if getattr(btn, "url", None):
                item["url"] = btn.url
            elif getattr(btn, "callback_data", None):
                item["callback_data"] = btn.callback_data
            elif getattr(btn, "web_app", None):
                item["web_app"] = {"url": btn.web_app.url}

            style = getattr(btn, "style", None)
            mapped_style = _map_btn_style(style)
            if mapped_style:
                item["style"] = mapped_style
            api_row.append(item)
        if api_row:
            api_keyboard.append(api_row)
    return {"inline_keyboard": api_keyboard}


def inside_buttons_to_html(reply_markup, align="center"):
    if not reply_markup:
        return ""
    if isinstance(reply_markup, InlineKeyboardMarkup):
        matrix = reply_markup.inline_keyboard
    elif isinstance(reply_markup, dict) and "inline_keyboard" in reply_markup:
        matrix = reply_markup["inline_keyboard"]
    elif isinstance(reply_markup, list):
        matrix = reply_markup
    else:
        return ""

    html_blocks = []
    align_attr = f' align="{align}"' if align else ""
    for row in matrix:
        row_tags = []
        for btn in row:
            text = btn.get("text", "") if isinstance(btn, dict) else getattr(btn, "text", "")
            url = btn.get("url") if isinstance(btn, dict) else getattr(btn, "url", None)
            cb = btn.get("callback_data") if isinstance(btn, dict) else getattr(btn, "callback_data", None)
            web_app = btn.get("web_app") if isinstance(btn, dict) else getattr(btn, "web_app", None)
            style = btn.get("style") if isinstance(btn, dict) else getattr(btn, "style", None)
            style_str = f' style="{_map_btn_style(style)}"' if _map_btn_style(style) else ""

            if url:
                row_tags.append(f'<tg-button type="url" url="{url}"{style_str}>{text}</tg-button>')
            elif cb:
                row_tags.append(f'<tg-button type="callback_data" data="{cb}"{style_str}>{text}</tg-button>')
            elif web_app:
                wa_url = web_app.get("url") if isinstance(web_app, dict) else getattr(web_app, "url", "")
                row_tags.append(f'<tg-button type="web_app" url="{wa_url}"{style_str}>{text}</tg-button>')
        if row_tags:
            html_blocks.append(f'<tg-button-row{align_attr}>' + "".join(row_tags) + '</tg-button-row>')
    return "\n".join(html_blocks)


async def call_bot_api(method, payload, timeout=10):
    token = Config.BOT_TOKEN
    if not token:
        return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    LOGGER.warning(f"Bot API {method} returned not ok: {data}")
                return data
    except Exception as e:
        LOGGER.warning(f"Bot API call {method} exception: {e}")
        return None


async def send_rich_message(chat_id, text, buttons=None, parse_mode="HTML"):
    chat_id_int = getattr(chat_id, "id", chat_id)
    payload = {
        "chat_id": chat_id_int,
        "rich_message": {"html": text},
    }
    markup = keyboard_to_bot_api(buttons) if buttons else None
    if markup:
        payload["reply_markup"] = markup

    res = await call_bot_api("sendRichMessage", payload)
    if res and res.get("ok"):
        return RichBotMessage(res.get("result"), text=text)

    # Fallback to sendMessage if sendRichMessage not accepted
    LOGGER.warning("sendRichMessage failed, falling back to sendMessage")
    clean_text = clean_rich_to_html(text)
    fallback_payload = {
        "chat_id": chat_id_int,
        "text": clean_text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if markup:
        fallback_payload["reply_markup"] = markup
    else:
        extracted = extract_buttons_from_html(text)
        if extracted:
            fallback_payload["reply_markup"] = extracted

    res = await call_bot_api("sendMessage", fallback_payload)
    if res and res.get("ok"):
        return RichBotMessage(res.get("result"), text=clean_text)
    return None


async def edit_rich_message(chat_id, message_id, text, buttons=None, parse_mode="HTML"):
    chat_id_int = getattr(chat_id, "id", chat_id)
    payload = {
        "chat_id": chat_id_int,
        "message_id": message_id,
        "rich_message": {"html": text},
    }
    markup = keyboard_to_bot_api(buttons) if buttons else None
    if markup:
        payload["reply_markup"] = markup

    res = await call_bot_api("editMessageText", payload)
    if res and res.get("ok"):
        return RichBotMessage(res.get("result"), text=text)
    err_str = str(res or "").lower()
    if "message is not modified" in err_str:
        return RichBotMessage({"message_id": message_id, "chat": {"id": chat_id_int}}, text=text)

    # Fallback without rich_message
    clean_text = clean_rich_to_html(text)
    fallback_payload = {
        "chat_id": chat_id_int,
        "message_id": message_id,
        "text": clean_text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if markup:
        fallback_payload["reply_markup"] = markup
    else:
        extracted = extract_buttons_from_html(text)
        if extracted:
            fallback_payload["reply_markup"] = extracted

    res = await call_bot_api("editMessageText", fallback_payload)
    if res and res.get("ok"):
        return RichBotMessage(res.get("result"), text=clean_text)
    if res and "message is not modified" in str(res).lower():
        return RichBotMessage({"message_id": message_id, "chat": {"id": chat_id_int}}, text=clean_text)
    return None


async def send_ephemeral_message(
    chat_id,
    text,
    buttons=None,
    callback_query_id=None,
    receiver_user_id=None,
    replace_callback_query_message=False,
    use_inside_buttons=False,
    parse_mode="HTML",
):
    chat_id_int = getattr(chat_id, "id", chat_id)
    payload = {
        "chat_id": chat_id_int,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    ephemeral_params = {}
    if callback_query_id:
        ephemeral_params["callback_query_id"] = str(callback_query_id)
    if receiver_user_id:
        ephemeral_params["receiver_user_id"] = int(receiver_user_id)
    if replace_callback_query_message:
        ephemeral_params["replace_callback_query_message"] = True

    if ephemeral_params:
        payload["ephemeral_message_parameters"] = ephemeral_params

    markup = keyboard_to_bot_api(buttons)

    # If inside buttons or table requested, try sendRichMessage
    if use_inside_buttons or "<tg-button" in text or "<table" in text:
        rich_html = text
        if use_inside_buttons and markup:
            inside_html = inside_buttons_to_html(markup)
            if inside_html:
                rich_html = f"{text}\n\n{inside_html}"
                markup = None

        rich_payload = {
            "chat_id": chat_id_int,
            "rich_message": {"html": rich_html},
        }
        if ephemeral_params:
            rich_payload["ephemeral_message_parameters"] = ephemeral_params
        if markup:
            rich_payload["reply_markup"] = markup

        res = await call_bot_api("sendRichMessage", rich_payload)
        if res and res.get("ok"):
            return RichBotMessage(res.get("result"), text=rich_html)

    # Standard sendMessage with ephemeral parameters
    payload["text"] = clean_rich_to_html(text) if ("<table" in text or "<tg-button" in text) else text
    if markup:
        payload["reply_markup"] = markup
    else:
        extracted = extract_buttons_from_html(text)
        if extracted:
            payload["reply_markup"] = extracted

    res = await call_bot_api("sendMessage", payload)
    if res and res.get("ok"):
        return RichBotMessage(res.get("result"), text=payload["text"])
    return None


async def edit_ephemeral_message(
    chat_id,
    message_id,
    text,
    buttons=None,
    callback_query_id=None,
    use_inside_buttons=False,
    parse_mode="HTML",
):
    chat_id_int = getattr(chat_id, "id", chat_id)
    markup = keyboard_to_bot_api(buttons)

    payload = {
        "chat_id": chat_id_int,
        "message_id": message_id,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    if callback_query_id:
        payload["ephemeral_message_parameters"] = {
            "callback_query_id": str(callback_query_id),
            "replace_callback_query_message": True,
        }

    if use_inside_buttons and markup:
        inside_html = inside_buttons_to_html(markup)
        if inside_html:
            text = f"{text}\n\n{inside_html}"
            markup = None

    if "<table" in text or "<tg-button" in text:
        payload["rich_message"] = {"html": text}
    else:
        payload["text"] = text

    if markup:
        payload["reply_markup"] = markup

    # Try editEphemeralMessageText first
    res = await call_bot_api("editEphemeralMessageText", payload)
    if res and res.get("ok"):
        return RichBotMessage(res.get("result"), text=text)

    # Fallback to standard editMessageText
    payload.pop("ephemeral_message_parameters", None)
    res = await call_bot_api("editMessageText", payload)
    if res and res.get("ok"):
        return RichBotMessage(res.get("result"), text=text)
    if res and "message is not modified" in str(res).lower():
        return RichBotMessage({"message_id": message_id, "chat": {"id": chat_id_int}}, text=text)

    # Fallback with cleaned HTML
    if "rich_message" in payload:
        payload.pop("rich_message")
        payload["text"] = clean_rich_to_html(text)
        if not markup:
            extracted = extract_buttons_from_html(text)
            if extracted:
                payload["reply_markup"] = extracted
        res = await call_bot_api("editMessageText", payload)
        if res and res.get("ok"):
            return RichBotMessage(res.get("result"), text=payload["text"])
    return None


async def answer_callback_ephemeral(
    query,
    text,
    buttons=None,
    replace=True,
    use_inside_buttons=False,
):
    try:
        await query.answer()
    except Exception:
        pass

    chat_id = query.message.chat.id
    res = await send_ephemeral_message(
        chat_id=chat_id,
        text=text,
        buttons=buttons,
        callback_query_id=query.id,
        receiver_user_id=query.from_user.id,
        replace_callback_query_message=replace,
        use_inside_buttons=use_inside_buttons,
    )
    if not res:
        try:
            from .message_utils import edit_message
            await edit_message(query.message, text, buttons)
        except Exception as e:
            LOGGER.error(f"Fallback edit_message error: {e}")
    return res
