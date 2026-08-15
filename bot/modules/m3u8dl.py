from asyncio import Event, create_subprocess_exec, wait_for
from asyncio.subprocess import PIPE
from functools import partial
from os import path as ospath
from re import compile as re_compile
from secrets import token_hex
from shlex import split as shlex_split
from time import time

from aiofiles.os import listdir
from pyrogram.filters import regex, user
from pyrogram.handlers import CallbackQueryHandler

from .. import DOWNLOAD_DIR, LOGGER, bot_loop, task_dict, task_dict_lock
from ..helper.ext_utils.bot_utils import COMMAND_USAGE, arg_parser, new_task
from ..helper.ext_utils.links_utils import is_url
from ..helper.ext_utils.status_utils import get_readable_time
from ..helper.ext_utils.task_manager import check_running_tasks, limit_checker, stop_duplicate_check
from ..helper.listeners.task_listener import TaskListener
from ..helper.mirror_leech_utils.status_utils.m3u8dl_status import M3u8dlStatus
from ..helper.mirror_leech_utils.status_utils.queue_status import QueueStatus
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import delete_message, edit_message, send_message, send_status_message

_STREAM_RE = re_compile(r"(?P<type>Vid|Aud|Sub)\s+(?P<flags>\*?\w*\s*)?(?P<id>[^|]+?)\s*\|\s*(?P<info>.+)")
_PROGRESS_RE = re_compile(r"(?P<pct>\d+(?:\.\d+)?)%")


def _header_args(headers):
    args = []
    for header in headers:
        args.extend(["-H", header])
    return args


def _parse_headers(raw):
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace("|", "\n").split("\n")]
    return [p for p in parts if p]


async def probe_streams(link, headers, extra_args):
    cmd = [
        "N_m3u8DL-RE",
        link,
        "--skip-download",
        "--no-log",
        "--write-meta-json",
        "--no-ansi-color",
        "--log-level",
        "INFO",
        *_header_args(headers),
        *extra_args,
    ]
    proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    out, err = await proc.communicate()
    text = f"{out.decode(errors='ignore')}\n{err.decode(errors='ignore')}"
    streams = {"Vid": [], "Aud": [], "Sub": []}
    for line in text.splitlines():
        if match := _STREAM_RE.search(line):
            data = match.groupdict()
            data["id"] = data["id"].strip().lstrip("* ")
            data["label"] = f"{data['id']} | {data['info'].strip()}"
            streams[data["type"]].append(data)
    if proc.returncode and not any(streams.values()):
        raise RuntimeError(text[-3500:] or "N_m3u8DL-RE failed to parse this link")
    return streams


@new_task
async def m3u8_select(_, query, obj):
    data = query.data.split()
    await query.answer()
    if data[1] == "cancel":
        await edit_message(query.message, "Task has been cancelled.")
        obj.listener.is_cancelled = True
        obj.event.set()
    elif data[1] == "done":
        obj.event.set()
    elif data[1] == "toggle":
        obj.toggle(int(data[2]))
        await obj.refresh()


class M3U8Selection:
    def __init__(self, listener, streams, kind):
        self.listener = listener
        self.streams = streams
        self.kind = kind
        self.selected = set()
        self.event = Event()
        self._reply_to = None
        self._timeout = 120
        self._time = time()

    def toggle(self, index):
        self.selected.symmetric_difference_update({index})

    def _buttons(self):
        buttons = ButtonMaker()
        for index, stream in enumerate(self.streams):
            prefix = "✅" if index in self.selected else "☑️"
            label = stream["label"][:54]
            buttons.data_button(f"{prefix} {label}", f"m3u8q toggle {index}")
        buttons.data_button("Done", "m3u8q done", "footer")
        buttons.data_button("Cancel", "m3u8q cancel", "footer")
        return buttons.build_menu(1)

    async def refresh(self):
        await edit_message(self._reply_to, self._message(), self._buttons())

    def _message(self):
        return f"Choose {self.kind} stream(s):\nTimeout: {get_readable_time(self._timeout - (time() - self._time))}"

    async def get(self):
        if not self.streams:
            return []
        self._reply_to = await send_message(self.listener.message, self._message(), self._buttons())
        pfunc = partial(m3u8_select, obj=self)
        handler = self.listener.client.add_handler(CallbackQueryHandler(pfunc, filters=regex("^m3u8q") & user(self.listener.user_id)), group=-1)
        try:
            await wait_for(self.event.wait(), timeout=self._timeout)
        except Exception:
            await edit_message(self._reply_to, "Timed Out. Task has been cancelled!")
            self.listener.is_cancelled = True
        finally:
            self.listener.client.remove_handler(*handler)
        if not self.listener.is_cancelled:
            await delete_message(self._reply_to)
        return [self.streams[i] for i in sorted(self.selected)]


class M3U8DLHelper:
    def __init__(self, listener):
        self.listener = listener
        self._gid = token_hex(5)
        self._processed = 0
        self._speed = 0
        self._progress = 0
        self.proc = None

    @property
    def progress(self): return self._progress
    @property
    def processed_bytes(self): return self._processed
    @property
    def speed(self): return self._speed

    async def add_download(self, path, headers, extra_args, videos, audios):
        msg, button = await stop_duplicate_check(self.listener)
        if msg:
            await self.listener.on_download_error(msg, button)
            return
        if limit_exceeded := await limit_checker(self.listener):
            await self.listener.on_download_error(limit_exceeded, is_limit=True)
            return
        add_to_queue, event = await check_running_tasks(self.listener)
        async with task_dict_lock:
            task_dict[self.listener.mid] = QueueStatus(self.listener, self._gid, "dl") if add_to_queue else M3u8dlStatus(self.listener, self, self._gid)
        if add_to_queue:
            await event.wait()
            if self.listener.is_cancelled:
                return
            async with task_dict_lock:
                task_dict[self.listener.mid] = M3u8dlStatus(self.listener, self, self._gid)
        await self.listener.on_download_start()
        if self.listener.multi <= 1 and not self.listener.is_rss:
            await send_status_message(self.listener.message)
        cmd = ["N_m3u8DL-RE", self.listener.link, "--save-dir", path, "--tmp-dir", f"{path}/.m3u8dl", "--no-log", "--no-ansi-color", "--thread-count", "16", "--download-retry-count", "10", "-M", "format=mkv", *_header_args(headers)]
        if self.listener.name:
            cmd.extend(["--save-name", ospath.splitext(self.listener.name)[0]])
        for v in videos:
            cmd.extend(["-sv", f'id="{v["id"]}"'])
        for a in audios:
            cmd.extend(["-sa", f'id="{a["id"]}"'])
        if not videos and not audios:
            cmd.append("--auto-select")
        cmd.extend(extra_args)
        LOGGER.info("Running N_m3u8DL-RE: %s", " ".join(cmd))
        self.proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        async def read_stream(stream):
            while line := await stream.readline():
                text = line.decode(errors="ignore").strip()
                if pct := _PROGRESS_RE.search(text):
                    self._progress = float(pct.group("pct"))
                LOGGER.info("N_m3u8DL-RE: %s", text)
        from asyncio import gather
        _, err = await gather(read_stream(self.proc.stdout), self.proc.stderr.read())
        rc = await self.proc.wait()
        if rc:
            await self.listener.on_download_error((err.decode(errors="ignore") or "N_m3u8DL-RE failed")[-3500:])
            return
        files = await listdir(path)
        self.listener.name = self.listener.name or next((f for f in files if not f.startswith(".")), "N_m3u8DL-RE")
        await self.listener.on_download_complete()

    async def cancel_task(self):
        self.listener.is_cancelled = True
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
        await self.listener.on_download_error("Stopped by User!")


class M3U8DL(TaskListener):
    def __init__(self, client, message, is_leech=False, **kwargs):
        self.message = message
        self.client = client
        self.same_dir = {}
        self.bulk = []
        self.multi_tag = None
        self.options = ""
        super().__init__()
        self.is_leech = is_leech

    async def new_event(self):
        text = self.message.text.split("\n")
        input_list = text[0].split(" ")
        args = {"-s": True, "-n": "", "-m": "", "-up": "", "-h": "", "--headers": "", "-opt": "", "link": "", "-i": 0, "-sp": 0, "-z": False, "-f": False, "-fd": False, "-fu": False, "-doc": False, "-med": False, "-hl": False, "-bt": False, "-ut": False, "-t": "", "-ca": "", "-cv": "", "-ns": "", "-tl": "", "-meta": "", "-gc": "", "-rcf": "", "-sv": False, "-ss": False, "-ff": set()}
        arg_parser(input_list[1:], args)
        self.link = args["link"]
        if not self.link and self.message.reply_to_message and self.message.reply_to_message.text:
            self.link = self.message.reply_to_message.text.split("\n", 1)[0].strip()
        if not is_url(self.link):
            await send_message(self.message, COMMAND_USAGE.get("m3u8", ["/cmd link --headers 'Header: value'"])[0])
            return
        self.name = args["-n"]
        self.up_dest = args["-up"]
        self.category = args["-gc"]
        self.rc_flags = args["-rcf"]
        self.compress = args["-z"]
        self.thumb = args["-t"]
        self.split_size = args["-sp"]
        self.sample_video = args["-sv"]
        self.screen_shots = args["-ss"]
        self.force_run = args["-f"]
        self.force_download = args["-fd"]
        self.force_upload = args["-fu"]
        self.convert_audio = args["-ca"]
        self.convert_video = args["-cv"]
        self.name_swap = args["-ns"]
        self.hybrid_leech = args["-hl"]
        self.thumbnail_layout = args["-tl"]
        self.as_doc = args["-doc"]
        self.as_med = args["-med"]
        self.bot_trans = args["-bt"]
        self.user_trans = args["-ut"]
        self.folder_name = f"/{args['-m']}".rstrip("/") if args["-m"] else ""
        self.multi = int(args["-i"] or 0)
        await self.get_tag(text)
        try:
            await self.before_start()
        except Exception as e:
            await send_message(self.message, e)
            return
        self._set_mode_engine()
        path = f"{DOWNLOAD_DIR}{self.mid}{self.folder_name}"
        headers = _parse_headers(args["--headers"] or args["-h"])
        extra_args = shlex_split(args["-opt"]) if args["-opt"] else []
        videos = audios = []
        if args["-s"]:
            try:
                streams = await probe_streams(self.link, headers, extra_args)
            except Exception as e:
                await send_message(self.message, str(e))
                return
            videos = await M3U8Selection(self, streams["Vid"], "video").get()
            if self.is_cancelled:
                return
            audios = await M3U8Selection(self, streams["Aud"], "audio").get()
            if self.is_cancelled:
                return
        await M3U8DLHelper(self).add_download(path, headers, extra_args, videos, audios)


async def m3u8_mirror(client, message):
    bot_loop.create_task(M3U8DL(client, message).new_event())


async def m3u8_leech(client, message):
    bot_loop.create_task(M3U8DL(client, message, is_leech=True).new_event())
