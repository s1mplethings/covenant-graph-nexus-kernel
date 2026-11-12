import threading
HANDLERS={}
lock=threading.Lock()
def handle(folder, request):
    with lock:
        return HANDLERS[request['milestone']](folder, request)
