from redsi.suites.base import Suite, load_tests, resolve_suites, suite, suites


def list_suites() -> list[Suite]:
    import redsi.suites.builtin  # noqa: F401

    return [suites.get(n) for n in suites.names()]


__all__ = ["Suite", "list_suites", "load_tests", "resolve_suites", "suite", "suites"]
