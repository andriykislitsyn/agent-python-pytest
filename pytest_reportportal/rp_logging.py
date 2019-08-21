import logging
import sys
from contextlib import contextmanager
from functools import wraps


# noinspection PyProtectedMember
class RPLogger(logging.getLoggerClass()):
    def __init__(self, name, level=0):
        super(RPLogger, self).__init__(name, level=level)

    def _log(self, level, msg, args, exc_info=None, extra=None, attachment=None):
        """
        Low-level logging routine which creates a LogRecord and then calls
        all the handlers of this logger to handle the record.
        """
        sinfo = None
        fn, lno, func = '(unknown file)', 0, '(unknown function)'
        if exc_info and not isinstance(exc_info, tuple):
            exc_info = sys.exc_info()

        record = self.makeRecord(self.name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)
        record.attachment = attachment
        self.handle(record)


class RPLogHandler(logging.Handler):
    # Map loglevel codes from `logging` module to ReportPortal text names:
    _loglevel_map = {
        logging.NOTSET: 'TRACE',
        logging.DEBUG: 'DEBUG',
        logging.INFO: 'INFO',
        logging.WARNING: 'WARN',
        logging.ERROR: 'ERROR',
        logging.CRITICAL: 'ERROR',
    }
    _sorted_levelnos = sorted(_loglevel_map.keys(), reverse=True)

    def __init__(self, py_test_service, level=logging.NOTSET, filter_reportportal_client_logs=False, endpoint=None):
        super(RPLogHandler, self).__init__(level)
        self.py_test_service = py_test_service
        self.filter_reportportal_client_logs = filter_reportportal_client_logs
        self.ignored_record_names = ('reportportal_client', 'pytest_reportportal')
        self.endpoint = endpoint

    def filter(self, record):
        if self.filter_reportportal_client_logs is False:
            return True
        if record.name.startswith(self.ignored_record_names):
            return False
        if record.name == 'urllib3.connectionpool':
            # Filter the reportportal_client requests instance urllib3 usage.
            if self.endpoint in self.format(record):
                return False
        return True

    # noinspection PyBroadException
    def emit(self, record):
        msg = ''
        try:
            msg = self.format(record)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            self.handleError(record)

        for level in self._sorted_levelnos:
            if level <= record.levelno:
                return self.py_test_service.post_log(
                    msg,
                    loglevel=self._loglevel_map[level],
                    attachment=record.__dict__.get('attachment', None),
                )


# noinspection PyProtectedMember
@contextmanager
def patching_logger_class():
    logger_class = logging.getLoggerClass()
    original_log = logger_class._log
    original_make_record = logger_class.makeRecord

    try:
        def wrap_log(original_func):
            @wraps(original_func)
            def _log(self, *args, **kwargs):
                attachment = kwargs.pop('attachment', None)
                if attachment is not None:
                    kwargs.setdefault('extra', {}).update(
                        {'attachment': attachment})
                return original_func(self, *args, **kwargs)

            return _log

        def wrap_make_record(original_func):
            @wraps(original_func)
            def make_record(self, name, level, fn, lno, msg, args, exc_info,
                            func=None, extra=None, sinfo=None):
                attachment = extra.pop('attachment', None) if extra else None
                record = original_func(self, name, level, fn, lno, msg, args, exc_info,
                                       func=func, extra=extra, sinfo=sinfo)
                record.attachment = attachment
                return record

            return make_record

        if not logger_class == RPLogger and not hasattr(logger_class, "_patched"):
            logger_class._log = wrap_log(logger_class._log)
            logger_class.makeRecord = wrap_make_record(logger_class.makeRecord)
            logger_class._patched = True
        yield

    finally:
        logger_class._log = original_log
        logger_class.makeRecord = original_make_record
