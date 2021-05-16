# usage: import autoshell as a
# a.echo("hello") (Result object that when stringified is the stdout) > "filename"
# a.echo.hello() > filename
# a.echo.hello() | a.cat
# eventually: from autoshell import echo, ps, etc.

# take custom args to pass through to subprocess.run

# log levels: log.warning for each command run, log.error if sometihng returns
# with a non-zero error code

import logging
import subprocess
from collections import namedtuple

log = logging.getLogger(__name__)

Result = namedtuple("Result", ['code', 'stdout', 'stderr'])

class ShellCommand:
    _default_kwargs = {'check': True, 'capture_output': True, 'text': True}
    _command: list[str]
    def __init__(self, *args, **kwargs):
        self._command = list(args)
        self._kwargs = self._default_kwargs | kwargs

    def __call__(self, *args, **kwargs):
        # interpreting of types can be done, like if you pass an un-called
        # ShellCommand instead of a str you call it, but for now take strs
        cmd = self._command + list(args)
        runargs = self._kwargs | kwargs
        log.warning(f"Executing: {cmd} with arguments {runargs}")
        result = subprocess.run(cmd, **runargs)
        if result.returncode:
            log.error(f"Return code {result.returncode} from process")

        return Result(result.returncode, result.stdout, result.stderr)

    def __getattr__(self, name):
        return ShellCommand(*(self._command + [name]), **self._kwargs)

if __name__ == '__main__':
    logging.basicConfig()
