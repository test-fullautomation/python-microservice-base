def register_block(name):
    return lambda cls: cls


@register_block("UdsDecodeBlock")
class UdsDecodeBlockAgain:
    outputs = ("x",)
