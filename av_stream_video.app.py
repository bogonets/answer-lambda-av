# -*- coding: utf-8 -*-

from functools import reduce

import sys
import time
import argparse
import psutil
# import numpy as np

from multiprocessing.sharedctypes import Value, Synchronized
from ctypes import c_bool, c_int
from multiprocessing import Process, Queue
from queue import Empty

import av_stream_video_server as vs


LOGGING_PREFIX = '[av.stream_video] '
LOGGING_SUFFIX = '\n'
UNKNOWN_PID = 0
DEFAULT_MAX_QUEUE_SIZE = 4
DEFAULT_VIDEO_FPS = 12


def print_out(message):
    sys.stdout.write(LOGGING_PREFIX + message + LOGGING_SUFFIX)
    sys.stdout.flush()


def print_error(message):
    sys.stderr.write(LOGGING_PREFIX + message + LOGGING_SUFFIX)
    sys.stderr.flush()


def kill_process(pid):
    if not psutil.pid_exists(pid):
        return

    parent = psutil.Process(pid)

    for child in parent.children(recursive=True):
        print_out(f'kill children: {child.pid}')
        child.kill()

    print_out(f'Force kill PID: {parent.pid}')
    parent.kill()


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


class InaccessibleException(AssertionError):
    pass


class IllegalStateException(ValueError):
    pass


class NotReadyException(ValueError):
    pass


class NullDataException(TypeError):
    pass


class StreamVideo:
    """
    """

    def __init__(self, *args, **kwargs):
        self.video_src: str = vs.opt_kwargs(kwargs, 'video_src', '')
        self.video_index: int = vs.opt_kwargs(kwargs, 'video_index', 0)
        self.frame_format: str = vs.opt_kwargs(kwargs, 'frame_format', vs.DEFAULT_FRAME_FORMAT)
        self.frame_width: int = vs.opt_kwargs(kwargs, 'frame_width', 0)
        self.frame_height: int = vs.opt_kwargs(kwargs, 'frame_height', 0)
        self.frame_interpolation: str = vs.opt_kwargs(kwargs, 'frame_interpolation', vs.INTERPOLATION_LIST[1])
        self.options: dict = vs.opt_kwargs(kwargs, 'options', {})
        self.container_options: dict = vs.opt_kwargs(kwargs, 'container_options', {})
        self.stream_options: list = vs.opt_kwargs(kwargs, 'stream_options', [])
        self.reconnect_sleep: float = vs.opt_kwargs(kwargs, 'reconnect_sleep', vs.RECONNECT_SLEEP)
        self.iteration_sleep: float = vs.opt_kwargs(kwargs, 'iteration_sleep', vs.ITERATION_SLEEP)
        self.verbose: bool = vs.opt_kwargs(kwargs, 'verbose', False)
        self.low_delay: bool = vs.opt_kwargs(kwargs, 'low_delay', False)
        self.refresh_error_threshold: int = vs.opt_kwargs(kwargs, 'refresh_error_threshold', vs.REFRESH_ERROR_THRESHOLD)

        self.max_queue_size: int = vs.opt_kwargs(kwargs, 'max_queue_size', DEFAULT_MAX_QUEUE_SIZE)
        self.exit_timeout_seconds: float = vs.opt_kwargs(kwargs, 'exit_timeout_seconds', vs.DEFAULT_EXIT_TIMEOUT_SECONDS)

        self.refresh_error_count = 0
        self.refresh_flag: Synchronized = Value(c_bool, False)

        self.process: Process = None  # noqa
        self.pid = UNKNOWN_PID

        self.server_state: Synchronized = Value(c_int, vs.SERVER_STATE_DONE)

        self.exit_flag: Synchronized = Value(c_bool, False)
        self.queue: Queue = None  # noqa
        self.last_image = None

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
            self.stream_options = list(filter(lambda x: x.strip(), str(val).split(',')))
        elif key == 'reconnect_sleep':
            self.reconnect_sleep = float(val)
        elif key == 'iteration_sleep':
            self.iteration_sleep = float(val)
        elif key == 'verbose':
            self.verbose = val.lower() in ['y', 'yes', 'true']
        elif key == 'low_delay':
            self.low_delay = val.lower() in ['y', 'yes', 'true']
        elif key == 'max_queue_size':
            self.max_queue_size = int(val)
        elif key == 'exit_timeout_seconds':
            self.exit_timeout_seconds = float(val)
        elif key == 'refresh_error_threshold':
            self.refresh_error_threshold = int(val)

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
        elif key == 'reconnect_sleep':
            return self.reconnect_sleep
        elif key == 'iteration_sleep':
            return self.iteration_sleep
        elif key == 'verbose':
            return str(self.verbose)
        elif key == 'low_delay':
            return str(self.low_delay)
        elif key == 'max_queue_size':
            return str(self.max_queue_size)
        elif key == 'exit_timeout_seconds':
            return str(self.exit_timeout_seconds)
        elif key == 'refresh_error_threshold':
            return str(self.refresh_error_threshold)

    def _get_server_state(self):
        with self.server_state.get_lock():
            return self.server_state.value

    def _set_server_state(self, value: int):
        with self.server_state.get_lock():
            self.server_state.value = value

    def _set_exit_flag(self, value: bool):
        with self.exit_flag.get_lock():
            self.exit_flag.value = value

    def _set_refresh_flag(self, value: bool):
        with self.refresh_flag.get_lock():
            self.refresh_flag.value = value

    def do_refresh_ok(self):
        self.refresh_error_count = 0
        self._set_refresh_flag(False)

    def do_refresh_error(self):
        if self.refresh_error_count < self.refresh_error_threshold:
            self.refresh_error_count += 1
            if self.verbose:
                print_out(f'StreamVideo.do_refresh_error({self.refresh_error_count}/{self.refresh_error_threshold})')
        else:
            self.refresh_error_count = 0
            self._set_refresh_flag(True)
            print_error(f'StreamVideo.do_refresh_error() Enable refresh_flag')

    def get_last_image(self):
        try:
            self.last_image = self.queue.get_nowait()
            self.do_refresh_ok()
        except Empty:
            self.do_refresh_error()
        return self.last_image

    def _create_process_impl(self):
        assert self.queue is None
        assert self.process is None

        kwargs = {
            'exit_flag': self.exit_flag,
            'server_state': self.server_state,
            'refresh_flag': self.refresh_flag,
            'video_src': self.video_src,
            'video_index': self.video_index,
            'frame_format': self.frame_format,
            'frame_width': self.frame_width,
            'frame_height': self.frame_height,
            'frame_interpolation': self.frame_interpolation,
            'options': self.options,
            'container_options': self.container_options,
            'stream_options': self.stream_options,
            'reconnect_sleep': self.reconnect_sleep,
            'iteration_sleep': self.iteration_sleep,
            'verbose': self.verbose,
            'low_delay': self.low_delay,
        }

        self.queue = Queue(self.max_queue_size)
        self.process = Process(target=vs.start_app, args=(self.queue,), kwargs=kwargs)

        self._set_server_state(vs.SERVER_STATE_OPENING)
        self.process.start()

        if self.process.is_alive():
            self.pid = self.process.pid
            print_out(f'StreamVideo._create_process_impl() Server process PID: {self.pid}')
            return True
        else:
            self._set_server_state(vs.SERVER_STATE_DONE)
            print_error(f'StreamVideo._create_process_impl() Server process is not alive.')
            return False

    def _create_process(self):
        try:
            return self._create_process_impl()
        except Exception as e:
            print_error(f'StreamVideo._create_process() Exception: {e}')
            return False

    def _close_process_impl(self):
        self._set_exit_flag(True)

        if self.process is not None:
            timeout = self.exit_timeout_seconds
            if self.process.is_alive():
                request_begin = time.time()
                print_out(f'StreamVideo._close_process_impl() RequestExit(timeout={timeout}s)')

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
            if self.process.is_alive():
                self.process.terminate()
            self.process.close()
            self.process = None

        if self.pid >= 1:
            kill_process(self.pid)
            self.pid = UNKNOWN_PID

        self._set_server_state(vs.SERVER_STATE_DONE)
        self._set_exit_flag(False)
        self._set_refresh_flag(False)

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

        state = self._get_server_state()
        if state == vs.SERVER_STATE_DONE:
            raise IllegalStateException
        elif state == vs.SERVER_STATE_OPENING:
            raise NotReadyException
        elif state == vs.SERVER_STATE_RUNNING:
            pass  # OK!!
        else:
            raise InaccessibleException

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


def main():
    parser = argparse.ArgumentParser(description='RealTimeVideo demo')
    parser.add_argument(
        '--url',
        default="rtsp://0.0.0.0:8554/live.sdp",
        help='RTSP URL.'),
    parser.add_argument(
        '--fps',
        type=int,
        default=DEFAULT_VIDEO_FPS,
        help=f'WebRTC Video FPS (default: {DEFAULT_VIDEO_FPS})')
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true')
    args = parser.parse_args()

    global LOGGING_SUFFIX
    LOGGING_SUFFIX = '\n'
    vs.LOGGING_SUFFIX = '\n'

    video = StreamVideo(video_src=args.url,
                        verbose=args.verbose)
    video.on_init()

    import cv2
    import time
    while True:
        try:
            result = video.on_run()
        except NotReadyException:
            # print_error(f"on_run() not ready exception.")
            continue
        except NullDataException:
            print_error(f"on_run() null data exception.")
            continue

        assert result is not None
        frame = result['frame']
        if frame is None:
            print_error("frame is empty.")
            continue

        cv2.imshow("Preview", frame)
        time.sleep(1.0/args.fps)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    video.on_destroy()


if __name__ == '__main__':
    main()
