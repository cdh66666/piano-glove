"""Optional conversion observation; no listener means no payload or side effect."""
from contextlib import contextmanager
import threading

_local=threading.local()

@contextmanager
def listen(callback):
    previous=getattr(_local,'listener',None)
    _local.listener=callback
    try:
        yield
    finally:
        if previous is None:
            try:del _local.listener
            except AttributeError:pass
        else:_local.listener=previous

def notify(stage,*,label=None,page_done=None,page_total=None):
    callback=getattr(_local,'listener',None)
    if callback is None:return False
    determinate=(stage=='recognizing' and type(page_total) is int and page_total>0
                 and type(page_done) is int and 0<=page_done<=page_total)
    payload=dict(stage=str(stage),label=str(label or stage),page_done=page_done if determinate else None,
                 page_total=page_total if determinate else None,determinate=bool(determinate))
    # The observer is deliberately unable to change a score or its exception.
    try:callback(payload)
    except Exception:return False
    return True
