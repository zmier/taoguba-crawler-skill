# Tests

Testing follows TDD-BDD and red-green-refactor.

Layers:

- `unit/`: small pure functions, parser edge cases, URL rules.
- `integration/`: module boundaries, such as parser + storage or request + parser with mocked HTTP.
- `e2e/`: fixture-driven mini pipelines across multiple project stages.
- `uat/`: user acceptance checks for outputs, commands, and operational behavior.
- `fixtures/`: stable HTML/JSON samples used by tests.

All test functions should use Chinese GIVEN-WHEN-THEN comments.

