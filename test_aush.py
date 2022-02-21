import aush
from aush import echo


def test_basic():
    assert echo("hello").stdout == b"hello\n"

def test_str():
    assert str(echo("hello")) == "hello"

def test_lines():
    assert list(echo("hello\nworld")) == ['hello','world']

def test_redirect(tmpdir):
    redirect_file = tmpdir / 'tmp'
    echo("hello") > redirect_file
    assert open(redirect_file).read() == "hello\n"
