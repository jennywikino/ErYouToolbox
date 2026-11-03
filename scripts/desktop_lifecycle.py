"""Non-blocking GUI close; cancel scans, drain writes, stop HTTP, then close GUI."""
import faulthandler
import logging
import threading
import time

from backfill_content_ratings import instance_lock


class DesktopLifecycle:
    def __init__(self, server, api, closing, http_thread, root, *, wait_seconds=45, trace=None):
        self.server,self.api,self.closing,self.http_thread,self.root=server,api,closing,http_thread,root
        self.wait_seconds,self.trace=wait_seconds,trace
        self.ready=threading.Event()
        self.guard=threading.Lock()
        self.worker=None
        self.window=None
        self.smoke_worker=None
        self.started=0
        self.services_stopped=False

    def log(self, stage, **fields):
        logging.info('shutdown stage=%s elapsed=%.3fs %s',stage,time.monotonic()-self.started if self.started else 0,fields)

    def active(self):
        def live(service):
            worker=getattr(service,'worker',None)
            return bool(worker and worker.is_alive())
        return {'web':self.api.web_sync.worker_active or live(self.api.web_sync),
                'auto':self.api.auto_sync.running.locked() or live(self.api.auto_sync),
                'history':self.api.history_sync.running.locked() or live(self.api.history_sync),
                'smoke':bool(self.smoke_worker and self.smoke_worker.is_alive())}

    def cancel(self):
        # In-memory signals only. Do not overwrite saved auto/history preferences.
        self.api.web_sync.cancel.set()
        self.api.auto_sync.cancel.set()
        service=self.api.auto_sync.current_service
        if service:service.cancel.set()
        self.api.history_sync.cancel.set()

    def before_close(self):
        self.log('GUI_close_requested',active=self.active())
        if self.ready.is_set():return True
        with self.guard:
            if self.worker and self.worker.is_alive():return False
            self.started=time.monotonic()
            self.closing.set()  # Reject new writes before any blocking work.
            self.worker=threading.Thread(target=self._close,name='desktop-shutdown',daemon=False)
            self.worker.start()
        return False  # GUI event must return immediately; no lock/network/SQLite wait.

    def status(self, text):
        if self.window and hasattr(self.window,'native'):
            try:
                from System import Action
                self.window.native.BeginInvoke(Action(lambda:setattr(self.window.native,'Text',text)))
            except Exception:logging.exception('shutdown status update failed')

    def wait_quiet(self):
        deadline=time.monotonic()+self.wait_seconds
        next_report=0
        while True:
            self.cancel()  # Also catches a previously queued launch that has just begun.
            busy=self.active()
            if not any(busy.values()) and self.server.lifecycle_lock.acquire(timeout=.1):
                try:
                    if not any(self.active().values()):
                        try:
                            with instance_lock(self.root/'logs/content_ratings/instance.lock'):pass
                            self.log('workers_and_writes_drained')
                            return True
                        except RuntimeError:busy['shared_lock']=True
                finally:self.server.lifecycle_lock.release()
            now=time.monotonic()
            if now>=next_report:
                self.log('waiting_safe_boundary',active=busy)
                if self.trace:faulthandler.dump_traceback(file=self.trace,all_threads=True)
                next_report=now+5
            if now>=deadline:
                self.log('wait_timeout_no_transaction_interrupted',active=busy)
                return False
            time.sleep(.05)

    def stop_http(self):
        if self.services_stopped:return
        # This runs off serve_forever and off the GUI thread, without lifecycle_lock.
        self.log('HTTP_shutdown_begin')
        self.server.shutdown()
        self.log('HTTP_serve_forever_stopped')
        self.server.server_close()  # Joins non-daemon request handlers; sockets have a timeout.
        self.http_thread.join(timeout=5)
        if self.http_thread.is_alive():raise RuntimeError('HTTP serve_forever did not exit')
        self.services_stopped=True
        self.log('HTTP_closed_port_released')

    def _close(self):
        try:
            self.status('妙妙二玩箱 · 正在安全关闭，请等待任务完成…')
            self.cancel();self.log('cancellation_sent',active=self.active())
            if not self.wait_quiet():
                self.closing.clear()
                self.status('妙妙二玩箱 · 任务尚未结束，请稍后再次关闭')
                return
            self.stop_http()
            self.ready.set()
            self.log('destroy_window_begin')
            self.window.destroy()
            self.log('destroy_window_returned')
        except Exception:
            logging.exception('shutdown coordinator failed; no forced process exit')
            self.status('妙妙二玩箱 · 关闭失败，请查看日志')
            if not self.services_stopped:self.closing.clear()

    def finish(self):
        """Main thread cleanup after GUI returns or an early startup failure."""
        if self.worker:
            self.worker.join(timeout=self.wait_seconds+10)
            if self.worker.is_alive():raise RuntimeError('Shutdown worker still active; see shutdown-threads.log')
        if not self.services_stopped:
            self.closing.set()
            if not self.wait_quiet():raise RuntimeError('Tasks still active; no unsafe transaction interruption performed')
            self.stop_http()
        self.log('main_cleanup_complete',threads=[t.name for t in threading.enumerate()])
