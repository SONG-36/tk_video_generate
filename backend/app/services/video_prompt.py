import re


VALID_IMAGE_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9._%+-])@图片([1-9]\d*)(?!\d|\.\d)"
)
INVALID_IMAGE_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"@图片(?:0\d*|-\d+|\+\d+|\d+\.\d+|(?!(?:[1-9]\d*))(?=\S|$))"
)


class VideoPromptReferenceError(ValueError):
    pass


def normalize_video_prompt(prompt: str, image_count: int) -> str:
    """权威校验结构化图片引用，并只移除规范引用的 @ 标记。"""
    if INVALID_IMAGE_REFERENCE.search(prompt):
        raise VideoPromptReferenceError(
            "图片引用格式不合法，请使用 @图片1、@图片2 等正整数编号"
        )

    for match in VALID_IMAGE_REFERENCE.finditer(prompt):
        number = int(match.group(1))
        if number > image_count:
            raise VideoPromptReferenceError(
                f"提示词引用了不存在的 @图片{number}，当前只有 {image_count} 张参考图"
            )

    return VALID_IMAGE_REFERENCE.sub(lambda match: f"图片{match.group(1)}", prompt)
