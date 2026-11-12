from psutil import cpu_percent, virtual_memory, disk_usage
from time import time
from asyncio import gather, iscoroutinefunction

from pyrogram.errors import QueryIdInvalid
from pyrogram.enums import ButtonStyle

from .. import (
    task_dict_lock,
    status_dict,
    task_dict,
    bot_start_time,
    intervals,
    sabnzbd_client,
    DOWNLOAD_DIR,
    user_data,
    LOGGER,
)
from ..core.config_manager import Config
from ..core.torrent_manager import TorrentManager
from ..core.jdownloader_booter import jdownloader
from ..helper.ext_utils.bot_utils import new_task, bt_selection_buttons
from ..helper.ext_utils.status_utils import (
    EngineStatus,
    MirrorStatus,
    get_readable_file_size,
    get_readable_time,
    speed_string_to_bytes,
    get_task_by_gid,
)
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.message_utils import (
    send_message,
    delete_message,
    auto_delete_message,
    send_status_message,
    update_status_message,
    edit_message,
)
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.ephemeral_utils import answer_callback_ephemeral, send_ephemeral_message


@new_task
async def task_status(_, message):
    async with task_dict_lock:
        count = len(task_dict)
    if count == 0:
        currentTime = get_readable_time(time() - bot_start_time)
        free = get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)
        msg = f"""〶 <b><i>No Active Bot Tasks!</i></b>
│
┖ <b>NOTE</b> → <i>Each user can get status for his tasks by adding "me" or user_id like "1234xxx" after cmd: /{BotCommands.StatusCommand[0]} me or /{BotCommands.StatusCommand[1]} me</i>

⌬ <b><u>Bot Stats</u></b>
┟ <b>CPU</b> → {cpu_percent()}% | <b>F</b> → {free} [{round(100 - disk_usage(DOWNLOAD_DIR).percent, 1)}%]
┖ <b>RAM</b> → {virtual_memory().percent}% | <b>UP</b> → {currentTime}
"""
        reply_message = await send_message(message, msg)
        await auto_delete_message(message, reply_message)
    else:
        text = message.text.split()
        if len(text) > 1:
            if text[1] == "me":
                user_id = message.from_user.id
            elif text[1].lstrip("-").isdigit():
                user_id = int(text[1])
            else:
                user_id = 0
        else:
            user_id = 0
            sid = message.chat.id
            if obj := intervals["status"].get(sid):
                obj.cancel()
                del intervals["status"][sid]
        await send_status_message(message, user_id)
        await delete_message(message)


async def get_download_status(download):
    eng = download.engine
    speed = (
        download.speed()
        if eng.startswith(("Pyro", "yt-dlp", "RClone", "Google-API"))
        else 0
    )
    return (
        (
            await download.status()
            if iscoroutinefunction(download.status)
            else download.status()
        ),
        speed,
        eng,
    )


@new_task
async def status_pages(_, query):
    data = query.data.split()
    key = int(data[1])
    if data[2] == "ref":
        await update_status_message(key, force=True)
    elif data[2] in ["nex", "pre"]:
        async with task_dict_lock:
            if key in status_dict:
                if data[2] == "nex":
                    status_dict[key]["page_no"] += status_dict[key]["page_step"]
                else:
                    status_dict[key]["page_no"] -= status_dict[key]["page_step"]
    elif data[2] == "ps":
        async with task_dict_lock:
            if key in status_dict:
                status_dict[key]["page_step"] = int(data[3])
    elif data[2] == "st":
        async with task_dict_lock:
            if key in status_dict:
                status_dict[key]["status"] = data[3]
        await update_status_message(key, force=True)
    elif data[2] == "can":
        user_id = query.from_user.id
        gid = data[3]
        task = await get_task_by_gid(gid)
        if task is None:
            await answer_callback_ephemeral(query, f"Task with GID <code>{gid}</code> not found or already finished!", replace=True)
            return
        if (
            Config.OWNER_ID != user_id
            and task.listener.user_id != user_id
            and (user_id not in user_data or not user_data[user_id].get("SUDO"))
        ):
            await answer_callback_ephemeral(query, "This task is not for you!", replace=False)
            return
        btn = ButtonMaker()
        btn.data_button("Yes, Cancel", f"status {key} canconf {gid}", style=ButtonStyle.DANGER)
        btn.data_button("No, Back", f"status {key} ref", style=ButtonStyle.SUCCESS)
        prompt_text = (
            f"<b>Cancel Task Confirmation</b>\n\n"
            f"<b>Name:</b> <code>{task.name()}</code>\n"
            f"<b>GID:</b> <code>{gid}</code>\n\n"
            f"<i>Are you sure you want to cancel this task?</i>\n"
            f'<tg-button-row align="center">'
            f'<tg-button type="callback_data" data="status {key} canconf {gid}" style="danger">Yes, Cancel</tg-button>'
            f'<tg-button type="callback_data" data="status {key} ref" style="success">No, Back</tg-button>'
            f'</tg-button-row>'
        )
        await answer_callback_ephemeral(query, prompt_text, btn.build_menu(2), replace=True, use_inside_buttons=True)
        return
    elif data[2] == "canconf":
        user_id = query.from_user.id
        gid = data[3]
        task = await get_task_by_gid(gid)
        if task is None:
            await answer_callback_ephemeral(query, f"Task with GID <code>{gid}</code> already finished or cancelled!", replace=True)
            return
        if (
            Config.OWNER_ID != user_id
            and task.listener.user_id != user_id
            and (user_id not in user_data or not user_data[user_id].get("SUDO"))
        ):
            await answer_callback_ephemeral(query, "This task is not for you!", replace=False)
            return
        task_name = task.name()
        obj = task.task()
        await obj.cancel_task()
        btn = ButtonMaker()
        btn.data_button("Back to Status", f"status {key} ref", style=ButtonStyle.PRIMARY)
        done_text = (
            f"<b>Task Cancelled!</b>\n<code>{task_name}</code>\n"
            f'<tg-button-row align="center">'
            f'<tg-button type="callback_data" data="status {key} ref" style="primary">Back to Status</tg-button>'
            f'</tg-button-row>'
        )
        await answer_callback_ephemeral(query, done_text, btn.build_menu(1), replace=True, use_inside_buttons=True)
        return
    elif data[2] == "sel":
        user_id = query.from_user.id
        gid = data[3]
        task = await get_task_by_gid(gid)
        if task is None:
            await answer_callback_ephemeral(query, f"Task with GID <code>{gid}</code> not found!", replace=True)
            return
        if (
            Config.OWNER_ID != user_id
            and task.listener.user_id != user_id
            and (user_id not in user_data or not user_data[user_id].get("SUDO"))
        ):
            await answer_callback_ephemeral(query, "This task is not for you!", replace=False)
            return
        if not iscoroutinefunction(task.status):
            await answer_callback_ephemeral(query, "The task has finished the download stage!", replace=True)
            return
        st = await task.status()
        if st not in [
            MirrorStatus.STATUS_DOWNLOAD,
            MirrorStatus.STATUS_PAUSED,
            MirrorStatus.STATUS_QUEUEDL,
        ]:
            await answer_callback_ephemeral(query, f"Task status ({st}) does not support file selection!", replace=True)
            return
        try:
            if not task.queued:
                await task.update()
                id_ = task.gid()
                if task.listener.is_nzb:
                    await sabnzbd_client.pause_job(id_)
                elif task.listener.is_qbit:
                    id_ = task.hash()
                    await TorrentManager.qbittorrent.torrents.stop([id_])
                else:
                    try:
                        await TorrentManager.aria2.forcePause(id_)
                    except Exception as e:
                        LOGGER.error(f"{e} Error in pause")
            task.listener.select = True
            SBUTTONS = bt_selection_buttons(id_)
            msg = "<b>Download Paused!</b>\n\n<i>Select your files &amp; press <b>Done Selecting</b> to start.</i>"
            await answer_callback_ephemeral(query, msg, SBUTTONS, replace=True, use_inside_buttons=True)
            return
        except Exception as e:
            await answer_callback_ephemeral(query, f"Selection error: {e}", replace=True)
            return
    elif data[2] == "ov":
        message = query.message
        tasks = {
            "Download": 0,
            "Upload": 0,
            "Seed": 0,
            "Archive": 0,
            "Extract": 0,
            "Split": 0,
            "QueueDl": 0,
            "QueueUp": 0,
            "Clone": 0,
            "CheckUp": 0,
            "Pause": 0,
            "SamVid": 0,
            "ConvertMedia": 0,
            "FFmpeg": 0,
        }
        dl_speed = 0
        up_speed = 0
        seed_speed = 0

        async with task_dict_lock:
            status_results = await gather(
                *(get_download_status(download) for download in task_dict.values())
            )

        eng_status = EngineStatus()
        if any(
            eng in (eng_status.STATUS_ARIA2, eng_status.STATUS_QBIT)
            for _, __, eng in status_results
        ):
            dl_speed, seed_speed = await TorrentManager.overall_speed()

        if any(eng == eng_status.STATUS_SABNZBD for _, __, eng in status_results):
            if not Config.DISABLE_NZB and sabnzbd_client.LOGGED_IN:
                dl_speed += (
                    int(
                        float(
                            (await sabnzbd_client.get_downloads())["queue"].get(
                                "kbpersec", "0"
                            )
                        )
                    )
                    * 1024
                )

        if any(eng == eng_status.STATUS_JD for _, __, eng in status_results):
            if not Config.DISABLE_JD and jdownloader.is_connected:
                dl_speed += (
                    await jdownloader.device.downloadcontroller.get_speed_in_bytes()
                )

        for status, speed, _ in status_results:
            match status:
                case MirrorStatus.STATUS_DOWNLOAD:
                    tasks["Download"] += 1
                    if speed:
                        dl_speed += speed_string_to_bytes(speed)
                case MirrorStatus.STATUS_UPLOAD:
                    tasks["Upload"] += 1
                    up_speed += speed_string_to_bytes(speed)
                case MirrorStatus.STATUS_SEED:
                    tasks["Seed"] += 1
                case MirrorStatus.STATUS_ARCHIVE:
                    tasks["Archive"] += 1
                case MirrorStatus.STATUS_EXTRACT:
                    tasks["Extract"] += 1
                case MirrorStatus.STATUS_SPLIT:
                    tasks["Split"] += 1
                case MirrorStatus.STATUS_QUEUEDL:
                    tasks["QueueDl"] += 1
                case MirrorStatus.STATUS_QUEUEUP:
                    tasks["QueueUp"] += 1
                case MirrorStatus.STATUS_CLONE:
                    tasks["Clone"] += 1
                case MirrorStatus.STATUS_CHECK:
                    tasks["CheckUp"] += 1
                case MirrorStatus.STATUS_PAUSED:
                    tasks["Pause"] += 1
                case MirrorStatus.STATUS_SAMVID:
                    tasks["SamVid"] += 1
                case MirrorStatus.STATUS_CONVERT:
                    tasks["ConvertMedia"] += 1
                case MirrorStatus.STATUS_FFMPEG:
                    tasks["FFmpeg"] += 1
                case _:
                    tasks["Download"] += 1

        msg = f"""㊂ <b>Tasks Overview</b> :
        
┎ <b>Download:</b> {tasks["Download"]} | <b>Upload:</b> {tasks["Upload"]}
┠ <b>Seed:</b> {tasks["Seed"]} | <b>Archive:</b> {tasks["Archive"]}
┠ <b>Extract:</b> {tasks["Extract"]} | <b>Split:</b> {tasks["Split"]}
┠ <b>QueueDL:</b> {tasks["QueueDl"]} | <b>QueueUP:</b> {tasks["QueueUp"]}
┠ <b>Clone:</b> {tasks["Clone"]} | <b>CheckUp:</b> {tasks["CheckUp"]}
┠ <b>Paused:</b> {tasks["Pause"]} | <b>SamVideo:</b> {tasks["SamVid"]}
┞ <b>Convert:</b> {tasks["ConvertMedia"]} | <b>FFmpeg:</b> {tasks["FFmpeg"]}
│
┟ <b>Total Download Speed:</b> {get_readable_file_size(dl_speed)}/s
┠ <b>Total Upload Speed:</b> {get_readable_file_size(up_speed)}/s
┖ <b>Total Seeding Speed:</b> {get_readable_file_size(seed_speed)}/s
<tg-button-row align="center">
  <tg-button type="callback_data" data="status {data[1]} ref" style="primary">Back to Status</tg-button>
</tg-button-row>
"""
        button = ButtonMaker()
        button.data_button("Back to Status", f"status {data[1]} ref", style=ButtonStyle.PRIMARY)
        await answer_callback_ephemeral(query, msg, button.build_menu(), replace=True, use_inside_buttons=True)
        return

    try:
        await query.answer()
    except QueryIdInvalid:
        pass
