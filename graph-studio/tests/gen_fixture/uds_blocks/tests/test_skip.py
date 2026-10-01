def register_block(name):
    return lambda cls: cls


@register_block("ShouldNotAppear")
class ShouldNotAppear:
    outputs = ("x",)
