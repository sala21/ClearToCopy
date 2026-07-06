import queue


class EventBus:
    """
    Canale thread-safe a bassa invasività tra la pipeline audio (thread di
    background) e la GUI (thread principale Tkinter).

    La pipeline chiama solo 'emit' (equivalente a un log strutturato); non
    ha nessuna dipendenza dalla GUI. Se 'event_bus' è None ovunque nella
    pipeline, il comportamento è identico a prima: zero overhead in modalità
    CLI pura.

    La GUI chiama 'poll_all' periodicamente (es. ogni 100ms via
    root.after()) SOLO dal thread principale, e aggiorna i widget con i
    dati ricevuti. Questo rispetta la regola di Tkinter: i widget si
    toccano solo dal thread main; la coda stessa è thread-safe per il
    passaggio dei dati da un thread all'altro.
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