# -*- coding: utf-8 -*-

import sys
import time
import numpy as np

from multiprocessing.sharedctypes import Value
from multiprocessing import Queue
from queue import Full, Empty

EMPTY_IMAGE = np.zeros((300, 300, 3), dtype=np.uint8)
DEFAULT_EXIT_TIMEOUT_SECONDS = 4.0
RECONNECT_SLEEP = 1.0
DEFAULT_FRAME_FORMAT = 'bgr24'
LOGGING_PREFIX = '[av.stream_video.server] '
LOGGING_SUFFIX = '\n'


def print_out(message):
    sys.stdout.write(LOGGING_PREFIX + message + LOGGING_SUFFIX)
    sys.stdout.flush()


def print_error(message):
    sys.stderr.write(LOGGING_PREFIX + message + LOGGING_SUFFIX)
    sys.stderr.flush()


class StreamVideoServer:
    """
    """

    def __init__(self,
                 queue: Queue,
                 exit_flag: Value,
                 video_src='',
                 video_index=0,
                 frame_format=DEFAULT_FRAME_FORMAT,
                 options={},
                 container_options={},
                 stream_options=[],
                 reconnect_sleep=RECONNECT_SLEEP,
                 verbose=False):
        self.queue = queue
        self.exit_flag = exit_flag

        self.video_src = video_src
        self.video_index = video_index
        self.frame_format = frame_format
        self.options = options
        self.container_options = container_options
        self.stream_options = stream_options
        self.reconnect_sleep = reconnect_sleep
        self.verbose = verbose

        self.container = None
        self.frames = None

        self.last_frame = EMPTY_IMAGE
        self.last_index = 0
        self.last_pts = 0

        print_out(f'StreamVideoServer() constructor done')
        if self.verbose:
            print_out(f' - options: {self.options}')
            print_out(f' - container_options: {self.container_options}')
            print_out(f' - stream_options: {self.stream_options}')

    def open_video(self):
        print_out('StreamVideoServer.open_video()')
        try:
            import av
            self.container = av.open(self.video_src, options=self.options,
                                     container_options=self.container_options,
                                     stream_options=self.stream_options)
            self.container.streams.video[self.video_index].thread_type = 'AUTO'  # Go faster!
            self.frames = self.container.decode(video=self.video_index)
            return True
        except Exception as e:
            print_error(e)
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
        self.last_frame = frame.to_ndarray(format=self.frame_format)
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
            # Read current frame.
            try:
                self.read_next_frame()
            except Exception as e:
                print_error(e)
                if self.verbose:
                    print_out(f'StreamVideoServer.run() reconnect sleep: {self.reconnect_sleep}s ...')
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

        self.close_video()
        print_out('StreamVideoServer.run() END.')


def start_app(queue, exit_flag, video_src, video_index, frame_format,
              options, container_options, stream_options, reconnect_sleep, verbose):
    args_text = 'src={},index={},format={},verbose={}'.format(
        video_src, video_index, frame_format, verbose)
    print_out(f'start_app({args_text}) BEGIN')

    try:
        server = StreamVideoServer(queue, exit_flag, video_src, video_index, frame_format,
                                   options, container_options, stream_options, reconnect_sleep,
                                   verbose)
        server.run()
    except Exception as e:
        print_error(f'StreamVideoServer Exception: {e}')
    finally:
        print_out(f'start_app() END')


if __name__ == '__main__':
    pass
