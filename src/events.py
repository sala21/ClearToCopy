import queue


class EventBus:
    """
    Canale thread-safe a bassa invasività tra la pipeline audio e la GUI.
    """

    def __init__(self):
        self._q = queue.Queue()

    def emit(self, kind, **data):
        self._q.put((kind, data))

    def poll_all(self):
        events = []
        while True:
            try:
                events.append(self._q.get_nowait())
            except queue.Empty:
                break
        return events