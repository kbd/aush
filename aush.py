import asyncio
import io
import logging
import os
import sys
from asyncio.subprocess import PIPE, create_subprocess_exec
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Union

log = logging.getLogger(__name__)

READ_CHUNK_LENGTH = 2**10

LOOP = asyncio.get_event_loop()
STDERR_COLOR = b'\x1b[31m'
RESET = b'\x1b[0m'


def _nonstriterable(value):
    return isinstance(value, Iterable) and not isinstance(value, str)


def _listify(value):
    return value if _nonstriterable(value) else [value]


def _convert_kwargs(kwargs):
    """Convert arguments passed by keywords into those that are passed as
    arguments to the subprocess vs those that are passed to the subprocess.

    Arguments that start with underscore are treated specially and are
    passed through to the underlying subprocess call.

    All other arguments are passed through as arguments to the program
    opened in the subprocess call, according to the following rules:

    - underscores are converted to dashes: shell convention tends towards
        dashes, while tokens in Python can only contain underscores.
    - if an argument value is True (eg. foo=True), it is passed through to
        the underlying subprocess call as either -f or --foo, depending on
        how many letters the argument has.
    - if _env is passed, is it merged with the wider os environment and
        passed to the subprocess's env call
    """
    subprocess_args = []
    subprocess_kwargs = {}
    for k, vs in kwargs.items():
        if k.startswith('_'):
            subprocess_kwargs[k[1:]] = vs  # pass arg (- underscore) through to 'run'
            continue

        key = f"{'-' * min(len(k), 2)}{k.replace('_', '-')}"
        for v in _listify(vs):
            if v is True:  # cmd(foo=True) -> cmd --foo
                subprocess_args.append(key)
            else:
                subprocess_args.extend([key, str(v)])

    return subprocess_args, subprocess_kwargs


class Command:
    _default_kwargs = {'_stdout': PIPE, '_stderr': PIPE}
    _command: list[str]
    _kwargs: dict[str, Any]
    _env: dict[str, str]
    _check: bool
    def __init__(self, *args, _check=True, **kwargs):
        if not args:
            raise Exception("Must provide command name")

        self._name = args[0]
        self._check = _check
        self._kwargs = kwargs
        subprocess_args, subprocess_kwargs = _convert_kwargs(self._default_kwargs | kwargs)
        self._command = [*args] + subprocess_args
        self._subprocess_kwargs = subprocess_kwargs

    def _bake(self, *args, **kwargs):
        return Command(*self._command, *args, **(self._kwargs | kwargs))

    def __call__(self, *args, **kwargs):
        kwargs = kwargs.copy()
        if env := kwargs.get('_env'):
            # merge provided env with os.environ
            kwargs['_env'] = os.environ | {k: str(v) for k, v in env.items()}

        cmd = self._bake(*args, **kwargs)
        return Result(cmd, logging.root.level <= logging.INFO)

    def __getitem__(self, key):
        new_cmd = self._command + list([key] if isinstance(key, str) else key)

        return Command(*new_cmd, _check=self._check, **self._kwargs)

    def __getattr__(self, name):
        return self[name.replace('_', '-')]

    def __str__(self):
        return str(self._command)

    def __repr__(self):
        return f"{self.__class__.__name__}({self._command})"

    def __or__(self, other):
        return Pipeline(self, other)


async def _read(buffer, stream, echo=True, color=None):
    while chunk := await stream.read(READ_CHUNK_LENGTH):
        buffer.write(chunk)
        if echo:
            if color:
                for value in color, chunk, RESET:
                    sys.stderr.buffer.write(value)
            else:
                sys.stderr.buffer.write(chunk)
            sys.stderr.buffer.flush()

    return buffer.getvalue()


async def _run(command: Command):
    """Run a Command, return the Process object"""
    cmd = list(map(str, command._command))
    log.warning(f"Executing: {cmd}")
    return await create_subprocess_exec(*cmd, **command._subprocess_kwargs)


class Result:
    def __init__(self, command: Command, echo=True):
        self._command = command
        self._stdout = io.BytesIO()
        self._stderr = io.BytesIO()

        self._process = LOOP.run_until_complete(_run(command))
        LOOP.run_until_complete(asyncio.gather(
            _read(self._stdout, self._process.stdout, echo),
            _read(self._stderr, self._process.stderr, echo, color=STDERR_COLOR),
        ))

        if self._command._check and self.code:
            # lazily evaluates code, which blocks, only if _check
            raise Exception(f"{self._command!r} returned non-zero exit status {self.code}")

    @property
    def finished(self):
        return self._process.returncode is not None

    def wait(self):
        if not self.finished:
            LOOP.run_until_complete(self._process.wait())

    @property
    def code(self):
        self.wait()
        return self._process.returncode

    @property
    def stdout(self):
        self.wait()
        return self._stdout.getvalue()

    @property
    def stderr(self):
        self.wait()
        return self._stderr.getvalue()

    def __getattr__(self, name):
        return getattr(self._process, name)

    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self._command)})"

    def __bool__(self):
        return self.code == 0

    def __int__(self):
        return self.code

    def __str__(self):
        return self.stdout.decode().strip()

    def __bytes__(self):
        return self.stdout

    def __iter__(self):
        yield from str(self).splitlines()

    def _write(self, path, stream, mode):
        with open(path, mode) as f:
            log.info(f"Writing {stream} to {path}({mode})")
            f.write(getattr(self, stream))
        return self

    # todo: make these redirection writes async, but ensure any read tasks
    # finish when the process closes.
    # Probably need to put all reads/writes on a queue
    def __gt__(self, other):
        return self._write(Path(other), 'stdout', 'wb')

    def __rshift__(self, other):
        return self._write(Path(other), 'stdout', 'ab')

    def __mul__(self, other):
        return self._write(Path(other), 'stderr', 'wb')

    def __pow__(self, other):
        return self._write(Path(other), 'stderr', 'ab')


class Pipeline:
    def __init__(self, left: Union[str, Result, Command, "Pipeline"], right: Command):
        self.left = left
        self.right = right

    def __call__(self):
        if isinstance(self.left, Command):
            result = self.left(_check=False)
            return self.right(_stdin=result._process.stdin)

        self.right._bake(_stdin=self.left.stdout)


class _AushModule(ModuleType):
    __file__ = __file__
    __path__: list[str] = []

    def __getitem__(self, name):
        if name == 'cd':
            # special-case cd because running cd as a subprocess
            # doesn't change the working directory of this process
            return os.chdir

        return Command(name)

    def __getattr__(self, name):
        return self[name.replace('_', '-')]

sys.modules[__name__] = _AushModule(__name__)

if __name__ == '__main__':
    logging.basicConfig()
