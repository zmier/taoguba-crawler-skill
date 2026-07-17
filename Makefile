PYTHON ?= ../../../../.venv/bin/python

.PHONY: test test-unit test-e2e test-uat crawl-sample crawl-incremental crawl-backfill-sample crawl-full-trial crawl-full-batch crawl-user-topics

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

crawl-incremental:
	$(PYTHON) scripts/tgb_incremental.py --max-pages 5 --max-articles 20 --max-refresh-articles 20 --comment-pages 1

crawl-backfill-sample:
	$(PYTHON) scripts/tgb_backfill_sample.py --max-list-pages 2 --max-articles-per-page 3 --max-comment-pages 2

crawl-full-trial:
	$(PYTHON) scripts/tgb_full_trial.py --max-list-pages 10 --max-articles-per-page 20 --max-comment-pages 5

crawl-full-batch:
	$(PYTHON) scripts/tgb_full_batch.py --manual-approval --max-list-pages 1 --max-articles-per-page 70 --max-comment-pages 3 --interval 1.0

crawl-user-topics:
	$(PYTHON) scripts/tgb_user_topics.py --user-id $(USER_ID) --all --interval 1.0

crawl-user-topic-details:
	$(PYTHON) scripts/tgb_user_topics.py --user-id $(USER_ID) --details-only --max-articles $(MAX_ARTICLES) --comment-pages 1 --interval 1.0
