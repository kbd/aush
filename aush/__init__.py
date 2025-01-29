import asyncio
import fileinput
import io
import logging
import os
import re
import sys
from asyncio.subprocess import PIPE, create_subprocess_exec
from collections import ChainMap
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Union

log = logging.getLogger(__name__)

READ_CHUNK_LENGTH = 2**10

RESET = b'\x1b[0m'
HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")
INLINE_HEX_RE = re.compile(r"#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})\b")


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
                for value in color.encode(), chunk, RESET:
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


def get_or_create_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


class Result:
    def __init__(self, command: Command, echo=True):
        self._command = command
        self._stdout = io.BytesIO()
        self._stderr = io.BytesIO()
        self._loop = get_or_create_loop()
        self._process = self._loop.run_until_complete(_run(command))
        self._loop.run_until_complete(asyncio.gather(
            _read(self._stdout, self._process.stdout, echo),
            _read(self._stderr, self._process.stderr, echo, color=COLORS.f.red),
        ))

        if self._command._check and self.code:
            # lazily evaluates code, which blocks, only if _check
            raise Exception(f"{self._command!r} returned non-zero exit status {self.code}")

    @property
    def finished(self):
        return self._process.returncode is not None

    def wait(self):
        if not self.finished:
            self._loop.run_until_complete(self._process.wait())

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


def esc(i):
    return f'\x1b[{i}m'  # \x1b == \e


class D(dict):
    __getattr__ = dict.__getitem__


class Formatter:
    def __init__(self, name, code):
        self.name = name
        self.code = code

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"{self.__module__}.{self.__class__.__name__}({self.name})"

    def __call__(self, text):
        return f"{self.code}{text}{COLORS.c.reset}"


class ColorMeta(type):
    @lru_cache
    def __getattr__(cls, name):
        """Build up formatters dynamically"""
        codes = []
        formatters = name.split("_")
        for f in formatters:
            code = None
            if f.startswith('bg'):
                if (tempcode := f[2:]) in cls.b:
                    code = cls.b[tempcode]
                elif HEX_RE.match(tempcode):
                    code = COLORS.hexbg(tempcode)
            else:
                code = ChainMap(cls.c, cls.f).get(f)
                if not code and HEX_RE.match(f):
                    code = COLORS.hexfg(f)

            if not code:
                raise AttributeError(f"{f} is not a valid formatter")

            codes.append(code)

        return Formatter(name, ''.join(codes))

    __getitem__ = __getattr__


class COLORS(metaclass=ColorMeta):
    # https://en.`wikipedia.org/wiki/ANSI_escape_code
    colors = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']
    codes = dict(reset=0, bold=1, it=3, ul=4, rev=7, it_off=23, ul_off=24, rev_off=27)

    c = D({name: esc(i) for name, i in codes.items()})  # c = control
    f = D({c: esc(30+i) for i,c in enumerate(colors)})  # f = foreground
    b = D({c: esc(40+i) for i,c in enumerate(colors)})  # b = background
    e = D(  # e = escapes for use within prompt, o=open, c=close
        zsh=D(o='%{', c='%}'),
        bash=D(o='\\[\x1b[', c='\\]'),
        interactive=D(o='', c=''),
    )

    @staticmethod
    def rgb(hex: str):
        """Convert a hex string like #RGB or #RRGGBB (# optional) into a tuple of RGB values."""
        if not (match := HEX_RE.match(hex)):
            raise ValueError(f"{hex} is not a valid hex color")

        hex = match.group(1)
        if len(hex) == 3:
            hex = ''.join(c*2 for c in hex)

        return tuple(int(hex[i:i+2], 16) for i in range(0, 6, 2))

    @staticmethod
    def hexfg(hexstr: str):
        r, g, b = COLORS.rgb(hexstr)
        return esc(f"38;2;{r};{g};{b}")

    @staticmethod
    def hexbg(hexstr: str):
        r, g, b = COLORS.rgb(hexstr)
        return esc(f"48;2;{r};{g};{b}")


class _AushModule(ModuleType):
    __file__ = __file__
    __path__: list[str] = []

    def __getitem__(self, name):
        if name.isupper():
            g = globals()
            if name in g:
                return g[name]
            raise ImportError(f"module {__name__!r} has no attribute {name!r}")

        if name == 'cd':
            # special-case cd because running cd as a subprocess
            # doesn't change the working directory of this process
            return os.chdir

        return Command(name)

    def __getattr__(self, name):
        if not name.isupper():
            name = name.replace('_', '-')
        return self[name]

sys.modules[__name__] = _AushModule(__name__)

if __name__ == '__main__':
    logging.basicConfig()
    from argparse import ArgumentParser
    parser = ArgumentParser(description="aush: cli library/utils")
    parser.add_argument('-c', '--color', help="Output an example of the provided color code")
    parser.add_argument(
        '-s', '--substitute', nargs="*",
        help="Substitute hex color codes in the provided text to show their color"
    )
    args = parser.parse_args()
    if args.color:
        print(f"{args.color}: {COLORS.hexbg(args.color)}     {COLORS.c.reset}")
    if args.substitute is not None:
        sys.argv = sys.argv[1:]  # strip off -s
        for line in fileinput.input(args.substitute or None):
            print(INLINE_HEX_RE.sub(lambda m: f"{m.group(0)} [{COLORS.hexbg(m.group(1))}     {COLORS.c.reset}]", line), end="")
