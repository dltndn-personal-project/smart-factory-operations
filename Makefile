# 검증·실행 진입점 (docs/spec/08-verification.md 2절, 07-runtime.md 6절).
# docker-test는 OPS-4A, smoke는 OPS-9A, feed는 OPS-9B가 추가한다.
PYTHON ?= python3
VENV := .venv

.PHONY: venv test run

venv: $(VENV)/.installed

$(VENV)/.installed: requirements.txt requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -q --disable-pip-version-check -r requirements-dev.txt
	$(VENV)/bin/python -c "import os, sysconfig; open(os.path.join(sysconfig.get_paths()[\"purelib\"], \"factory_operations_src.pth\"), \"w\").write(os.path.abspath(\"src\") + \"\\n\")"
	touch $(VENV)/.installed

test: venv
	$(VENV)/bin/python -m pytest -q -m "not docker" tests

run: venv
	$(VENV)/bin/python -m factory_operations serve
