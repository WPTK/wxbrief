## Purpose

<!-- Why this change: the problem it solves or, for a fix, the root cause. -->

## What changed

<!-- The change in a few lines. Mention anything removed. -->

## How it was tested

<!-- Commands run, new or updated tests, manual checks. -->

Closes #

## Checklist

- [ ] `python -m ruff check .`
- [ ] `python -m mypy wxbrief`
- [ ] `python -m vulture wxbrief scripts --min-confidence 80`
- [ ] `python -m pytest`
- [ ] Goldens reviewed against the raw reports (`git diff`), if any changed
