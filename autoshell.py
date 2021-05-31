# usage: import autoshell as a
# a.echo("hello") (Result object that when stringified is the stdout) > "filename"
# a.echo.hello() > filename
# a.echo.hello() | a.cat
# eventually: from autoshell import echo, ps, etc.

# take custom args to pass through to subprocess.run

# log levels: log.warning for each command run, log.error if sometihng returns
# with a non-zero error code

import logging
from subprocess import PIPE, Popen

log = logging.getLogger(__name__)


class Command:
    _default_kwargs = {'stdout': PIPE, 'stderr': PIPE, 'text': True}
    _command: list[str]
    def __init__(self, *args, **kwargs):
        self._command = [*args]
        self._kwargs = self._default_kwargs | kwargs

    def __call__(self, *args, **kwargs):
        # interpreting of types can be done, like if you pass an un-called
        # Command instead of a str you call it, but for now take strs
        if args or kwargs:
            return Command(*(self._command + [*args]), **(self._kwargs | kwargs))
        else:
            log.warning(f"Executing: {self._command} with arguments {self._kwargs}")
            result = Popen(self._command, **self._kwargs)
            return Result(result)

    def __getattr__(self, name):
        return Command(*(self._command + [name]), **self._kwargs)

    def __str__(self):
        return str(self._command)


class Result:
    def __init__(self, process):
        self._process = process
        self._waited = False

    def wait(self):
        if self._waited:
            return

        if self._process.stdin and self._process.stdin != PIPE:
            # https://docs.python.org/3.9/library/subprocess.html#replacing-shell-pipeline
            self._process.stdin.close()

        self.stdout, self.stderr = self._process.communicate()
        self.code = self._process.returncode
        self.waited = True

    def __getattr__(self, name):
        if not self._waited:
            if name in ['returncode', 'stdout', 'stderr']:
                self.wait()
                return getattr(self, name)

        return getattr(self._process, name)

    def __or__(self, other):
        """Pipe two Commands together

        This directly connects the stdout left -> right like a shell pipeline
        so that commands run in parallel
        """
        stdin = {'input': self.stdout} if self._waited else {'stdin': self._process.stdout}
        return Command(*other._command, **(other._kwargs | stdin))


if __name__ == '__main__':
    logging.basicConfig()
