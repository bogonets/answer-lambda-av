# -*- coding: utf-8 -*-

from functools import reduce
import sys
import numpy as np
import av


src = ''
video_index = 0
frame_format = 'bgr24'
options = {}
reopen = False

container = None
frames = None
last_frame = np.zeros((300, 300, 3), dtype=np.uint8)
last_pts = 0
last_index = 0


def print_error(message):
    sys.stderr.write(message)
    sys.stderr.flush()


def split_option(text: str, kv_split='='):
    i = text.find(kv_split)
    if i == -1:
        return None
    return text[0:i].strip(), text[i+1:].strip()


def str_to_dict(text: str, item_split=';', kv_split='='):
    items = [x for x in text.split(item_split)]
    items = list(filter(lambda x: x.strip(), items))
    result = {}
    for x in items:
        opt = split_option(x, kv_split)
        if opt:
            assert len(opt) == 2
            result[opt[0]] = opt[1]
    return result


def dict_to_str(items: dict, item_split=';', kv_split='='):
    return reduce(lambda x, y: x+item_split+y,
                  [str(k)+kv_split+str(v) for k, v in items.items()])


def is_opened_video():
    return container is not None


def close_video():
    global container
    global frames

    try:
        if container is not None:
            container.close()
    except Exception as e:
        print_error(e)

    container = None
    frames = None


def open_video():
    try:
        global src
        global video_index
        global options
        global container
        global frames
        container = av.open(src, options=options)
        container.streams.video[video_index].thread_type = 'AUTO'  # Go faster!
        frames = container.decode(video=video_index)
        return True
    except Exception as e:
        print_error(e)
        return False


def reopen_video():
    close_video()
    return open_video()


def on_set(key, val):
    if key == 'src':
        global src
        src = val
    elif key == 'video_index':
        global video_index
        video_index = int(val)
    elif key == 'frame_format':
        global frame_format
        frame_format = val
    elif key == 'options':
        global options
        options = str_to_dict(str(val))
    elif key == 'reopen':
        global reopen
        reopen = bool(val)


def on_get(key):
    if key == 'src':
        return src
    elif key == 'video_index':
        return str(video_index)
    elif key == 'frame_format':
        return frame_format
    elif key == 'options':
        return dict_to_str(options)
    elif key == 'reopen':
        return str(reopen)


def on_init():
    return reopen_video()


def on_valid():
    return is_opened_video()


def on_run():
    global frame_format
    global frames
    global last_frame
    global last_pts
    global last_index

    try:
        frame = next(frames)
        last_frame = frame.to_ndarray(format=frame_format)
        last_pts = frame.pts
        last_index = frame.index
    except Exception as e:
        print_error(e)
        if reopen:
            reopen_video()

    return {"frame": last_frame}


def on_destroy():
    close_video()


if __name__ == '__main__':
    pass
