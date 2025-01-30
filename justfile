test:
	pytest

build:
	rm dist/*
	uv build

publish:
	uv publish

# export UV_PUBLISH_TOKEN="$(just token)"
token:
	op item get PyPI --fields=token --reveal
