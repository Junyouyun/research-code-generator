EXPANSION_KEYWORDS = (
    "对比",
    "比较",
    "类似",
    "相关",
    "扩展",
    "发散",
    "衍生",
    "其他论文",
    "别的论文",
    "已有研究",
    "相关研究",
    "前人工作",
    "相似方法",
    "同类方法",
    "替代方法",
    "改进方向",
    "后续工作",
    "有什么区别",
    "有什么联系",
    "和其他方法相比",
    "sota",
    "state of the art",
    "related work",
    "compare",
    "comparison",
    "similar",
    "related",
    "other papers",
    "prior work",
    "future work",
    "extension",
    "extend",
)


def should_expand_to_related_papers(question: str) -> bool:
    normalized = question.strip().lower()
    return any(keyword in normalized for keyword in EXPANSION_KEYWORDS)
