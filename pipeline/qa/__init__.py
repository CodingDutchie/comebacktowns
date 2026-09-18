"""Validation rules. A breach raises QAError and fails the run."""


class QAError(Exception):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("QA failed:\n  - " + "\n  - ".join(problems))
