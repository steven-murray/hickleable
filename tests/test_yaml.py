import hickle
import yaml

from hickleable import hickleable


@hickleable()
class A:
    def __init__(self, a):
        self.a = a

    def __eq__(self, other):
        return self.a == other.a


def test_load_yaml(tmpdir):
    fl = tmpdir / "test_load_yaml.h5"
    a = A("more stuff")

    hickle.dump(a, str(fl))

    txt = f"""!hickle {fl}"""

    b = yaml.load(txt, Loader=yaml.FullLoader)
    assert a == b
