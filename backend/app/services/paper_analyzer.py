def analyze_paper(parsed_paper: dict) -> dict:
    full_text = parsed_paper.get("full_text", "")
    abstract = parsed_paper.get("abstract", "")
    sections = parsed_paper.get("sections", [])

    return {
        "title": parsed_paper.get("title", ""),
        "abstract": abstract,
        "research_problem": _guess_research_problem(abstract, full_text),
        "main_contribution": _extract_contributions(full_text),
        "method_summary": _extract_section_summary(
            sections,
            ["method", "approach", "model", "algorithm", "方法", "模型", "算法"],
        ),
        "experiment_summary": _extract_section_summary(
            sections,
            ["experiment", "evaluation", "result", "实验", "评估", "结果"],
        ),
        "reproducible_parts": _guess_reproducible_parts(full_text),
        "required_inputs": _guess_required_inputs(full_text),
        "possible_code_modules": _guess_code_modules(full_text),
        "source": parsed_paper.get("source", ""),
    }


def _guess_research_problem(abstract: str, full_text: str) -> str:
    source = abstract or full_text
    if not source:
        return ""

    sentences = _split_sentences(source)
    return sentences[0] if sentences else source[:300]


def _extract_contributions(full_text: str) -> list[str]:
    if not full_text:
        return []

    keywords = ["contribution", "contributions", "we propose", "we present", "提出", "贡献"]
    sentences = _split_sentences(full_text)
    contributions = [
        sentence
        for sentence in sentences
        if any(keyword.lower() in sentence.lower() for keyword in keywords)
    ]

    return contributions[:5]


def _extract_section_summary(sections: list[dict], keywords: list[str]) -> str:
    for section in sections:
        title = section.get("title", "").lower()
        if any(keyword.lower() in title for keyword in keywords):
            return _compact(section.get("content", ""))[:1200]

    for section in sections:
        content = section.get("content", "")
        lowered_content = content.lower()
        if any(keyword.lower() in lowered_content for keyword in keywords):
            return _compact(content)[:1200]

    return ""


def _guess_reproducible_parts(full_text: str) -> list[str]:
    lowered_text = full_text.lower()
    parts = []

    candidates = [
        ("algorithm", "核心算法"),
        ("model", "模型结构"),
        ("training", "训练流程"),
        ("dataset", "数据处理"),
        ("experiment", "实验流程"),
        ("算法", "核心算法"),
        ("模型", "模型结构"),
        ("训练", "训练流程"),
        ("数据集", "数据处理"),
        ("实验", "实验流程"),
    ]

    for keyword, name in candidates:
        if keyword in lowered_text and name not in parts:
            parts.append(name)

    return parts


def _guess_required_inputs(full_text: str) -> list[str]:
    lowered_text = full_text.lower()
    inputs = []

    if "dataset" in lowered_text or "数据集" in lowered_text:
        inputs.append("论文使用的数据集")
    if "parameter" in lowered_text or "hyperparameter" in lowered_text or "参数" in lowered_text:
        inputs.append("模型参数或超参数")
    if "preprocess" in lowered_text or "预处理" in lowered_text:
        inputs.append("数据预处理规则")

    return inputs


def _guess_code_modules(full_text: str) -> list[dict]:
    lowered_text = full_text.lower()
    modules = [
        {
            "name": "main.py",
            "purpose": "运行最小复现实验入口",
        }
    ]

    if "dataset" in lowered_text or "数据集" in lowered_text:
        modules.append({"name": "data.py", "purpose": "加载和预处理数据"})
    if "model" in lowered_text or "模型" in lowered_text:
        modules.append({"name": "model.py", "purpose": "实现论文中的核心模型或算法"})
    if "train" in lowered_text or "训练" in lowered_text:
        modules.append({"name": "train.py", "purpose": "实现训练流程"})
    if "evaluate" in lowered_text or "evaluation" in lowered_text or "评估" in lowered_text:
        modules.append({"name": "evaluate.py", "purpose": "实现评估流程"})

    return modules


def _split_sentences(text: str) -> list[str]:
    normalized = _compact(text)
    sentences = [normalized]

    for separator in [". ", "。", "\n"]:
        next_sentences = []
        for sentence in sentences:
            next_sentences.extend(sentence.split(separator))
        sentences = next_sentences

    return [sentence.strip() for sentence in sentences if len(sentence.strip()) >= 20]


def _compact(text: str) -> str:
    return " ".join(text.split())
