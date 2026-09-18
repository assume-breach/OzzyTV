"""It has to import on the Python that is actually on the machine.

Raspberry Pi OS Bullseye ships Python 3.9 and Bookworm ships 3.11, and this is
developed on neither. The gap that bites is `A | B` written as a real expression
rather than an annotation: `from __future__ import annotations` defers
annotations, so those are free, but a type ALIAS at module level is evaluated at
import and raises TypeError on 3.9 — the app does not start, and the message is
about unsupported operand types rather than about a Python version.

That shipped. These stop it shipping twice.
"""
import ast
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SOURCES = sorted(REPO.glob("ozzytv/*.py")) + sorted(REPO.glob("tools/*.py"))

# What the oldest Raspberry Pi OS we claim support for can parse and run.
OLDEST = (3, 9)


def _tree(path):
    return ast.parse(path.read_text(), filename=str(path))


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_type_union_is_evaluated_at_import(path):
    """`Item = A | B` at module level. Annotations are fine; this is not."""
    for node in ast.walk(_tree(path)):
        if isinstance(node, (ast.Assign, ast.Return, ast.Call)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr) \
                        and isinstance(sub.left, ast.Name) \
                        and sub.left.id[:1].isupper():
                    pytest.fail(f"{path.name}:{sub.lineno}: "
                                f"`{ast.unparse(sub)}` runs at import and needs 3.10+")


def _annotations(tree):
    """Every annotation in the file: variables, arguments and return types."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.AnnAssign, ast.arg)) and node.annotation is not None:
            yield node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns:
            yield node.returns


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_annotations_are_deferred(path):
    """Which is what makes every OTHER `A | B` in the file safe on 3.9."""
    tree = _tree(path)
    uses_new_union = any(
        isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)
        for ann in _annotations(tree) for n in ast.walk(ann))
    if not uses_new_union:
        return
    assert any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names)
               for n in tree.body), \
        f"{path.name} writes `A | B` in an annotation without deferring it"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_match_statement(path):
    for node in ast.walk(_tree(path)):
        assert not isinstance(node, ast.Match), \
            f"{path.name}:{node.lineno}: match/case needs Python 3.10+"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_dataclass_features_from_after_3_9(path):
    """slots= and kw_only= are 3.10; they fail with a TypeError at class creation
    time, which is to say at import, which is to say the app does not start."""
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.ClassDef):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    assert kw.arg not in ("slots", "kw_only"), \
                        f"{path.name}:{dec.lineno}: @dataclass({kw.arg}=) needs 3.10+"


def test_the_package_states_the_python_it_needs():
    pyproject = (REPO / "pyproject.toml").read_text()
    assert f'requires-python = ">={OLDEST[0]}.{OLDEST[1]}"' in pyproject


@pytest.mark.skipif(sys.version_info[:2] != OLDEST,
                    reason=f"only meaningful on Python {OLDEST[0]}.{OLDEST[1]}")
def test_everything_imports():
    """Runs for real where the oldest supported Python is available — on a Pi, or
    in CI. Here it is skipped, and the AST checks above are what stands in."""
    import importlib
    for path in REPO.glob("ozzytv/*.py"):
        if path.stem != "__main__":
            importlib.import_module(f"ozzytv.{path.stem}")
