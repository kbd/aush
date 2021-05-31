# usage: import autoshell as a
# a.echo("hello") (Result object that when stringified is the stdout) > "filename"
# a.echo.hello() > filename
# a.echo.hello() | a.cat
# eventually: from autoshell import echo, ps, etc.

# take custom args to pass through to subprocess.run

# log levels: log.warning for each command run, log.error if sometihng returns
# with a non-zero error code

import logging
import sys
from pathlib import Path
from subprocess import PIPE, Popen
from types import ModuleType
from typing import Iterable

log = logging.getLogger(__name__)


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

    def __str__(self):
        return self.stdout.strip()

    def _write(self, path, mode):
        with open(path, mode) as f:
            log.info(f"Writing ({mode}) to {path}")
            f.write(self.stdout)

    def __gt__(self, other):
        self._write(Path(other), 'w')

    def __rshift__(self, other):
        self._write(Path(other), 'a')

    def __or__(self, other):
        """Pipe two Commands together

        This directly connects the stdout left -> right like a shell pipeline
        so that commands run in parallel
        """
        stdin = {'input': self.stdout} if self._waited else {'stdin': self._process.stdout}
        return Command(*other._command, **(other._kwargs | stdin))


def _nonstriterable(value):
    return isinstance(value, Iterable) and not isinstance(value, str)


def _listify(value):
    return value if _nonstriterable(value) else [value]


def convert_kwargs(kwargs):
    converted_kwargs = []
    for k, vs in kwargs.items():
        if k.startswith('_'):
            # todo: args that start with underscore will be special
            # but anything not understood by autoshell will be passed along to
            # subprocess.run with the underscore removed
            continue

        key = f"{'-' * min(len(k), 2)}{k.replace('_', '-')}"
        for v in _listify(vs):
            if v is True:
                converted_kwargs.append(key)
            else:
                converted_kwargs.extend([key, str(v)])

    return converted_kwargs


class Command:
    _default_kwargs = {'stdout': PIPE, 'stderr': PIPE, 'text': True}
    _command: list[str]
    def __init__(self, *args, **kwargs):
        self._command = [*args]
        self._kwargs = self._default_kwargs | kwargs

    def __call__(self, *args, **kwargs):
        cmd = self._command + [*args] + convert_kwargs(kwargs)
        log.warning(f"Executing: {cmd} with arguments {self._kwargs}")
        result = Popen(cmd, **self._kwargs)
        return Result(result)

    def __getitem__(self, *args):
        # return Command(*(self._command + [*args]), **(self._kwargs | kwargs))
        return Command(*(self._command + [*args]), **self._kwargs)

    __getattr__ = __getitem__

    def __str__(self):
        return str(self._command)

    def __repr__(self):
        return f"{self.__class__.__name__}({self._command!r})"


class MyModule(ModuleType):
    def __getattr__(self, name):
        return Command(name)

sys.modules[__name__] = MyModule(__name__)

if __name__ == '__main__':
    logging.basicConfig()
