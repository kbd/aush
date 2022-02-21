# aush

Pythonic subprocess library

# Introduction

`aush` is a Python library to make calling other programs and getting their output as easy as possible. It's intended to be the best possible melding of shell scripting and Python. It's *aushome*.

# Philosophy

Command line programs are basically “functions” available to call from any other language, whose signature looks like: `list[str] -> (code: smallint, stdout: stream, stedrr: stream)`. That's what calls like [execve](https://linux.die.net/man/2/execve) are doing underneath.

The goal of this library is to make calling those functions as natural as possible within Python.

# Motivation

So often I've found myself writing a small Bash/shell script that just calls some programs and maybe does some conditionals. Naturally, it has to start with

```
#!/usr/bin/env bash
set -Eeuxo pipefail
```

for a "strict mode" that has some of the same failure properties you expect a program to have, such as that your program doesn't just keep running when a command fails, it won't silently proceed if you use undeclared variables, and so on.

Then it frequently occurs to want to do something "hard" in shell, like string processing or data structures or even command-line argument parsing.
Python has `argparse` in the stdlib, I don't want to mess with `getopt`.
I want to be able to bust out some Pandas DataFrames or Requests requests, read json or whatever.

So often when I start with Bash, I wind up transitioning the script to Python, and that often feels *terrible*.
Pipes become an unnatural operation.
I can't just "redirect to a file" I need to know how to call `subprocess.run` to capture stdout (there are a few different ways), open and close the file, and so on.
Instead, `aush` makes the transition from shell to Python feel *better*.

Here's the [origin thread on lobste.rs](https://lobste.rs/s/p1hict/zxpy_tool_for_shell_scripting_python#c_agohpx).

# Installation

```pip install aush```

# Examples

I recently make a [create-python](https://github.com/kbd/setup/blob/master/HOME/bin/create-python) program that will initialize a Python project the same way every time, as a [Poetry](https://python-poetry.org/) project with the same set of default dependencies, linters, and so on.

At first I created a shell script. Here's a portion:

```bash
poetry init \
  --no-interaction \
  --name="$1" \
  --author="$(git config --get user.name)" \
  --dev-dependency=pytest \
  --dev-dependency=ipython \
  --dev-dependency=pylint \
  --dev-dependency=mypy \
  --dev-dependency=black \
  --dev-dependency=pudb

poetry install
```

Here's how that converts to Python:

```python
cmd = ['git', 'config', '--get', '--global', 'user.name']
username = run(cmd, check=True, capture_output=True, text=True).stdout.strip()

cmd = [
  'poetry', 'init',
  '--no-interaction',
  '--name', sys.argv[1],
  '--author', username,
  '--dev-dependency=pytest',
  '--dev-dependency=ipython',
  '--dev-dependency=pylint',
  '--dev-dependency=mypy',
  '--dev-dependency=black',
  '--dev-dependency=pudb',
]
run(cmd, check=True)
run(['poetry', 'install'], check=True)
```

Here's how that looks now using `aush`:

```python
poetry.init(
    no_interaction = True,
    name = args.name,
    author = git.config(get='user.name'),
    dev_dependency = ['pytest', 'ipython', 'pylint', 'mypy', 'black', 'pudb'],
)
poetry.install()
```

I think that finally feels *better* than either shell or Python alone. Feel free to look at [`create-python`'s history](https://github.com/kbd/setup/commits/master/HOME/bin/create-python) where I convert it from shell to Python and try various libraries along the way.

# Usage

`aush` has `Command`s and `Result`s. You make a base command like:

```
from aush import echo, git, python3
```

Then, any new command is immutably created from another command by either dot or indexing notation:

```python
git.init()
echo("*.sqlite3") > '.gitignore'
git.add(all=True)
git.commit(m="Initial commit")
```

Here's an example of explicitly creating a command from another using index notation:

```python
django_manage = python3["manage.py"]
django_manage.startapp(args.name)
django_manage.migrate()
django_manage.createsuperuser(
    noinput = True,
    username = "admin",
    email = git.config(get='user.email'),
    _env = dict(DJANGO_SUPERUSER_PASSWORD='password'),
)
```

Here's how that call to `createsuperuser` looks in equivalent shell:

```shell
DJANGO_SUPERUSER_PASSWORD='password' python3 manage.py createsuperuser \
  --noinput \
  --username admin \
  --email "$(git config --get=user.email)"
```

Note that, like shell, in `aush` you don't have to manually merge in `os.environ` if you want to add new things to the environment.

A program gets executed when a function call () is made on a `Command`.
That returns a `Result`.
The result has `.code`, `.stdout`, and `.stderr` members to get the results of running the command.
Using the `Result` you can also redirect stdout to a file with `result > 'filename'`, `bool(result)` indicates success or failure of the command, and more.

`aush` calls follow the following conventions:

- positional arguments are passed verbatim
- single-letter keyword arguments are converted to single-dash arguments
- longer keyword arguments are converted to double-dash arguments
- underscores in keywords and program names are converted to dashes
- if the value of a keyword argument is an iterable (not `str`), it is repeated

If the conventions don't do what you want, you can always fall back to passing exactly the strings you want, positionally, in the list way of creating commands.

# aush Design Goals:

## `aush` should provide the *most convenient* way to write "shell scripts"

* make it easy to call subprocesses and get their outputs
* make subprocesses calls *look* like idiomatic Python
* favor convenience over performance/control (there are lower level APIs available to use)
* but still enable shell performance patterns, such as:
  * piping and redirecting shouldn't have to wait for one process to complete in order to start
  * aush can (optionally) log stdout/stderr "as they happen" same as you would for a shell script
* Safer subprocess management
  * be "safer" than shell scripts or Python
  * fewer opportunities for string substitution or incorrect input handling leading to deadlocks
  * throws exceptions on non-zero return codes (like set -e by default) to make it harder to miss error cases

## Secondary design goals

* it should make good use of asyncio, and eventually help script applications like expect
* it should allow you to build tools around cli tools, like timestamping each line of output (something I miss from iTerm2)
* just like you'd use Pandas to deal with tabular data (I'll often use it just to massage csvs) I hope `aush` can be useful for calling subprocesses in your programs, and help write *safer* programs that interact with subprocesses, and bigger "shell scripts" than you would otherwise
* Allow `aush` to be a command-line program itself that does something? Maybe when called as a module it can provide testing utilities like my `argv` or `randomtextgenerator`. Maybe an "aush script" could find a way to automatically import anything not found in python space and try to run it? That way you can avoid the 'from aush import a million things' and turn logging on, etc.

## Non-goals

* `aush` is not a new language or an interactive shell; it's just a Python library

# FAQ

Q. Pronunciation?

A. It's pronounced "awwsh" ("au" as in "audible").

Q. Where does the name come from?

A. Originally I named it "autoshell", but when I went to put it on PyPI I found "autoshell" was taken, while the shorter present name wasn't.
