# 动画辅助函数模块，当前仅包含缓动函数
def ease_in_out(t: float) -> float:
    """缓动函数：平滑的加速和减速"""
    return t * t * (3.0 - 2.0 * t)