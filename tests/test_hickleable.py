import pytest

import attr
import hickle
import time
import warnings
from functools import cached_property
from pathlib import Path

from hickleable import hickleable


@hickleable()
@attr.s(frozen=True)
class A:
    a = attr.ib("stuff")


@hickleable()
@attr.s(frozen=True)
class FrozenWithCachedProperty:
    a = attr.ib("stuff")

    @cached_property
    def big_old_computation(self):
        time.sleep(0.1)
        return time.time()

    def __attrs_post_init__(self):
        if self.a == "warnme":
            warnings.warn("warning you!", stacklevel=2)


@hickleable(evaluate_cached_properties=True)
@attr.s(frozen=True)
class FrozenWithCachedPropertyEval:
    a = attr.ib("stuff")

    @cached_property
    def big_old_computation(self):
        time.sleep(0.1)
        return time.time()

    def __gethstate__(self):
        return self.__dict__

    def __sethstate__(self, hstate):
        self.__dict__.update(hstate)


class B:
    def __init__(self, b: dict, name: str = "name"):
        self.b = b
        self.name = name

    def __eq__(self, other):
        return self.b == other.b

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, other):
        self.__dict__ = other


@pytest.fixture(scope="module")
def tmpdir(tmp_path_factory):
    return tmp_path_factory.mktemp("tests")


def test_simple_class(tmpdir):
    fl = tmpdir / "test_simple.h5"

    a = A("more stuff")

    hickle.dump(a, fl)

    aa = hickle.load(fl)

    assert aa == a


def test_nested(tmpdir):
    fl = tmpdir / "test_nested.h5"
    a = A(A("nested"))

    hickle.dump(a, fl)
    b = hickle.load(fl)
    assert a == b


def test_path(tmpdir, recwarn):
    fl = tmpdir / "test_path.h5"
    a = Path("here/to/there")

    hickle.dump(a, fl)
    b = hickle.load(fl)

    assert a == b
    assert len(recwarn) == 0


def test_cached_properties(tmpdir):
    fl = tmpdir / "test_cached_properties.h5"

    a = FrozenWithCachedProperty(3)
    hickle.dump(a, fl)
    b = hickle.load(fl)
    assert a == b

    assert "big_old_computation" not in a.__dict__

    # cache it
    t = a.big_old_computation
    assert "big_old_computation" in a.__dict__
    assert t == a.big_old_computation

    hickle.dump(a, fl)
    b = hickle.load(fl)
    assert b.big_old_computation == a.big_old_computation


def test_cached_properties_eval(tmpdir):
    fl = tmpdir / "test_cached_properties_eval.h5"

    a = FrozenWithCachedPropertyEval(3)
    hickle.dump(a, fl)
    b = hickle.load(fl)
    assert a == b
    t = time.time()
    assert b.big_old_computation < t


def test_hkl_str(tmpdir):
    fl = tmpdir / "test_hkl_str.h5"

    bb = hickleable(hkl_str="my_string")(B)
    b = bb({"hey": "there"})

    hickle.dump(b, fl)
    c = hickle.load(fl)
    assert b == c

    fl = tmpdir / "test_hkl_bytes.h5"

    bb = hickleable(hkl_str=b"my_string")(B)
    b = bb({"hey": "there"})

    hickle.dump(b, fl)
    c = hickle.load(fl)
    assert b == c

    with pytest.raises(TypeError):
        hickleable(hkl_str=3)(B)


def test_with_metadata(tmpdir):
    fl = tmpdir / "test_with_metadata.h5"

    bb = hickleable(metadata_keys=["name"])(B)
    b = bb({"yo": "sup"}, name="ivan")

    hickle.dump(b, fl)
    c = hickle.load(fl)

    assert c.name == "ivan"

    with pytest.warns(UserWarning, match="Ignoring metadata key non-existent"):
        bb = hickleable(metadata_keys=["non-existent"], hkl_str="!ignore!")(B)
        hickle.dump(bb({}), fl)


def test_attrs_post_init(tmpdir):
    fl = tmpdir / "test_attrs_post_init.h5"

    a = FrozenWithCachedProperty("warnme")

    hickle.dump(a, fl)

    with pytest.warns(UserWarning, match="warning you!"):
        hickle.load(fl)
