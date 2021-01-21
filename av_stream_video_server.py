# -*- coding: utf-8 -*-

import sys
import traceback
import time
import numpy as np

from multiprocessing.sharedctypes import Value
from multiprocessing import Queue
from queue import Full, Empty

EMPTY_IMAGE = np.zeros((300, 300, 3), dtype=np.uint8)
DEFAULT_EXIT_TIMEOUT_SECONDS = 4.0
RECONNECT_SLEEP = 1.0
ITERATION_SLEEP = 0.001
REFRESH_ERROR_THRESHOLD = 100
DEFAULT_FRAME_FORMAT = 'bgr24'
INTERPOLATION_LIST = [
    'FAST_BILINEAR',
    'BILINEAR',
    'BICUBIC',
    'X',
    'POINT',
    'AREA',
    'BICUBLIN',
    'GAUSS',
    'SINC',
    'LANCZOS',
    'SPLINE'
]

LOGGING_PREFIX = '[av.stream_video.server] '
LOGGING_SUFFIX = '\n'


def print_out(message):
    sys.stdout.write(LOGGING_PREFIX + message + LOGGING_SUFFIX)
    sys.stdout.flush()


def print_error(message):
    sys.stderr.write(LOGGING_PREFIX + message + LOGGING_SUFFIX)
    sys.stderr.flush()


def opt_kwargs(kwargs, name, default_value=None):
    if name not in kwargs:
        return default_value
    return kwargs[name]


class StreamVideoServer:
    """
    """

    def __init__(self, *args, **kwargs):
        assert len(args) == 1
        self.queue: Queue = args[0]

        self.exit_flag: Value = opt_kwargs(kwargs, 'exit_flag')
        self.refresh_flag: Value = opt_kwargs(kwargs, 'refresh_flag')

        self.video_src: str = opt_kwargs(kwargs, 'video_src', '')
        self.video_index: int = opt_kwargs(kwargs, 'video_index', 0)
        self.frame_format: str = opt_kwargs(kwargs, 'frame_format', DEFAULT_FRAME_FORMAT)
        self.frame_width: int = opt_kwargs(kwargs, 'frame_width', 0)
        self.frame_height: int = opt_kwargs(kwargs, 'frame_height', 0)
        self.frame_interpolation: str = opt_kwargs(kwargs, 'frame_interpolation', INTERPOLATION_LIST[1])
        self.options: dict = opt_kwargs(kwargs, 'options', {})
        self.container_options: dict = opt_kwargs(kwargs, 'container_options', {})
        self.stream_options: list = opt_kwargs(kwargs, 'stream_options', [])
        self.reconnect_sleep: float = opt_kwargs(kwargs, 'reconnect_sleep', RECONNECT_SLEEP)
        self.iteration_sleep: float = opt_kwargs(kwargs, 'iteration_sleep', ITERATION_SLEEP)
        self.verbose: bool = opt_kwargs(kwargs, 'verbose', False)
        self.low_delay: bool = opt_kwargs(kwargs, 'low_delay', False)

        self.container = None
        self.frames = None

        self.last_frame = EMPTY_IMAGE
        self.last_index = 0
        self.last_pts = 0

        assert self.frame_width >= 0
        assert self.frame_height >= 0
        assert self.frame_interpolation in INTERPOLATION_LIST

        if self.verbose:
            print_out(f' - video_src: {self.video_src}')
            print_out(f' - video_index: {self.video_index}')
            print_out(f' - frame_format: {self.frame_format}')
            print_out(f' - frame_width: {self.frame_width}')
            print_out(f' - frame_height: {self.frame_height}')
            print_out(f' - frame_interpolation: {self.frame_interpolation}')
            print_out(f' - options: {self.options}')
            print_out(f' - container_options: {self.container_options}')
            print_out(f' - stream_options: {self.stream_options}')
            print_out(f' - reconnect_sleep: {self.reconnect_sleep}')
            print_out(f' - iteration_sleep: {self.iteration_sleep}')
            print_out(f' - verbose: {self.verbose}')
            print_out(f' - low_delay: {self.low_delay}')

        print_out(f'StreamVideoServer() constructor done')

    def open_video(self):
        print_out(f'StreamVideoServer.open_video(src={self.video_src},index={self.video_index})')
        try:
            import av
            self.container = av.open(self.video_src,
                                     options=self.options,
                                     container_options=self.container_options,
                                     stream_options=self.stream_options)
            self.container.streams.video[self.video_index].thread_type = 'AUTO'  # Go faster!
            if self.low_delay:
                self.container.streams.video[self.video_index].codec_context.flags = 'LOW_DELAY'
            self.frames = self.container.decode(video=self.video_index)
            if self.verbose:
                print_out(f'StreamVideoServer.open_video() Video open success!')
            return True
        except Exception as e:
            print_error(f'StreamVideoServer.open_video() Exception: {e}')
            return False

    def is_opened_video(self):
        return self.container is not None

    def close_video(self):
        print_out('av.stream_video.StreamVideoServer.close_video()')
        try:
            if self.container is not None:
                self.container.close()
        except Exception as e:
            print_error(e)

        self.container = None
        self.frames = None

    def reopen_video(self):
        self.close_video()
        return self.open_video()

    def read_next_frame(self):
        frame = next(self.frames)
        self.last_frame = frame.to_ndarray(width=self.frame_width,
                                           height=self.frame_height,
                                           format=self.frame_format,
                                           interpolation=self.frame_interpolation)
        self.last_index = frame.index
        self.last_pts = frame.pts

    def _put_nowait(self, data):
        try:
            self.queue.put_nowait(data)
            return True
        except Full:
            return False

    def _get_nowait(self):
        try:
            self.queue.get_nowait()
        except Empty:
            pass

    def push(self, data):
        if self._put_nowait(data):
            return True
        self._get_nowait()
        return self._put_nowait(data)

    def run(self):
        print_out('StreamVideoServer.run() BEGIN.')
        if not self.is_opened_video():
            self.open_video()

        while not self.exit_flag.value:

            if self.refresh_flag:
                print_out(f'StreamVideoServer.run() [REFRESH] -> Flag is is enabled.')
                reconnect_result = self.reopen_video()
                if reconnect_result:
                    print_out(f'StreamVideoServer.run() [REFRESH] -> reconnect success.')
                else:
                    print_error(f'StreamVideoServer.run() [REFRESH] -> reconnect failure.')
                self.refresh_flag = False

            # Read current frame.
            try:
                self.read_next_frame()
            except Exception as e:
                print_error(e)
                if self.verbose:
                    print_out(f'StreamVideoServer.run() reconnect sleep: {self.reconnect_sleep}s ...')
                if self.reconnect_sleep > 0:
                    time.sleep(self.reconnect_sleep)

                reconnect_result = self.reopen_video()
                if reconnect_result:
                    print_out(f'StreamVideoServer.run() reconnect success.')
                else:
                    print_error(f'StreamVideoServer.run() reconnect failure.')

            if self.verbose:
                args_text = f'index={self.last_index},pts={self.last_pts},frame={self.last_frame.shape}'
                print_out(f'StreamVideoServer.run() Push({args_text})')

            self.push(self.last_frame)
            if self.iteration_sleep > 0:
                time.sleep(self.iteration_sleep)

        self.close_video()
        print_out('StreamVideoServer.run() END.')


def start_app(*args, **kwargs):
    print_out(f'start_app() BEGIN')
    try:
        server = StreamVideoServer(*args, **kwargs)
        server.run()
    except StopIteration:
        print_error('StopIteration.')
    except Exception as e:
        print_error(f'Exception: {e}')
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
    finally:
        print_out(f'start_app() END')


if __name__ == '__main__':
    pass
