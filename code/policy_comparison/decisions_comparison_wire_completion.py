"""Future-slot adapter; never hot-swap or resume an existing episode."""
import json

import decisions_policy as original
from decisions_wire_budget import bound_request

original_call = original.call


def bounded_call(body, key, folder):
    receipt = bound_request(body)
    # original.call creates the folder. Preserve size evidence even on HTTP error.
    try:
        return original_call(body, key, folder)
    finally:
        if folder.is_dir():
            (folder / 'context_policy.json').write_text(
                json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    original.call = bounded_call
    original.main()
