"""Scaffolds pytest parity tests (skeleton).
You still need to fill in fixture URLs and expected outputs.
"""
from pathlib import Path

TEST = Path("tests/test_parity.py")

CONTENT = '''\
def test_parity_placeholder():
    # TODO:
    # 1) call API to submit job
    # 2) wait for completion
    # 3) compare output vs golden
    assert True
'''

def main():
    TEST.parent.mkdir(parents=True, exist_ok=True)
    if not TEST.exists():
        TEST.write_text(CONTENT)
    print("Wrote tests/test_parity.py")

if __name__ == "__main__":
    main()
