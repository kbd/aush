import logging
import sys
from pathlib import Path
from subprocess import PIPE, Popen
from types import ModuleType
from typing import Iterable

log = logging.getLogger(__name__)


class Result:
    def __init__(self, command, process):
        self._command = command
        self._process = process
        self._waited = False

    def wait(self):
        if self._waited:
            return

        if self._process.stdin and self._process.stdin != PIPE:
            # https://docs.python.org/3.9/library/subprocess.html#replacing-shell-pipeline
            self._process.stdin.close()

        self.stdout, self.stderr = self._process.communicate()
        self.returncode = self._process.returncode
        self.code = self.returncode
        self.waited = True

    def __getattr__(self, name):
        if not self._waited:
            if name in ['code', 'returncode', 'stdout', 'stderr']:
                self.wait()
                return getattr(self, name)

        return getattr(self._process, name)

    def __bool__(self):
        return self.code == 0

    def __int__(self):
        return self.code

    def __str__(self):
        return self.stdout.strip()

    def _write(self, path, stream, mode):
        with open(path, mode) as f:
            log.info(f"Writing {stream} to {path}({mode})")
            f.write(getattr(self, stream))
        return self

    def __gt__(self, other):
        return self._write(Path(other), 'stdout', 'w')

    def __mul__(self, other):
        return self._write(Path(other), 'stderr', 'w')

    def __rshift__(self, other):
        return self._write(Path(other), 'stdout', 'a')

    def __pow__(self, other):
        return self._write(Path(other), 'stderr', 'a')

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


def _convert_kwargs(kwargs):
    converted_args = []
    converted_kwargs = {}
    for k, vs in kwargs.items():
        if k.startswith('_'):
            converted_kwargs[k[1:]] = vs  # pass arg (- underscore) through to 'run'
            continue

        key = f"{'-' * min(len(k), 2)}{k.replace('_', '-')}"
        for v in _listify(vs):
            if v is True:
                converted_args.append(key)
            else:
                converted_args.extend([key, str(v)])

    return converted_args, converted_kwargs


class Command:
    _default_kwargs = {'stdout': PIPE, 'stderr': PIPE, 'text': True}
    _command: list[str]
    def __init__(self, *args, **kwargs):
        self._command = [*args]
        self._kwargs = self._default_kwargs | kwargs

    def __call__(self, *args, **kwargs):
        converted_args, converted_kwargs = _convert_kwargs(kwargs)
        cmd = self._command + [*args] + converted_args
        kwargs = self._kwargs | converted_kwargs
        log.warning(f"Executing {cmd} with arguments {kwargs}")
        result = Popen(cmd, **kwargs)
        return Result(self, result)

    def __getitem__(self, *args):
        return Command(*(self._command + [*args]), **self._kwargs)

    __getattr__ = __getitem__

    def __str__(self):
        return str(self._command)

    def __repr__(self):
        return f"{self.__class__.__name__}({self._command!r})"

    def __or__(self, other):
        return self() | other


class _CommandModule(ModuleType):
    def __getattr__(self, name):
        return Command(name)

sys.modules[__name__] = _CommandModule(__name__)

if __name__ == '__main__':
    logging.basicConfig()
