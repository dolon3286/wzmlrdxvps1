from ...ext_utils.status_utils import MirrorStatus, get_readable_file_size


class M3u8dlStatus:
    def __init__(self, listener, obj, gid):
        self.listener = listener
        self._obj = obj
        self._gid = gid
        self.engine = "N_m3u8DL-RE"

    def gid(self):
        return self._gid

    def processed_bytes(self):
        return get_readable_file_size(self._obj.processed_bytes)

    def size(self):
        return get_readable_file_size(self.listener.size)

    def status(self):
        return MirrorStatus.STATUS_DOWNLOAD

    def name(self):
        return self.listener.name or "N_m3u8DL-RE"

    def progress(self):
        return f"{round(self._obj.progress, 2)}%"

    def speed(self):
        return f"{get_readable_file_size(self._obj.speed)}/s"

    def eta(self):
        return "-"

    def task(self):
        return self._obj
