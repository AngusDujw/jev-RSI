"""Predeclared visible boxes for the ten Goal init0 development scenes.

These are image coordinates measured from the captured 768x768 agent view.
They are task-specific perception scaffolds, not simulator object poses. A
different view or initial state must be inspected before using this table.
"""

BOXES_768 = {
    1144: ((326, 385, 440, 474), (465, 306, 644, 421)),
    1163: ((321, 277, 371, 398), (0, 278, 220, 370)),
    1252: ((321, 277, 370, 403), (0, 278, 220, 370)),
    1335: ((480, 445, 535, 525), (330, 386, 447, 477)),
    1423: ((326, 382, 440, 471), (296, 495, 450, 616)),
    1458: ((321, 278, 372, 399), (51, 51, 242, 355)),
}

LABELS = {
    1144: ("bowl", "stove support surface"),
    1163: ("wine bottle", "visible cabinet top"),
    1252: ("bowl", "visible cabinet top"),
    1335: ("cream cheese box", "bowl interior"),
    1423: ("bowl", "plate support surface"),
    1458: ("wine bottle", "wine rack opening"),
}


def recognition(task_id, reason, views):
    if task_id not in BOXES_768:
        raise ValueError(f"No fixed visible boxes for Goal task {task_id}")
    if reason not in ("initial", "pregrasp", "stalled"):
        raise ValueError(f"Fixed boxes are invalid for {reason}")
    view = views["agentview"]
    height, width = view["rgb"].shape[:2]
    if (height, width) != (768, 768):
        raise ValueError("Fixed Goal boxes require the captured 768x768 view")
    boxes = BOXES_768[task_id]
    labels = LABELS[task_id]
    return {
        role: dict(label=label, camera="agentview", bbox=list(box),
                   visible=True, receiver_kind=("open_container" if task_id == 1335
                   and role == "destination" else "support_surface"),
                   evidence="predeclared box from public init0 RGB capture")
        for role, label, box in zip(("source", "destination"), labels, boxes)
    }
