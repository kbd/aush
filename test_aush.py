from aush import HEX_RE, echo


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

def test_hex_re():
    assert HEX_RE.match("#01F")
    assert HEX_RE.match("#abcdef")
    assert HEX_RE.match("666")
    assert not HEX_RE.match("#FF")
    assert not HEX_RE.match("#ggg")
    assert not HEX_RE.match("fffffff")
