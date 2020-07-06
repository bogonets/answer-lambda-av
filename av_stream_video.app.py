# -*- coding: utf-8 -*-

from functools import reduce

import sys
import multiprocessing as mp
from multiprocessing.sharedctypes import Value
from ctypes import c_bool
import numpy as np
from queue import Empty

import av_stream_video_server


DEFAULT_MAX_QUEUE_SIZE = 4
DEFAULT_EXIT_TIMEOUT_SECONDS = 4.0

src = ''
video_index = 0
frame_format = 'bgr24'
options = {}
reopen = False
max_queue_size = DEFAULT_MAX_QUEUE_SIZE
exit_timeout_seconds = DEFAULT_EXIT_TIMEOUT_SECONDS


def print_out(message):
    sys.stdout.write(message)
    sys.stdout.flush()


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
    elif key == 'max_queue_size':
        global max_queue_size
        max_queue_size = int(val)
    elif key == 'exit_timeout_seconds':
        global exit_timeout_seconds
        exit_timeout_seconds = float(val)


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
    elif key == 'max_queue_size':
        return str(max_queue_size)
    elif key == 'exit_timeout_seconds':
        return str(exit_timeout_seconds)


EMPTY_ARRAY = np.zeros((300, 300, 3), dtype=np.uint8)
av_process: mp.Process
av_queue: mp.Queue
av_exit: Value
av_last_data = EMPTY_ARRAY


def run_process():
    global max_queue_size
    queue_size = max_queue_size if max_queue_size > 0 else DEFAULT_MAX_QUEUE_SIZE

    global av_process, av_queue, av_exit
    global src, video_index, frame_format, options, reopen

    av_queue = mp.Queue(queue_size)
    av_exit = Value(c_bool, False)
    av_process = mp.Process(target=av_stream_video_server.on_runner,
                            args=(av_queue, av_exit, src, video_index, frame_format, options, reopen,))
    av_process.start()

    print_out(f'av.stream_video process PID is {av_process.pid}.')
    return av_process.is_alive()


def close_process():
    global av_exit
    av_exit = True

    global exit_timeout_seconds
    timeout = exit_timeout_seconds if exit_timeout_seconds > 0.0 else DEFAULT_EXIT_TIMEOUT_SECONDS

    global av_process
    print_out(f'av.stream_video(pid={av_process.pid}) Join(timeout={timeout}s) ...')
    av_process.join(timeout=timeout)

    global av_queue
    av_queue.close()
    av_queue.cancel_join_thread()
    av_queue = None

    if av_process.is_alive():
        print_error(f'av.stream_video(pid={av_process.pid}) Kill ...')
        av_process.kill()

    # A negative value -N indicates that the child was terminated by signal N.
    print_out(f'av.stream_video(pid={av_process.pid}) Exit Code: {av_process.exitcode}')

    av_process.close()
    av_process = None


def pop_array():
    global av_queue, av_last_data
    try:
        data = av_queue.get_nowait()
    except Empty:
        data = None

    if data is not None:
        av_last_data = data

    return av_last_data


def on_init():
    return run_process()


def on_valid():
    global av_process
    return av_process.is_alive()


def on_run():
    return {'frame': pop_array()}


def on_destroy():
    close_process()


if __name__ == '__main__':
    # test_default()
    pass
