from asyncio import gather, iscoroutinefunction
from html import escape
from pyrogram.enums import ButtonStyle
from re import findall
from time import time

from psutil import cpu_percent, disk_usage, virtual_memory

from ... import (
    DOWNLOAD_DIR,
    bot_cache,
    bot_start_time,
    status_dict,
    task_dict,
    task_dict_lock,
)
from ...core.config_manager import Config
from ..telegram_helper.button_build import ButtonMaker

SIZE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


class MirrorStatus:
    STATUS_UPLOAD = "Upload"
    STATUS_DOWNLOAD = "Download"
    STATUS_CLONE = "Clone"
    STATUS_QUEUEDL = "QueueDl"
    STATUS_QUEUEUP = "QueueUp"
    STATUS_PAUSED = "Pause"
    STATUS_ARCHIVE = "Archive"
    STATUS_EXTRACT = "Extract"
    STATUS_SPLIT = "Split"
    STATUS_CHECK = "CheckUp"
    STATUS_SEED = "Seed"
    STATUS_SAMVID = "SamVid"
    STATUS_CONVERT = "Convert"
    STATUS_FFMPEG = "FFmpeg"
    STATUS_YT = "YouTube"
    STATUS_METADATA = "Metadata"


class EngineStatus:
    def __init__(self):
        ver = bot_cache.get("eng_versions", {})
        self.STATUS_ARIA2 = f"Aria2 v{ver.get('aria2', 'N/A')}"
        self.STATUS_AIOHTTP = f"AioHttp v{ver.get('aiohttp', 'N/A')}"
        self.STATUS_GDAPI = f"Google-API v{ver.get('gapi', 'N/A')}"
        self.STATUS_QBIT = f"qBit v{ver.get('qBittorrent', 'N/A')}"
        self.STATUS_TGRAM = f"Pyro v{ver.get('pyrotgfork', 'N/A')}"
        self.STATUS_MEGA = f"MegaSDK v{ver.get('mega', 'N/A')}"
        self.STATUS_YTDLP = f"yt-dlp v{ver.get('yt-dlp', 'N/A')}"
        self.STATUS_FFMPEG = f"ffmpeg v{ver.get('ffmpeg', 'N/A')}"
        self.STATUS_7Z = f"7z v{ver.get('7z', 'N/A')}"
        self.STATUS_RCLONE = f"RClone v{ver.get('rclone', 'N/A')}"
        self.STATUS_SABNZBD = f"SABnzbd+ v{ver.get('SABnzbd+', 'N/A')}"
        self.STATUS_QUEUE = "QSystem v2"
        self.STATUS_JD = "JDownloader v2"
        self.STATUS_YT = "Youtube-Api"
        self.STATUS_METADATA = "Metadata"
        self.STATUS_UPHOSTER = "Uphoster"


STATUSES = {
    "ALL": "All",
    "DL": MirrorStatus.STATUS_DOWNLOAD,
    "UP": MirrorStatus.STATUS_UPLOAD,
    "QD": MirrorStatus.STATUS_QUEUEDL,
    "QU": MirrorStatus.STATUS_QUEUEUP,
    "AR": MirrorStatus.STATUS_ARCHIVE,
    "EX": MirrorStatus.STATUS_EXTRACT,
    "SD": MirrorStatus.STATUS_SEED,
    "CL": MirrorStatus.STATUS_CLONE,
    "CM": MirrorStatus.STATUS_CONVERT,
    "SP": MirrorStatus.STATUS_SPLIT,
    "SV": MirrorStatus.STATUS_SAMVID,
    "FF": MirrorStatus.STATUS_FFMPEG,
    "PA": MirrorStatus.STATUS_PAUSED,
    "CK": MirrorStatus.STATUS_CHECK,
}


async def get_task_by_gid(gid: str):
    async with task_dict_lock:
        for tk in task_dict.values():
            if hasattr(tk, "seeding"):
                await tk.update()
            if tk.gid() == gid or tk.gid().startswith(gid):
                return tk
        return None


async def get_specific_tasks(status, user_id):
    if status == "All":
        if user_id:
            return [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        else:
            return list(task_dict.values())
    tasks_to_check = (
        [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        if user_id
        else list(task_dict.values())
    )
    coro_tasks = []
    coro_tasks.extend(tk for tk in tasks_to_check if iscoroutinefunction(tk.status))
    coro_statuses = await gather(*[tk.status() for tk in coro_tasks])
    result = []
    coro_index = 0
    for tk in tasks_to_check:
        if tk in coro_tasks:
            st = coro_statuses[coro_index]
            coro_index += 1
        else:
            st = tk.status()
        if (st == status) or (
            status == MirrorStatus.STATUS_DOWNLOAD and st not in STATUSES.values()
        ):
            result.append(tk)
    return result


async def get_all_tasks(req_status: str, user_id):
    async with task_dict_lock:
        return await get_specific_tasks(req_status, user_id)


def get_raw_file_size(size):
    num, unit = size.split()
    return int(float(num) * (1024 ** SIZE_UNITS.index(unit)))


def get_readable_file_size(size_in_bytes):
    if not size_in_bytes:
        return "0B"
    if size_in_bytes < 0:
        return "Unknown"

    index = 0
    while size_in_bytes >= 1024 and index < len(SIZE_UNITS) - 1:
        size_in_bytes /= 1024
        index += 1

    return f"{size_in_bytes:.2f}{SIZE_UNITS[index]}"


def get_readable_time(seconds: int):
    periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f"{int(period_value)}{period_name}"
    return result


def get_raw_time(time_str: str) -> int:
    time_units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(
        int(value) * time_units[unit]
        for value, unit in findall(r"(\d+)([dhms])", time_str)
    )


def time_to_seconds(time_duration):
    try:
        parts = time_duration.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = map(float, parts)
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = map(float, parts)
        elif len(parts) == 1:
            hours = 0
            minutes = 0
            seconds = float(parts[0])
        else:
            return 0
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0


def speed_string_to_bytes(size_text: str):
    size = 0
    size_text = size_text.lower()
    if "k" in size_text:
        size += float(size_text.split("k")[0]) * 1024
    elif "m" in size_text:
        size += float(size_text.split("m")[0]) * 1048576
    elif "g" in size_text:
        size += float(size_text.split("g")[0]) * 1073741824
    elif "t" in size_text:
        size += float(size_text.split("t")[0]) * 1099511627776
    elif "b" in size_text:
        size += float(size_text.split("b")[0])
    return size


# --- Telegram Premium Custom Emojis ---
EM_1 = '<tg-emoji emoji-id="5877219383691972108">➕</tg-emoji>'
EM_2 = '<tg-emoji emoji-id="5195111279244619776">🍀</tg-emoji>'
EM_3 = '<tg-emoji emoji-id="5287533898803211359">📫</tg-emoji>'
EM_4 = '<tg-emoji emoji-id="5411590687663608498">⚡</tg-emoji>'
EM_5 = '<tg-emoji emoji-id="5422407403884798028">🍀</tg-emoji>'
EM_6 = '<tg-emoji emoji-id="5424867354993513047">🌷</tg-emoji>'
EM_7 = '<tg-emoji emoji-id="5443127283898405358">⬇️</tg-emoji>'
EM_8 = '<tg-emoji emoji-id="5445355530111437729">⬆️</tg-emoji>'
EM_9 = '<tg-emoji emoji-id="5765005318610228026">❌</tg-emoji>'
EM_10 = '<tg-emoji emoji-id="5285439518130857782">❤️</tg-emoji>'
EM_11 = '<tg-emoji emoji-id="5190642636356072894">☔️</tg-emoji>'
EM_12 = '<tg-emoji emoji-id="5256218768262056531">🟪</tg-emoji>'
EM_13 = '<tg-emoji emoji-id="5285535716808342592">☠️</tg-emoji>'
EM_14 = '<tg-emoji emoji-id="5224607267797606837">⚡</tg-emoji>'
EM_15 = '<tg-emoji emoji-id="5305265301917549162">📎</tg-emoji>'
PRG_FULL = '<tg-emoji emoji-id="5321086282103792429">🌷</tg-emoji>'
PRG_EMPTY = '<tg-emoji emoji-id="5971816626796892111">🔹</tg-emoji>'
# ----------------------------------------


def get_progress_bar_string(pct):
    try:
        pct_float = float(str(pct).strip("%"))
    except Exception:
        pct_float = 0
    p = min(max(pct_float, 0), 100)
    cFull = int(p // 8)
    p_str = PRG_FULL * cFull + PRG_EMPTY * (12 - cFull)
    return f"[{p_str}]"


async def get_readable_message(sid, is_user, page_no=1, status="All", page_step=1):
    msg = ""
    tasks = await get_specific_tasks(status, sid if is_user else None)

    STATUS_LIMIT = Config.STATUS_LIMIT
    tasks_no = len(tasks)
    pages = (max(tasks_no, 1) + STATUS_LIMIT - 1) // STATUS_LIMIT
    if page_no > pages:
        page_no = (page_no - 1) % pages + 1
        status_dict[sid]["page_no"] = page_no
    elif page_no < 1:
        page_no = pages - (abs(page_no) % pages)
        status_dict[sid]["page_no"] = page_no
    start_position = (page_no - 1) * STATUS_LIMIT

    for index, task in enumerate(
        tasks[start_position : STATUS_LIMIT + start_position], start=1
    ):
        idx = index + start_position
        if status != "All":
            tstatus = status
        elif iscoroutinefunction(task.status):
            tstatus = await task.status()
        else:
            tstatus = task.status()

        # Task header line 1: index and title
        msg += f"<b>{idx}. {escape(task.name())}</b><br>\n"
        if task.listener.subname:
            msg += f"┖ <b>Sub Name</b> → <i>{task.listener.subname}</i><br>\n"

        elapsed = time() - task.listener.message.date.timestamp()
        link_str = f' <i>[<a href="{task.listener.message.link}">Link</a>]</i>' if task.listener.is_super_chat else ""

        # Task header line 2: Task By
        from_user = task.listener.message.from_user
        user_id = from_user.id if from_user else getattr(task.listener, "user_id", 0)
        user_name = escape((from_user.first_name if from_user else None) or "User")
        user_mention = f'<a href="tg://user?id={user_id}">{user_name}</a>'
        msg += f"{EM_14} <b>Task By</b> {user_mention} ( #ID{user_id} ){link_str}<br>\n"

        # Task progress check
        has_prog = (
            tstatus not in [MirrorStatus.STATUS_SEED, MirrorStatus.STATUS_QUEUEUP]
            and task.listener.progress
        )
        msg += "<br>\n"

        gid_short = task.gid()[:8]
        is_torrent = getattr(task.listener, "is_torrent", False) or getattr(task.listener, "is_qbit", False)

        # Native Rich Table for Task with Premium Emojis (Progress bar as main table caption title)
        msg += '<table border="1">\n'
        if has_prog:
            progress = task.progress()
            msg += f'<caption>{get_progress_bar_string(progress)} <i>{progress}</i></caption>\n'
        if has_prog:
            if task.listener.subname:
                subsize = f" / {get_readable_file_size(task.listener.subsize)}"
                ac = len(task.listener.files_to_proceed)
                count = f" ( {task.listener.proceed_count} / {ac or '?'} )"
            else:
                subsize = ""
                count = ""
            msg += f"<tr><th>{EM_2} Processed</th><th><i>{task.processed_bytes()}{subsize} of {task.size()}{count}</i></th></tr>\n"
            msg += f"<tr><td>{EM_3} Status</td><td>{tstatus}</td></tr>\n"
            msg += f"<tr><td>{EM_4} Speed</td><td>{task.speed()}</td></tr>\n"
            msg += f"<tr><td>{EM_5} Time</td><td>{task.eta()} of {get_readable_time(elapsed + get_raw_time(task.eta()))} ( {get_readable_time(elapsed)} )</td></tr>\n"
            if tstatus == MirrorStatus.STATUS_DOWNLOAD and is_torrent:
                try:
                    s_num = task.seeders_num()
                    l_num = task.leechers_num()
                    if s_num is not None or l_num is not None:
                        msg += f"<tr><td>{EM_2} Seeders / Leechers</td><td>{s_num or 0} / {l_num or 0}</td></tr>\n"
                except Exception:
                    pass
        elif tstatus == MirrorStatus.STATUS_SEED:
            msg += f"<tr><th>{EM_6} Size</th><th><i>{task.size()} | Uploaded: {task.uploaded_bytes()}</i></th></tr>\n"
            msg += f"<tr><td>{EM_3} Status</td><td>{tstatus}</td></tr>\n"
            msg += f"<tr><td>{EM_4} Speed</td><td>{task.seed_speed()}</td></tr>\n"
            msg += f"<tr><td>{EM_1} Ratio</td><td>{task.ratio()}</td></tr>\n"
            msg += f"<tr><td>{EM_5} Time</td><td>{task.seeding_time()} ( {get_readable_time(elapsed)} )</td></tr>\n"
        else:
            msg += f"<tr><th>{EM_6} Size</th><th><i>{task.size()}</i></th></tr>\n"
            msg += f"<tr><td>{EM_3} Status</td><td>{tstatus}</td></tr>\n"

        msg += f"<tr><td>{EM_13} Engine</td><td>{task.engine}</td></tr>\n"
        msg += f"<tr><td>{EM_7} In Mode</td><td>{task.listener.mode[0]}</td></tr>\n"
        msg += f"<tr><td>{EM_8} Out Mode</td><td>{task.listener.mode[1]}</td></tr>\n"
        msg += "</table>\n"

        # Buttons Inside Message right under task table
        can_select = (
            tstatus in [
                MirrorStatus.STATUS_DOWNLOAD,
                MirrorStatus.STATUS_PAUSED,
                MirrorStatus.STATUS_QUEUEDL,
            ]
            and is_torrent
        )
        msg += '<tg-button-row align="center">'
        if can_select:
            msg += f'<tg-button type="callback_data" data="status {sid} sel {gid_short}" style="primary">📂 Select #{idx}</tg-button>'
        msg += f'<tg-button type="callback_data" data="status {sid} can {gid_short}" style="danger">❌ Cancel #{idx}</tg-button>'
        msg += '</tg-button-row><br><br>\n\n'

    if len(tasks) == 0:
        if status == "All":
            return None, None
        else:
            msg = f"<b>No Active {status} Tasks!</b><br><br>\n\n"

    # Native Rich Table for Bot Stats
    msg += f"{EM_12} <b><u>Bot Stats</u></b><br>\n"
    if len(tasks) > STATUS_LIMIT:
        msg += f"<b>Page:</b> {page_no}/{pages} | <b>Tasks:</b> {tasks_no} | <b>Step:</b> {page_step}<br>\n"

    msg += '<table border="1">\n'
    msg += f'<tr><th>{EM_10} CPU</th><th>{EM_15} Free</th><th>{EM_11} RAM</th><th>{EM_4} UP</th></tr>\n'
    msg += f'<tr><td>{cpu_percent()}%</td><td>{get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)} [{round(100 - disk_usage(DOWNLOAD_DIR).percent, 1)}%]</td><td>{virtual_memory().percent}%</td><td>{get_readable_time(time() - bot_start_time)}</td></tr>\n'
    msg += '</table>\n'

    # Bottom Inside Buttons
    msg += '<tg-button-row align="center">'
    if len(tasks) > STATUS_LIMIT:
        msg += f'<tg-button type="callback_data" data="status {sid} pre">&lt;&lt;</tg-button>'
        msg += f'<tg-button type="callback_data" data="status {sid} nex">&gt;&gt;</tg-button>'
    if not is_user:
        msg += f'<tg-button type="callback_data" data="status {sid} ov" style="primary">📜 TStats</tg-button>'
    msg += f'<tg-button type="callback_data" data="status {sid} ref" style="primary">♻️ Refresh</tg-button>'
    msg += '</tg-button-row>'

    return msg, None
