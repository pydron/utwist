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

import unittest
import sys

from twisted.internet import defer
from twisted.internet import protocol, reactor, task
from twisted.python.failure import Failure
from twisted.trial.util import DirtyReactorAggregateError
from twisted.internet.protocol import ClientFactory
from twisted.internet.endpoints import TCP4ServerEndpoint, TCP4ClientEndpoint

from utwist import with_reactor
from twisted.internet.defer import CancelledError

class TestUTwist(unittest.TestCase):
    """
    Unit-tests for the :func:`utwist.twisted_test` decorator.
    """
    
    def test_forwards_exceptions(self):
        """
        Checks that test errors are passed through.
        """
        @with_reactor
        def test():
            raise ValueError()
        self.assertRaises(ValueError, test)
    
    
    def test_fowards_returnvalue(self):
        """
        Checks that return values are passed through (although
        this is probably not used in most test frameworks).
        """
        @with_reactor
        def test():
            return 42
        self.assertEqual(42, test())
    
    
    def test_reactor_running(self):
        """
        Reactor should be running. Not a very strong test,
        since the reactor is started on the first test only,
        but we can check anyways.
        """
        @with_reactor
        def test():
            self.assertTrue(reactor.running)
        test()
        

    def test_timeout(self):
        """
        Checks that timeout causes a test to fail.
        Also checks that the default timeout can be overwritten.
        """
        @with_reactor(timeout=0.01)
        def test():
            def nop():
                return
            return task.deferLater(reactor, 1, nop)
        self.assertRaises(CancelledError, test)
        
        
    def test_no_timeout(self):
        """
        Checks that a timeout of zero, is not interpreted
        literally.
        """
        @with_reactor(timeout=0)
        def test():
            def nop():
                return
            return task.deferLater(reactor, 0.1, nop)
        test()


    def test_deferred_success(self):
        """
        Checks that we can return a value via a deferred.
        """
        @with_reactor
        def test():
            return defer.succeed(42)
        self.assertEqual(42, test())
        
        
    def test_deferred_failure(self):
        """
        Checks that we can fail a test by returning
        a failure via a deferred.
        """
        @with_reactor
        def test():
            return defer.fail(Failure(ValueError()))
        self.assertRaises(ValueError, test)
        
        
    def test_failure(self):
        """
        Checks that we can fail a test by returing
        a failure directly.
        """
        @with_reactor
        def test():
            return Failure(ValueError())
        self.assertRaises(ValueError, test)
        
        
    def test_pending_call(self):
        """
        Checks that leftover pending calls result in a dirty-reactor
        failure.
        """
        @with_reactor
        def test():
            def later():
                pass
            reactor.callLater(1, later)
        self.assertRaises(DirtyReactorAggregateError, test)
        

        
    def test_setup_called(self):
        """
        Checks that `twisted_setup()` is called before the test.
        """
        class TestClass(object):
            def __init__(self):
                self.called = False
            def twisted_setup(self):
                self.called = True
            @with_reactor
            def test(self):
                return self.called
        case = TestClass()
        self.assertTrue(case.test())
        
        
    def test_teardown_called(self):
        """
        Checks that `twisted_teardown()` is called after the test.
        """
        class TestClass(object):
            def __init__(self):
                self.called = False
            def twisted_teardown(self):
                self.called = True
            @with_reactor
            def test(self):
                return self.called
        case = TestClass()
        self.assertFalse(case.test())
        self.assertTrue(case.called)
        
        
    def test_teardown_after_failure(self):
        """
        Checks that `twisted_teardown()` is called even if the
        test failed.
        """
        class TestClass(object):
            def __init__(self):
                self.called = False
            def twisted_teardown(self):
                self.called = True
            @with_reactor
            def test(self):
                raise ValueError()
        case = TestClass()
        self.assertRaises(ValueError, case.test)
        self.assertTrue(case.called)
        
        
    def test_teardown_fails_after_failure(self):
        """
        If the test fails and the teardown fails, the
        failure of the test must be reported.
        """
        class TestClass(object):
            def __init__(self):
                self.called = False
            def twisted_teardown(self):
                raise TypeError()
            @with_reactor
            def test(self):
                raise ValueError()
        case = TestClass()
        self.assertRaises(ValueError, case.test)
        
        
    def test_setup_delegate(self):
        """
        Check that if setup returns a deferred
        that we wait til it has completed before running
        the test.
        """
        class TestClass(object):
            def __init__(self):
                self.called = False
            def twisted_setup(self):
                def later():
                    self.called = True
                return task.deferLater(reactor, 0.01, later)
            @with_reactor
            def test(self):
                return self.called
        case = TestClass()
        self.assertTrue(case.test())
        
        
    def test_teardown_delegate(self):
        """
        Check that if teardown returns a deferred
        that we wait til for it before finishing the
        test.
        """
        class TestClass(object):
            def __init__(self):
                self.called = False
            def twisted_teardown(self):
                def later():
                    self.called = True
                return task.deferLater(reactor, 0.01, later)
            @with_reactor
            def test(self):
                return self.called
        case = TestClass()
        self.assertFalse(case.test())
        self.assertTrue(case.called)
        
        
        
    def test_spawnProcess(self):
        """
        Integration test.
        Checks that we can start a process and detect when it exits.
        If this test fails with a timeout, then there is very likely
        something broken with the interrupt handing.
        """
        class DummyProcessProtocol(protocol.ProcessProtocol):
            def processEnded(self, status):
                process_end.callback(None)
                
        @with_reactor
        def test():
            reactor.spawnProcess(DummyProcessProtocol(), sys.executable, ['python', '-c', 'print "hello"'])
            return process_end

        process_end = defer.Deferred()
        test()
        
        
    def test_tcp_echo(self):
        """
        Integration test.
        Checks if we can open a TCP port, connect to it, send data in both
        directions, and close both connection and port.
        """
        @with_reactor
        def test():
            class Echo(protocol.Protocol):
                def dataReceived(self, data):
                    self.transport.write(data)
                    
            class SayX(protocol.Protocol):
                def __init__(self):
                    self.data_deferred = defer.Deferred()
                def connectionMade(self):
                    self.transport.write("X")
                def dataReceived(self, data):
                    self.transport.loseConnection()
                    self.data_deferred.callback(data)
            
            def open_port():
                echo_factory = ClientFactory()
                echo_factory.protocol = Echo
                endpoint = TCP4ServerEndpoint(reactor, 0, interface='127.0.0.1')
                d = endpoint.listen(echo_factory)
                d.addCallback(port_open)
                return d
                    
            def port_open(listening_port):
                port = listening_port.getHost().port
                return connect(port, listening_port)
                
            def connect(port, listening_port):
                sayx_factory = ClientFactory()
                sayx_factory.protocol = SayX
                endpoint = TCP4ClientEndpoint(reactor, '127.0.0.1', port)
                d = endpoint.connect(sayx_factory)
                d.addCallback(connected, listening_port)
                return d
            
            def connected(sayx_protocol, listening_port):
                d = sayx_protocol.data_deferred
                d.addCallback(disconnected, listening_port)
                return d
                
            def disconnected(data, listening_port):
                self.assertEqual("X", data)
                return listening_port. stopListening()
            
            return open_port()

        test()
