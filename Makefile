PYTHON ?= ../../.venv/bin/python

.PHONY: test test-unit test-e2e test-uat crawl-sample

test:
	$(PYTHON) -m unittest discover tests

test-unit:
	$(PYTHON) -m unittest discover -s tests/unit -p 'test_*.py'

test-e2e:
	$(PYTHON) -m unittest discover -s tests/e2e -p 'test_*.py'

test-uat:
	$(PYTHON) -m unittest discover -s tests/uat -p 'test_*.py'

crawl-sample:
	$(PYTHON) scripts/tgb_sample.py --list-pages 1 --max-articles 3 --comment-pages 1
