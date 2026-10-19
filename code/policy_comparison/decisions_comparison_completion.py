"""Original categorical comparison with an explicit Decisions image-count bound."""
import json

import decisions_policy as original

MAX_IMAGES=126  # Complete three-camera observations within the API's128 limit.
original_call=original.call


def bound_history(messages):
    count=sum(x.get('type')=='input_image' for m in messages for x in m.get('content',[]))
    remove=max(0,count-MAX_IMAGES)
    removed=remove
    for message in messages:
        kept=[]
        for item in message.get('content',[]):
            if remove and item.get('type')=='input_image':remove-=1
            else:kept.append(item)
        message['content']=kept
    return removed


def bounded_call(body,key,folder):
    removed=bound_history(body['input'])
    result=original_call(body,key,folder)
    (folder/'context_policy.json').write_text(json.dumps(dict(
        latest_image_limit=MAX_IMAGES,older_images_removed=removed,
        text_history_retained=True,arbitrary_codex_tools_available=False))+'\n')
    return result


if __name__=='__main__':
    original.call=bounded_call
    original.main()
