test:
	pytest

build:
	rm dist/*
	uv build

publish:
	uv publish
