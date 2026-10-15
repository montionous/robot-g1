"""Open bounded owner artifacts without following any symlink component."""
import os
import stat
from pathlib import Path

MIME = {'.wav':'audio/wav','.mp3':'audio/mpeg','.m4a':'audio/mp4','.mp4':'video/mp4','.webm':'video/webm'}
MAX_BYTES = 100 * 1024 * 1024


def open_attachment(raw_path, source_path, roots, kind):
    if not isinstance(raw_path,str) or not raw_path or len(raw_path)>2048:
        raise ValueError('上游未提供有效附件路径')
    path = Path(raw_path)
    if not path.is_absolute():path = Path(source_path).parent/path
    if '..' in path.parts:
        raise ValueError('附件路径包含越界分量')
    path=path.absolute()
    mime=MIME.get(path.suffix.lower())
    if not mime or not mime.startswith(kind+'/'):
        raise ValueError('附件类型不符合音视频合同')
    root=next((Path(root).resolve() for root in roots if path.is_relative_to(Path(root).resolve())),None)
    if root is None:
        raise ValueError('附件不在允许的模块目录内')
    parts=path.relative_to(root).parts
    parent=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    handle=None
    try:
        for part in parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            os.close(parent);parent=child
        descriptor=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        handle=os.fdopen(descriptor,'rb')
        info=os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
            raise ValueError('附件不是有界普通文件，或超过 100 MiB')
        return handle,info.st_size,mime
    except BaseException:
        if handle is not None:handle.close()
        raise
    finally:
        os.close(parent)
