# Copyright (c) 2014 Stefan C. Mueller

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, 
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER 
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING 
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

import functools
import threading
import time
import signal
import sys

from twisted.trial.util import _Janitor, DirtyReactorAggregateError
from twisted.internet import reactor, defer, task, threads
from twisted.python.failure import Failure

defer.setDebugging(True)

def with_reactor(*dec_args, **dec_kwargs):
    """
    Decorator for test functions that require a running reactor.
    
    Can be used like this::
    
       @with_reactor
       def test_connect_to_server(self):
          ...
          
    Or like this::
    
       @with_reactor(timeout=10)
       def test_connect_to_server(self):
          ...
          
    If the test function returns a deferred then the test will
    be successful if the deferred resolves to a value or unsuccessful
    if the deferred errbacks.
    
    The test must not leave any connections or a like open. This will
    otherwise result in a reactor-unclean failure of the test.
    
    If there is a function called `twisted_setup()` in the same class
    as the test function is defined, then this function will be invoked
    before the test, but already in the context of the reactor. Note that
    the regular setup function provided by the testing framework will
    be executed too, but not in the reactor context.
    
    Accordingly, if there is a `twisted_teardown()` it executes after the
    test function, even if the test failed. 
    
    If the test, including `twisted_setup` and `twisted_teardown`, has
    not completed within the timout, the test fails. The timeout defaults
    to two minutes. A timeout duration of zero disables the timeout.
    """
    
    # This method takes care of the decorator protocol, it
    # distinguishes between using the decorator with brackets
    # and without brackets. It then calls `_twisted_test_sync()`.

    if len(dec_args) == 1 and callable(dec_args[0]) and not dec_kwargs:
        # decorator used without brackets:
        #   @twisted_test
        #   def test_xxx():
        #     ....
        callee = dec_args[0]
        dec_args = ()
        dec_kwargs = {}
        
        @functools.wraps(callee)
        def wrapper(*call_args, **call_kwargs):
            return _twisted_test_sync(callee, call_args, call_kwargs)
        return wrapper

    else:
        # decorator used with brackets:
        #   @twisted_test(*dec_args, **dec_args)
        #   def test_xxx():
        #     ....
        def decorator(callee):
            @functools.wraps(callee)
            def wrapper(*call_args, **call_kwargs):
                return _twisted_test_sync(callee, call_args, call_kwargs, *dec_args, **dec_kwargs)
            return wrapper
        return decorator


def _twisted_test_sync(callee, call_args, call_kwargs, timeout=120):
    """
    Called from the main-thread upon invocation of a method 
    decorated with `@twisted_test`.
    Starts the reactor and performs the test in the reactor's thread.
    
    :param callee: The callable to which the decorator is applied.
    
    :param call_args: Positional arguments passed to the call.
    
    :param call_kwargs: Keyword arguments passed to the call.
    
    :param timeout: Argument of the decorator. See :func:`twisted_test`.
    
    :returns: Return value of `callee`.
    """
    _ensure_reactor_running()
    
    class WrappedFailure(object):
        def __init__(self, failure):
            self.failure = failure
    
    def run_in_reactor():
        
        def capture_failures(failure):
            # Somehow the tracktrace object is not stored in the failure.
            # (a memory management thing?). `blockingCallFromThread` is using
            # `failure.raiseException()` which will result in a useless 
            # stack trace which does not even indiciate the line where the 
            # original error occured.
            # So we wrap the failure to avoid `blockingCallFromThread` raising
            # it.
            return WrappedFailure(failure)
        
        defer = _twisted_test_async(callee, call_args, call_kwargs, timeout)
        defer.addErrback(capture_failures)
        return defer
    
    retval = threads.blockingCallFromThread(reactor, run_in_reactor)
    if isinstance(retval, WrappedFailure):
        # Unwrap the failure and report it as an assertion error.
        # `failure.getTraceback()` contains a printed stacktrace back to
        # the original cause of the error.
        # We raise an exception of the right type, but we replace
        # the value with the string representation provided by `failure`.
        failure = retval.failure
        
        failure.printTraceback(file=sys.stderr)
        failure.raiseException()
            
    else:
        return retval


def _twisted_test_async(callee, call_args, call_kwargs, timeout):
    """
    Called from the reactor-thread upon invocation of a method 
    decorated with `@twisted_test`.
    
    Performs the actual test sequence.
    
    :param callee: The callable to which the decorator is applied.
    
    :param call_args: Positional arguments passed to the call.
    
    :param call_kwargs: Keyword arguments passed to the call.
    
    :param timeout: Argument of the decorator. See :func:`twisted_test`.
    
    :returns: Return value of `callee`.
    """
    
    def janitor(value):
        """
        Cleans up the reactor and reports any open connections,
        pending calls, ... as failures.
        
        This method is supposed to be used with `Deferred.addBoth()`.
        
        We don't want the janitor to hide a previous
        failure. If it finds the reactor in unclean state it will
        return a corresponding failure, but only if `value` is not
        a failure itself.
        """
        
        # We use the non-public `_Janitor` from trial. The implementation
        # if this class seems to use a non-public API of the reactor.
        # We should try find an official way to do this.
        
        class ErrorCollector(object):
            def __init__(self):
                self.errors = []
            def addError(self, ignored, failure):
                self.errors.append(failure)
           
        collector = ErrorCollector()
        j = _Janitor(None, collector, reactor)
        j.postCaseCleanup()
        j.postClassCleanup()
        
        # If there already was a failure earlier, ignore
        # janitor errors.
        if not isinstance(value, Failure) and collector.errors:
            return collector.errors[0]
        return value
    
    # Chain of callbacks that runs the test procedure.
    # We have to use `deferLater`, or we
    # end up in an infinite recursion due to the janitor-magic.
    # I don't fully understand this, found this workaround
    # by accident.
    chain = task.deferLater(reactor, 0, lambda:None)
    
    # Check if there is a 'twisted_setup()' for us to call.
    if hasattr(callee, '__get__') and len(call_args) >= 1:
        test_case = call_args[0]
        if hasattr(test_case, 'twisted_setup'):
            chain.addCallback(lambda _:test_case.twisted_setup())
    
    # Then call the test method.
    chain.addCallback(lambda _:callee(*call_args, **call_kwargs))
    
    # Check if there is a 'twisted_teardown()' for us to call.
    if hasattr(callee, '__get__') and len(call_args) >= 1:
        test_case = call_args[0]
        if hasattr(test_case, 'twisted_teardown'):
            
            # Callback has to preserve the result of the test, unless
            # the test was successful but the teardown failed.
            def success_teardown(retval):
                d = defer.maybeDeferred(test_case.twisted_teardown)
                d.addCallback(lambda _:retval)
                return d
            def fail_teardown(failure):
                d = defer.maybeDeferred(test_case.twisted_teardown)
                d.addBoth(lambda _:failure)
                return d
            chain.addCallbacks(success_teardown, fail_teardown)

    # Timeout handling (must be before janitor checks, or the delayed call will be found).
    if timeout > 0:
        _timeoutDeferred(chain, timeout)
        
    # Put the reactor-unclean checks to the end of the queue. This makes the checks a bit less thorough.
    # We don't delay by a time, so we just wait til after cleanup stuff which is already planned.
    chain2 = defer.Deferred()
    chain.addBoth(lambda result: task.deferLater(reactor, 0, chain2.callback, result))

    # Reactor-unclean checks.
    chain2.addBoth(janitor)
    
    return chain2

def _ensure_reactor_running():
    """
    Starts the twisted reactor if it is not running already.
    
    The reactor is started in a new daemon-thread.
    
    Has to perform dirty hacks so that twisted can register
    signals even if it is not running in the main-thread.
    """
    if not reactor.running:
        
        # Some of the `signal` API can only be called
        # from the main-thread. So we do a dirty workaround.
        #
        # `signal.signal()` and `signal.wakeup_fd_capture()`
        # are temporarily monkey-patched while the reactor is
        # starting.
        #
        # The patched functions record the invocations in
        # `signal_registrations`. 
        #
        # Once the reactor is started, the main-thread
        # is used to playback the recorded invocations.
        
        signal_registrations = []

        # do the monkey patching
        def signal_capture(*args, **kwargs):
            signal_registrations.append((orig_signal, args, kwargs))
        def set_wakeup_fd_capture(*args, **kwargs):
            signal_registrations.append((orig_set_wakeup_fd, args, kwargs))
        orig_signal = signal.signal
        signal.signal = signal_capture
        orig_set_wakeup_fd = signal.set_wakeup_fd
        signal.set_wakeup_fd = set_wakeup_fd_capture
        
        
        # start the reactor in a daemon-thread
        reactor_thread = threading.Thread(target=reactor.run, name="reactor")
        reactor_thread.daemon = True
        reactor_thread.start()
        while not reactor.running:
            time.sleep(0.01)
            
        # Give the reactor a moment to register the signals. 
        # Apparently the 'running' flag is set before that.
        time.sleep(0.01)
        
        # Undo the monkey-paching
        signal.signal = orig_signal
        signal.set_wakeup_fd = orig_set_wakeup_fd
        
        # Playback the recorded calls
        for func, args, kwargs in signal_registrations:
            func(*args, **kwargs)


def _timeoutDeferred(deferred, timeout):
    """
    Cancels the given deferred after the given time, if it has not yet callbacked/errbacked it.
    """
    delayedCall = reactor.callLater(timeout, deferred.cancel)
    def gotResult(result):
        if delayedCall.active():
            delayedCall.cancel()
        return result
    deferred.addBoth(gotResult)
    
def monkey_patch_twisted_process():
    
    def reapProcessWrapper(self):
        if self.pid is not None:
            original_reap(self)
            
    if "twisted.internet.process" in sys.modules:
        from twisted.internet import process
        original_reap = process._BaseProcess.reapProcess
        process._BaseProcess.reapProcess = reapProcessWrapper

    
    
monkey_patch_twisted_process()