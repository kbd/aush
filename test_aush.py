import aush


def test_basic():
    assert aush.echo("hello").stdout == b"hello\n"
