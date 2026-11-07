"""Trusted test policy validator. No network, credentials or model calls."""
import hashlib
import json
from pathlib import Path
import sys
import unittest


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def validate(root, manifest):
    if not set(manifest.get('baseline_tests', [])) <= set(manifest['tests']):
        raise ValueError('Original baseline test names removed')
    for name, digest in manifest['baseline_files'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Baseline test source changed: '+name)
    suite = unittest.defaultTestLoader.discover(str(root/'tests'))
    names = [test.id() for test in flatten(suite)]
    if not names or len(names) != len(set(names)) or set(names) != set(manifest['tests']):
        raise ValueError('Discovered test names differ from trusted manifest')
    return suite, names


def main():
    # Policy arrives from the trusted supervisor/base checkout, never task text.
    root = Path(sys.argv[1]).resolve()
    policy = json.loads(sys.argv[2])
    sys.path.insert(0, str(root))
    suite, names = validate(root, policy)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    ok = result.wasSuccessful() and result.testsRun == len(names) and not result.skipped and not result.expectedFailures
    print('CF_TEST_RESULT '+json.dumps({'success':ok,'count':result.testsRun,'tests':sorted(names)}))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
