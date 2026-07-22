"""Tests for _validate_dependency_calls in translate node."""
from cobol_migrator.agent.nodes.translate import _validate_dependency_calls


def test_no_deps_no_errors():
    assert _validate_dependency_calls("x = 1", {}) == []


def test_no_calls_to_deps():
    deps = {
        "PROGB": {
            "python_function_name": "progb_func",
            "python_parameters": [{"name": "a"}, {"name": "b"}],
        }
    }
    code = "def main():\n    x = 1 + 2"
    assert _validate_dependency_calls(code, deps) == []


def test_call_matches():
    deps = {
        "PROGB": {
            "python_function_name": "progb_func",
            "python_parameters": [{"name": "a"}, {"name": "b"}],
        }
    }
    code = "from progb import progb_func\ndef main():\n    progb_func(1, 2)"
    assert _validate_dependency_calls(code, deps) == []


def test_call_wrong_arg_count():
    deps = {
        "PROGB": {
            "python_function_name": "progb_func",
            "python_parameters": [{"name": "a"}, {"name": "b"}],
        }
    }
    code = "from progb import progb_func\ndef main():\n    progb_func(1)"
    errors = _validate_dependency_calls(code, deps)
    assert len(errors) == 1
    assert "progb_func" in errors[0]
    assert "1 args" in errors[0]
    assert "expected 2" in errors[0]


def test_multiple_deps_one_wrong():
    deps = {
        "FUNC1": {
            "python_function_name": "func1",
            "python_parameters": [{"name": "a"}],
        },
        "FUNC2": {
            "python_function_name": "func2",
            "python_parameters": [{"name": "x"}, {"name": "y"}, {"name": "z"}],
        },
    }
    code = "from func1 import func1\nfrom func2 import func2\nfunc1(1)\nfunc2(1, 2)"
    errors = _validate_dependency_calls(code, deps)
    assert len(errors) == 1
    assert "func2" in errors[0]
    assert "2 args" in errors[0]
    assert "expected 3" in errors[0]


def test_syntax_error_returns_empty():
    deps = {
        "FUNC1": {
            "python_function_name": "func1",
            "python_parameters": [{"name": "a"}],
        },
    }
    code = "this is not valid python @@@"
    assert _validate_dependency_calls(code, deps) == []
