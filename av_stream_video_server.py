# -*- coding: utf-8 -*-

import sys
import multiprocessing as mp
from multiprocessing.sharedctypes import Value
from queue import Full
import numpy as np
import time


EMPTY_ARRAY = np.zeros((300, 300, 3), dtype=np.uint8)
RECONNECT_SLEEP = 1.0
ENABLE_VERBOSE = False


def print_out(message):
    sys.stdout.write(message)
    sys.stdout.flush()


def print_error(message):
    sys.stderr.write(message)
    sys.stderr.flush()


class VideoServer:
    """
    """

    def __init__(self,
                 av_queue: mp.Queue,
                 av_exit: Value,
                 src: str,
                 video_index: int,
                 frame_format: str,
                 options: dict,
                 reopen: bool):
        self.av_queue = av_queue
        self.av_exit = av_exit

        self.src = src
        self.video_index = video_index
        self.frame_format = frame_format
        self.options = options
        self.reopen = reopen

        self.container = None
        self.frames = None

        self.last_frame = EMPTY_ARRAY
        self.last_pts = 0
        self.last_index = 0

        print_out(f'av.stream_video.VideoServer.__init__(src={src},video_index={video_index},format={frame_format},options={options},reopen={reopen})')
        print_out(f'av_exit is {self.av_exit}')

    def open_video(self):
        print_out('av.stream_video.VideoServer.open_video()')
        try:
            import av
            self.container = av.open(self.src, options=self.options)
            self.container.streams.video[self.video_index].thread_type = 'AUTO'  # Go faster!
            self.frames = self.container.decode(video=self.video_index)
            return True
        except Exception as e:
            print_error(e)
            return False

    def is_opened_video(self):
        return self.container is not None

    def close_video(self):
        print_out('av.stream_video.VideoServer.close_video()')
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
        self.last_pts = frame.pts
        self.last_index = frame.index

    def push_data(self, data):
        try:
            self.av_queue.put_nowait(data)
        except Full:
            self.av_queue.get_nowait()
            try:
                self.av_queue.put_nowait(data)
            except Full:
                print_error('av.stream_video.VideoServer.push_array() Queue is Full.')

    def run(self):
        print_out('av.stream_video.VideoServer.run() BEGIN.')
        if not self.is_opened_video():
            self.open_video()

        while not self.av_exit.value:
            # Read current frame.
            try:
                self.read_next_frame()
            except Exception as e:
                print_error(e)
                if self.reopen:
                    print_out('av.stream_video.VideoServer.run() ReOpen ...')
                    self.reopen_video()
                    time.sleep(RECONNECT_SLEEP)
                else:
                    break

            if ENABLE_VERBOSE:
                print_out(f'av.stream_video.VideoServer.run() Push(pts={self.last_pts},index={self.last_index},frame={self.last_frame.shape})')

            self.push_data(self.last_frame)

        self.close_video()
        print_out('av.stream_video.VideoServer.run() END.')


def on_runner(av_queue, av_exit, src, video_index, frame_format, options, reopen):
    print_out('av.stream_video.VideoServer BEGIN.')
    VideoServer(av_queue, av_exit, src, video_index, frame_format, options, reopen).run()
    print_out('av.stream_video.VideoServer END.')


# def test_default(test_video_source_url):
#     if not open_video_impl(test_video_source_url):
#         print_error('Video open error.')
#         exit(1)
#     import cv2
#     while on_run():
#         result = on_run()
#         cv2.imshow('preview', result['frame'])
#         if cv2.waitKey(1) & 0xFF == ord('q'):
#             break
#     cv2.destroyAllWindows()


if __name__ == '__main__':
    # test_default
    pass
