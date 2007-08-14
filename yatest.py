#!/usr/bin/env python

# Yet Another Test framework
#
# Basically does test scanning like nose or py.test (but simpler), and then
# the actual test running is way simplified, and -- critically -- it can fork
# before the test to give them each a pristine environment, even if there are
# obnoxious shared libraries that don't want to play along (*cough* GTK+
# *cough*).
#
# It will scan a package, looking for all modules whose name contains "test"
# or "Test" (anywhere in their full name), and then within each such module it
# will look for all classes whose name contains "test" or "Test", and then for
# each such class it will instantiate (with no arguments) one instance for
# each method whose name contains "test" or "Test", and on that instance run
# .setUp(), then the test method, then .tearDown().  If the test method throws
# an exception then it failed, if it doesn't then it succeeded.  If .setUp()
# or .tearDown() throw an exception, then the test is an error (tearDown()
# will be called in any case).
#
# Except, if the module or class or method has __test__ = False set, then it
# will be ignored.
#
# Having the 'nose' package installed will give you more details on errors.
#
# Desireable future enhancements:
#   -- Timeout support (even more fun select stuff -- this may call for
#      twisted...).
#   -- Ability to run specific tests
#   -- Some way to have setup that happens in the parent for multiple children
#      (e.g. spawning Xvfb, dbus-daemon, and trusting that they will reset
#      when all their clients have been *killed off*, even if we do not trust
#      anything less than that to clean things up fully).
#   -- Parallelized testing?

import sys
import os
import os.path
import traceback
import signal
import tempfile
from cPickle import dump, load
from types import ClassType
from optparse import OptionParser

try:
    from nose.inspector import inspect_traceback
except ImportError:
    def inspect_traceback(*args):
        return "(unknown; install 'nose' for more details)"

SKIPPED = "SKIPPED"
SUCCESS = "SUCCESS"
FAILURE = "FAILURE"
    
def ispkg(path):
    return (os.path.isdir(path)
            and os.path.exists(os.path.join(path, "__init__.py")))

class YaTest(object):
    def main(self):
        parser = OptionParser(usage="%prog PATH-TO-PACKAGE")
        parser.add_option("-S", "--nocapture",
                          dest="capture_output",
                          action="store_false", default=True,
                          help="disable capture of stdout/stderr from tests")
        (opts, args) = parser.parse_args()
        if len(args) != 1:
            parser.error("Takes exactly 1 argument")
            
        pkg_path = args[0]
        assert ispkg(pkg_path)

        # Set up environment:
        pkg_dir, pkg_name = os.path.split(pkg_path)
        sys.path.insert(0, pkg_dir)

        if "DBUS_SESSION_BUS_ADDRESS" in os.environ:
            del os.environ["DBUS_SESSION_BUS_ADDRESS"]
        if "DISPLAY" in os.environ:
            del os.environ["DISPLAY"]

        reporter = Reporter()
        Runner(reporter, opts.capture_output).scan_pkg(pkg_path, pkg_name)
        reporter.close()
        

class Runner(object):
    def __init__(self, reporter, capture_output):
        self.reporter = reporter
        self.capture_output = capture_output

    def thing_looks_testy(self, name, obj):
        return (("test" in name or "Test" in name)
                and getattr(obj, "__test__", True))

    def scan_pkg(self, pkg_path, pkg_name):
        assert ispkg(pkg_path)
        # packages are themselves basically modules
        self.maybe_load_and_scan_module(pkg_name)
        # look for children
        for child_basename in os.listdir(pkg_path):
            child_path = os.path.join(pkg_path, child_basename)
            if ispkg(child_path):
                self.scan_pkg(child_path,
                              ".".join([pkg_name, child_basename]))
            if (child_path.endswith(".py")
                and child_basename != "__init__.py"):
                child_modname = ".".join([pkg_name, child_basename[:-3]])
                self.maybe_load_and_scan_module(child_modname)
            
    def maybe_load_and_scan_module(self, module_name):
        # Hack: Skip out early if the module cannot possibly be interesting.
        if not self.thing_looks_testy(module_name, None):
            return
        # __import__("foo.bar.baz") returns the foo module object:
        try:
            mod = __import__(module_name)
        except ImportError:
            sys.stderr.write("Error loading module: %s; skipping\n"
                             % module_name)
            return
        for comp in module_name.split(".")[1:]:
           mod = getattr(mod, comp) 
        if not self.thing_looks_testy(module_name, mod):
            return

        for key, val in mod.__dict__.iteritems():
            if (self.thing_looks_testy(key, val)
                and isinstance(val, (type, ClassType))):
                self.run_test_class(".".join([module_name, key]), val)

    def run_test_class(self, class_name, cls):
        for key, val in cls.__dict__.iteritems():
            if (self.thing_looks_testy(key, val)
                and callable(val)):
                self.run_test_method(class_name, cls, key)

    def run_test_method(self, class_name, cls, name):
        (readable_fd, writeable_fd) = os.pipe()
        readable = os.fdopen(readable_fd, "rb")
        writeable = os.fdopen(writeable_fd, "wb")
        if self.capture_output:
            output = tempfile.TemporaryFile()
        else:
            output = None
        pid = os.fork()
        if pid:
            writeable.close()
            self.run_test_method_in_parent(pid,
                                           class_name, cls, name, readable,
                                           output)
        else:
            readable.close()
            self.run_test_method_in_child(cls, name, writeable,
                                          output)
            # This should not return
            assert False
        
    def run_test_method_in_parent(self, child_pid,
                                  class_name, cls, name, readable, output):
        method_name = ".".join([class_name, name])
        try:
            result = load(readable)
        except EOFError:
            one_result = (FAILURE, "?? (child blew up before reporting back)")
            result = (one_result, one_result, one_result)
        readable.close()
        os.kill(-child_pid, signal.SIGTERM)
        os.waitpid(child_pid, 0)
        if output is not None:
            output.seek(0)
            output_data = output.read()
            output.close()
        else:
            output_data = None
        self.reporter.report(method_name, output_data, result)

    def string_for_traceback(self, exc_info):
        tb = "".join(traceback.format_exception(*exc_info))
        details = inspect_traceback(exc_info[2])
        return "%s\nDetails of failing source:\n%s" % (tb, details)

    def marshal_one_result(self, result):
        if result is None:
            return (SKIPPED,)
        elif result is True:
            return (SUCCESS,)
        else:
            return (FAILURE, self.string_for_traceback(result))

    def run_test_method_in_child(self, cls, name, writeable, output):
        os.setpgid(0, 0)
        if output is not None:
            os.dup2(output.fileno(), 1)
            os.dup2(output.fileno(), 2)

        instance = None         # None or instance of cls
        setup_result = None     # True or exc_info
        test_result = None      # None or True or exc_info
        teardown_result = None  # True or exc_info
        # If at first you don't succeed...
        try:
            try:
                try:  # ...again.
                    instance = cls()
                    if hasattr(instance, "setUp"):
                        instance.setUp()
                except:
                    setup_result = sys.exc_info()
                else:
                    setup_result = True
                if setup_result is True:
                    try:
                        getattr(instance, name)()
                    except:
                        test_result = sys.exc_info()
                    else:
                        test_result = True
            finally:
                try:
                    if hasattr(instance, "tearDown"):
                        instance.tearDown()
                except:
                    teardown_result = sys.exc_info()
                else:
                    teardown_result = True

                # Send the results back to our parent.
                dump((self.marshal_one_result(setup_result),
                      self.marshal_one_result(test_result),
                      self.marshal_one_result(teardown_result)),
                     writeable, -1)
        except:
            pass
        writeable.close()
        sys.exit()
            

class Reporter(object):
    def __init__(self):
        self.total_run = 0
        self.total_passed = 0
        sys.stdout.write("Testing: ")
        sys.stdout.flush()

    def report(self, method_name, output_data, marshalled_result):
        # NB output_data may be None if output capturing is disabled
        self.total_run += 1
        (setup, test, teardown) = marshalled_result
        if (setup[0] == SUCCESS
            and test[0] == SUCCESS
            and teardown[0] == SUCCESS):
            self.total_passed += 1
            sys.stdout.write(".")
            sys.stdout.flush()
        else:
            # NB the newline at the start of this string
            if output_data is None:
                output_string = "<child output not captured>"
            else:
                # FIXME: sanitize output?
                output_string = output_data
            sys.stdout.write("""
=========================================
Problem in: %s
=========================================
test output:
%s
-----------------------------------------
__init__ and setUp: %s
-----------------------------------------
test itself: %s
-----------------------------------------
tearDown: %s
-----------------------------------------
""" % (method_name,
       output_string,
       "\n".join(setup),
       "\n".join(test),
       "\n".join(teardown)))
            sys.stdout.flush()

    def close(self):
        sys.stdout.write("\nRun complete; %s tests, %s failures.\n"
                         % (self.total_run,
                            (self.total_run - self.total_passed) or "no"))

if __name__ == "__main__":
    YaTest().main()
