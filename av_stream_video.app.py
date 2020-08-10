# -*- coding: utf-8 -*-

from functools import reduce

import sys
import time
import argparse
import psutil
import numpy as np

from multiprocessing.sharedctypes import Value
from ctypes import c_bool
from multiprocessing import Process, Queue
from queue import Full, Empty

import av_stream_video_server as vs


LOGGING_PREFIX = '[av.stream_video] '
LOGGING_SUFFIX = '\n'
UNKNOWN_PID = 0
DEFAULT_MAX_QUEUE_SIZE = 4


def print_out(message):
    sys.stdout.write(LOGGING_PREFIX + message + LOGGING_SUFFIX)
    sys.stdout.flush()


def print_error(message):
    sys.stderr.write(LOGGING_PREFIX + message + LOGGING_SUFFIX)
    sys.stderr.flush()


def split_option(text: str, kv_split='='):
    i = text.find(kv_split)
    if i == -1:
        return None
    return text[0:i].strip(), text[i+1:].strip()


def str_to_dict(text: str, item_split=',', kv_split='='):
    items = [x for x in text.split(item_split)]
    items = list(filter(lambda x: x.strip(), items))
    result = {}
    for x in items:
        opt = split_option(x, kv_split)
        if opt:
            assert len(opt) == 2
            result[opt[0]] = opt[1]
    return result


def dict_to_str(items: dict, item_split=',', kv_split='='):
    return reduce(lambda x, y: x+item_split+y,
                  [str(k)+kv_split+str(v) for k, v in items.items()])


class CreateProcessError(Exception):
    pass


class NullDataException(TypeError):
    pass


class StreamVideo:
    """
    """

    def __init__(self,
                 video_src='',
                 video_index=0,
                 frame_format=vs.DEFAULT_FRAME_FORMAT,
                 frame_width=0,
                 frame_height=0,
                 frame_interpolation=vs.INTERPOLATION_LIST[1],
                 options={},
                 container_options={},
                 stream_options=[],
                 reconnect_sleep=vs.RECONNECT_SLEEP,
                 max_queue_size=DEFAULT_MAX_QUEUE_SIZE,
                 exit_timeout_seconds=vs.DEFAULT_EXIT_TIMEOUT_SECONDS,
                 verbose=False,
                 low_delay=False):
        self.video_src = video_src
        self.video_index = video_index
        self.frame_format = frame_format
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.frame_interpolation = frame_interpolation
        self.options = options
        self.container_options = container_options
        self.stream_options = stream_options
        self.reconnect_sleep = reconnect_sleep
        self.iteration_sleep = vs.ITERATION_SLEEP
        self.max_queue_size = max_queue_size
        self.exit_timeout_seconds = exit_timeout_seconds
        self.verbose = verbose
        self.low_delay = low_delay

        self.last_image = None
        self.exit_flag = Value(c_bool, False)
        self.process: Process = None
        self.queue: Queue = None
        self.pid = UNKNOWN_PID

    def on_set(self, key, val):
        if key == 'video_src':
            self.video_src = val
        elif key == 'video_index':
            self.video_index = int(val)
        elif key == 'frame_format':
            self.frame_format = val
        elif key == 'frame_width':
            self.frame_width = int(val)
        elif key == 'frame_height':
            self.frame_height = int(val)
        elif key == 'frame_interpolation':
            self.frame_interpolation = val
        elif key == 'options':
            self.options = str_to_dict(str(val))
        elif key == 'container_options':
            self.container_options = str_to_dict(str(val))
        elif key == 'stream_options':
            self.stream_options = list(map(lambda x: x, str(val).split(',')))
        elif key == 'max_queue_size':
            self.max_queue_size = int(val)
        elif key == 'exit_timeout_seconds':
            self.exit_timeout_seconds = float(val)
        elif key == 'verbose':
            self.verbose = val.lower() in ['y', 'yes', 'true']
        elif key == 'low_delay':
            self.low_delay = val.lower() in ['y', 'yes', 'true']

    def on_get(self, key):
        if key == 'video_src':
            return self.video_src
        elif key == 'video_index':
            return str(self.video_index)
        elif key == 'frame_format':
            return self.frame_format
        elif key == 'frame_width':
            return self.frame_width
        elif key == 'frame_height':
            return self.frame_height
        elif key == 'frame_interpolation':
            return self.frame_interpolation
        elif key == 'options':
            return dict_to_str(self.options)
        elif key == 'container_options':
            return dict_to_str(self.container_options)
        elif key == 'stream_options':
            return ','.join(list(map(lambda x: str(x), self.stream_options)))
        elif key == 'max_queue_size':
            return str(self.max_queue_size)
        elif key == 'exit_timeout_seconds':
            return str(self.exit_timeout_seconds)
        elif key == 'verbose':
            return str(self.verbose)
        elif key == 'low_delay':
            return str(self.low_delay)

    def get_last_image(self):
        try:
            self.last_image = self.queue.get_nowait()
        except Empty:
            pass
        return self.last_image

    def _create_process_impl(self):
        assert self.queue is None
        assert self.process is None

        self.queue = Queue(self.max_queue_size)
        self.process = Process(target=vs.start_app,
                               args=(self.queue, self.exit_flag, self.video_src, self.video_index,
                                     self.frame_format, self.frame_width, self.frame_height,
                                     self.frame_interpolation, self.options,
                                     self.container_options, self.stream_options,
                                     self.reconnect_sleep, self.iteration_sleep,
                                     self.verbose, self.low_delay,))

        self.process.start()
        if self.process.is_alive():
            self.pid = self.process.pid
            print_out(f'StreamVideo._create_process_impl() Server process PID: {self.pid}')
            return True
        else:
            print_error(f'StreamVideo._create_process_impl() Server process is not alive.')
            return False

    def _create_process(self):
        try:
            return self._create_process_impl()
        except Exception as e:
            print_error(f'StreamVideo._create_process() Exception: {e}')
            return False

    def _close_process_impl(self):
        if self.process is not None:
            timeout = self.exit_timeout_seconds
            if self.process.is_alive():
                request_begin = time.time()
                print_out(f'StreamVideo._close_process_impl() RequestExit(timeout={timeout}s)')
                self.exit_flag = True
                timeout = timeout - (time.time() - request_begin)
                timeout = timeout if timeout >= 0.0 else 0.0

            print_out(f'StreamVideo._close_process_impl() Join(timeout={timeout}s) the sub-process.')
            self.process.join(timeout=timeout)

            if self.process.is_alive():
                print_error(f'StreamVideo._close_process_impl() Send a KILL signal to the server process.')
                self.process.kill()

        # A negative value -N indicates that the child was terminated by signal N.
        print_out(f'StreamVideo._close_process_impl() The exit code of sub-process is {self.process.exitcode}.')

        if self.queue is not None:
            self.queue.close()
            self.queue.cancel_join_thread()
            self.queue = None

        if self.process is not None:
            self.process.close()
            self.process = None

        if self.pid >= 1:
            if psutil.pid_exists(self.pid):
                print_out(f'Force kill PID: {self.pid}')
                psutil.Process(self.pid).kill()
            self.pid = UNKNOWN_PID

        assert self.queue is None
        assert self.process is None
        assert self.pid is UNKNOWN_PID
        print_out(f'StreamVideo._close_process_impl() Done.')

    def _close_process(self):
        try:
            self._close_process_impl()
        except Exception as e:
            print_error(f'StreamVideo._close_process() Exception: {e}')
        finally:
            self.queue = None
            self.process = None
            self.pid = UNKNOWN_PID

    def create_process(self):
        if self._create_process():
            return True
        self._close_process()
        return False

    def is_reopen(self):
        if self.process is None:
            return True
        if not self.process.is_alive():
            return True
        return False

    def reopen(self):
        self._close_process()
        if self._create_process():
            print_out(f'Recreated Server process PID: {self.pid}')
        else:
            raise CreateProcessError

    def on_init(self):
        return self.create_process()

    def on_valid(self):
        return self.pid != UNKNOWN_PID

    def on_run(self):
        if self.is_reopen():
            self.reopen()

        frame = self.get_last_image()
        if frame is None:
            raise NullDataException

        return {'frame': frame}

    def on_destroy(self):
        self._close_process()


MAIN_HANDLER = StreamVideo()


def on_set(key, val):
    MAIN_HANDLER.on_set(key, val)


def on_get(key):
    return MAIN_HANDLER.on_get(key)


def on_init():
    return MAIN_HANDLER.on_init()


def on_valid():
    return MAIN_HANDLER.on_valid()


def on_run():
    return MAIN_HANDLER.on_run()


def on_destroy():
    return MAIN_HANDLER.on_destroy()


if __name__ == '__main__':
    pass
