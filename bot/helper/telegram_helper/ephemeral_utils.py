import re
import aiohttp
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ButtonStyle

from ... import LOGGER
from ...core.config_manager import Config


def clean_inside_buttons(text):
    if not text:
        return text
    return re.sub(r'</?tg-button(-row)?(\s+[^>]*)?>', '', str(text))


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

    # If inside buttons are enabled or text contains <tg-button>, try sendRichMessage
    if use_inside_buttons or "<tg-button" in text:
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
            return res.get("result")

    # Standard sendMessage with ephemeral parameters
    payload["text"] = text
    if markup:
        payload["reply_markup"] = markup

    res = await call_bot_api("sendMessage", payload)
    if res and res.get("ok"):
        return res.get("result")
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

    payload["text"] = text
    if markup:
        payload["reply_markup"] = markup

    # Try editEphemeralMessageText first
    res = await call_bot_api("editEphemeralMessageText", payload)
    if res and res.get("ok"):
        return res.get("result")

    # Fallback to standard editMessageText
    payload.pop("ephemeral_message_parameters", None)
    res = await call_bot_api("editMessageText", payload)
    if res and res.get("ok"):
        return res.get("result")
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
        # Fallback to editing the message via Pyrogram
        try:
            from .message_utils import edit_message
            await edit_message(query.message, text, buttons)
        except Exception as e:
            LOGGER.error(f"Fallback edit_message error: {e}")
    return res
