"""Submit approved historical RGB with the first fresh observation only."""
import base64
import hashlib
import json
import os
from pathlib import Path


REFERENCE_ROOT = Path('/home/ykj/project/gpt6/benchmark/gpt_as_policy_reference_assets')
MANIFEST_ENV = 'ROLLOUT_POLICY_REFERENCE_MANIFEST'


def validate_reference_manifest(path):
    raw = Path(path).read_bytes()
    manifest = json.loads(raw)
    if set(manifest) != {'version', 'images'} or manifest['version'] != 1:
        raise ValueError('Unexpected reference manifest schema')
    if not isinstance(manifest['images'], list) or not 1 <= len(manifest['images']) <= 16:
        raise ValueError('Expected one to sixteen approved raw reference images')
    images = []
    for item in manifest['images']:
        if set(item) != {'label', 'description', 'path', 'sha256'}:
            raise ValueError('Reference metadata may contain appearance evidence only')
        if any(not isinstance(item[k], str) or not item[k] or not item[k].isascii()
               for k in item):
            raise ValueError('Reference text must be nonempty English ASCII')
        source = Path(item['path'])
        if (not source.is_absolute() or source.is_symlink() or not source.is_file()
                or source.suffix != '.png'
                or not source.resolve().is_relative_to(REFERENCE_ROOT.resolve())):
            raise ValueError('Reference must be an approved ordinary PNG')
        payload = source.read_bytes()
        if not payload.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Reference bytes are not PNG')
        if hashlib.sha256(payload).hexdigest() != item['sha256']:
            raise ValueError('Reference image SHA differs from the frozen manifest')
        images.append((dict(item), payload))
    return images, hashlib.sha256(raw).hexdigest()


def add_reference_images(packet, attachments):
    manifest_path = os.environ.get(MANIFEST_ENV)
    if not manifest_path or packet.get('step_id') != 0:
        return packet, attachments
    if (len(attachments) != 3 or len(packet.get('images', [])) != 3
            or {x.get('camera') for x in packet['images']}
            != {'cam_high', 'cam_left_wrist', 'cam_right_wrist'}):
        raise ValueError('Historical attachments require the unchanged fresh three-RGB packet')
    images, manifest_sha = validate_reference_manifest(manifest_path)
    descriptors, result = [], list(attachments)
    for item, payload in images:
        descriptors.append(dict(item, attachment_index=len(result)))
        result.append(dict(type='inputImage', imageUrl='data:image/png;base64,'
                           + base64.b64encode(payload).decode('ascii')))
    visible = dict(packet, historical_reference_images=descriptors,
        historical_reference_note='Attachments follow the current three RGB images. '
        'These labelled historical appearance examples are not current observations, '
        'current object poses, action targets or complete task outcomes.')
    receipt = Path(manifest_path).with_name('reference-image-delivery.json')
    with receipt.open('x') as stream:
        json.dump(dict(status='constructed_for_stdio_reply', step_id=0,
            manifest_sha256=manifest_sha, live_rgb_count=len(attachments),
            historical_rgb_count=len(images), historical_images=descriptors,
            scope='Payload construction, not evidence of model attention or perception.'), stream, indent=2)
        stream.write('\n')
    return visible, result


def mark_reference_reply_submitted(packet, enabled):
    path = os.environ.get(MANIFEST_ENV)
    if not enabled or not path or packet.get('step_id') != 0:
        return
    receipt = Path(path).with_name('reference-image-delivery.json')
    data = json.loads(receipt.read_text())
    if data['status'] != 'constructed_for_stdio_reply':
        raise ValueError('Reference reply was already marked submitted')
    data['status'] = 'stdio_reply_submitted_not_attention_verified'
    receipt.write_text(json.dumps(data, indent=2) + '\n')


def install_reference_delivery(source):
    """Patch only a fresh local actor runtime; native simulation is untouched."""
    if '.policy_reference_images import' in source:
        raise ValueError('Reference delivery is already installed')
    anchor = "    return [dict(type='inputText', text=json.dumps(visible_packet, separators=(',', ':'))), *attachments]"
    after_reply = '                call_index += 1\n'
    if source.count(anchor) != 1 or source.count(after_reply) != 1:
        raise ValueError('Reference delivery anchors are not unique')
    source = source.replace(anchor,
        "    if images:\n"
        "        from .policy_reference_images import add_reference_images\n"
        "        visible_packet, attachments = add_reference_images(visible_packet, attachments)\n"
        + anchor)
    return source.replace(after_reply,
        "                from .policy_reference_images import mark_reference_reply_submitted\n"
        "                mark_reference_reply_submitted(packet, success and name != 'pi05_infer')\n"
        + after_reply)
