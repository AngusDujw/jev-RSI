"""Offline-testable request-size guard for future independent Decisions slots.

Keep original image pixels, every text item and the latest camera triplet.
Drop only oldest complete image triplets, as the existing image-count adapter
already does. This is a history-window difference and must be disclosed.
"""
import json

MAX_WIRE_BYTES = 24 * 1024 * 1024
MAX_IMAGES = 126


def wire_bytes(body):
    # Must match decisions_policy.call's actual JSON serialization.
    return len(json.dumps(body).encode())


def bound_request(body, *, max_bytes=MAX_WIRE_BYTES, max_images=MAX_IMAGES):
    images = [(message, item) for message in body['input']
              for item in message.get('content', [])
              if item.get('type') == 'input_image']
    if len(images) % 3:
        raise ValueError('Expected complete three-camera observations')
    before = wire_bytes(body)
    size = before
    removed = 0
    while len(images) - removed > max_images or size > max_bytes:
        if len(images) - removed <= 3:
            raise ValueError('Text and latest camera triplet exceed request budget')
        # Remove by identity; equal data URLs may occur in different frames.
        for message, item in images[removed:removed + 3]:
            content = message['content']
            index = next(i for i, value in enumerate(content) if value is item)
            del content[index]
        removed += 3
        size = wire_bytes(body)
    return dict(wire_bytes_before=before, wire_bytes_after=size,
                max_wire_bytes=max_bytes, latest_image_limit=max_images,
                images_before=len(images), images_after=len(images) - removed,
                older_images_removed=removed, text_history_retained=True,
                latest_camera_triplet_retained=True, image_pixels_unchanged=True,
                arbitrary_codex_tools_available=False)
