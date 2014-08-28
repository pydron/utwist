

utwist - Running twisted's reactor inside regular unit-tests without trial
===========================================================================

Unit testing with twisted is a bit difficult if the tests require the reactor
to run. The official way is to use twisted's own unit testing framework called
`trial`. It is very similar to the `unittest` module. If you would like
to use another framework, or if you like nice IDE integration then `utwist`
might be the right thing for you.

Note that it is considered good practice to write unit tests that
don't perform IO. But for integration tests, and probably some unit-tests as well,
you'll need a reactor running.

Disclaimer: `utwist` is quite a hack. It works, I test it regularly on Linux,
OSX, and Windows, but future versions of twisted might break it. You've been
warned. Hopefully twisted will come in with a better testing solution eventually.

This library is open source and released under the MIT License.

You can install it with `pip install utwist`. It doesn't need to
compile anything, so there shouldn't be any surprises. Even on Windows.

----------------------
Let's get going!
----------------------

.. code-block:: python

   from utwist import with_reactor
   
   @with_reactor
   def test_connect_with_tcp():
     point = TCP4ClientEndpoint(reactor, "google.com", 80)
     d = point.connect(MyFactory())
     return d
     
If run with `nose` this will do exactly what you'd expect. 
It opens the network connection. The test will fail because 
the connection wasn't closed. `utwist` checks that the reactor
is clean at the end of the test.

Of course you don't have to use `nose`. It works just as well
with `unittest`, and probably also with most other frameworks.

----------------------
Deferred return values
----------------------
   
If the test function returns a deferred then the test will
be successful if the deferred resolves to a value or unsuccessful
if the deferred errbacks.

----------------------
Setup and tear-down
----------------------

If there is a function called `twisted_setup()` in the same class
as the test function is defined, then this function will be invoked
before the test, but already in the context of the reactor. Note that
the regular setup function provided by the testing framework will
be executed too, but not in the reactor context.

Accordingly, if there is a `twisted_teardown()` it executes after the
test function, even if the test failed. 

----------------------
Setting a timeout
----------------------
   
If the test, including `twisted_setup` and `twisted_teardown`, has
not completed within the timeout, the test fails. The timeout defaults
to two minutes. A timeout duration of zero disables the timeout.

To specify a different timeout pass it (in seconds) to the decorator:

.. code-block:: python

   @with_reactor(timeout=10)
   def test_quick():
     ...
   
----------------------
How does it work
----------------------
   
I spare you the details, but `utwist` starts the reactor in a separate thread when
the first test is started and lets it run until the end (the reactor cannot be restarted).
It uses `blockingCallFromThread()` to run the test method inside the reactor.
Other than that there are some tricks to check if the reactor is clean, and to clean
it if not. There is also a very dirty hack to make signals work even though the
reactor doesn't run in the main thread.

-----------------------------------
Bug Reports and other contributions
-----------------------------------

This project is hosted here `utwist github page <https://github.com/smurn/utwist>`_.
 
------------
Alternatives
------------

If you don't mind using a cut-down version of `unittest` for your tests, nor to run
the tests with the special runner, then I highly recommend `trial`. It is the
official unit testing tool provided by twisted.


