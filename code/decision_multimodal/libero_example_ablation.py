"""Remove one archived example family after the frozen v20 payload is built."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys


def filter_examples(payload, omit):
    """Preserve current observations, questions and retained example order exactly."""
    removed = []
    for message in payload['input']:
        original = message.get('content', [])
        kept = []
        index = 0
        while index < len(original):
            part = original[index]
            text = part.get('text', '') if part.get('type') == 'input_text' else ''
            family = ('motion' if text.startswith('Actual independently reset +') else
                      'task' if text.startswith(('Another recorded episode illustrates the physical relationship for phase ',
                                                'ARCHIVED goal-relationship example from a DIFFERENT episode,',
                                                'ARCHIVED goal appearance, BEFORE left and AFTER right;')) else None)
            if family == omit:
                if index + 1 >= len(original) or original[index + 1].get('type') != 'input_image':
                    raise ValueError('Archived example caption lacks its paired image')
                removed.append(dict(family=family, caption_sha256=hashlib.sha256(text.encode()).hexdigest()))
                index += 2
            else:
                kept.append(part)
                index += 1
        message['content'] = kept
    return removed


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--omit-example-kind', choices=['motion', 'task'], required=True)
    parser.add_argument('--frozen-source', type=Path, required=True)
    args, remaining = parser.parse_known_args()
    source = args.frozen_source.resolve()
    expected = '41a142354cdc22b05b4b2a2575758c88fbf3ec01e6726a16016f7391b4089ae3'
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise ValueError('Frozen v20 source hash mismatch')
    sys.path.insert(0, str(source.parent))
    namespace = runpy.run_path(str(source), run_name='frozen_knob_v20')
    cls = namespace['DirectAPI']
    original_build = cls.build_payload

    def build(self, sent):
        payload = original_build(self, sent)
        removed = filter_examples(payload, args.omit_example_kind)
        self.image_count = sum(p['type'] == 'input_image' for m in payload['input'] for p in m.get('content', []))
        self.log(dict(kind='archived_example_ablation', omitted_family=args.omit_example_kind,
                      removed=removed, native_tick=self.tick))
        return payload

    cls.build_payload = build
    original_audit = cls.input_audit

    def audit(self):
        return dict(original_audit(self), archived_example_ablation=args.omit_example_kind,
                    frozen_source_sha256=expected)

    cls.input_audit = audit
    sys.argv = [str(source), *remaining]
    namespace['main']()


if __name__ == '__main__':
    main()
